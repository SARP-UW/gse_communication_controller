"""Generic GSE spoke: connects an existing controller program to the GSE hub.

To add to a controller codebase, copy this file AND the generated/ folder next to each other.
Then, in the controller's main(), after its hardware objects exist:

    from spoke import Spoke

    spoke = Spoke('cc', {
        'set_valve': set_valve,      # command name -> handler function
        'get_state': get_state,
    })
    spoke.start()   # returns immediately; the spoke runs in a background thread
    ...             # the controller's existing main loop, unchanged
    spoke.stop()    # on shutdown

Handlers:
    - take one argument: the command's args, a dict of strings (e.g. {'id': '3', 'state': 'open'})
    - return a dict (sent back to the hub as `data`) or None
    - returning means the command COMPLETED; raising an exception means it FAILED
      (the exception text is sent back as `message`)
    - are ordinary blocking functions; they run one at a time, in a worker thread

The spoke never raises into the controller program. If the hub is down or the network drops,
it logs the problem and keeps reconnecting. `spoke.connected` says whether the hub link is up.

Hub address: the `hub_addr` argument, else the GSE_HUB_ADDR environment variable,
else localhost:50051.

Run `python spoke.py <node_id>` to start a test spoke (see the bottom of this file).
"""
import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

# The generated stubs import each other by bare module name, so their folder must be on the path.
# Found relative to this file, so it works from any working directory.
sys.path.insert(0, str(Path(__file__).parent / 'generated'))

import grpc
import controller_pb2
import controller_pb2_grpc

log = logging.getLogger('gse.spoke')

# Ping the hub every 10 s; if a ping goes unanswered for 5 s, treat the connection as dead.
# Without this, a pulled cable can go unnoticed for hours. The hub allows this ping rate (see hub.py).
KEEPALIVE_OPTIONS = [
    ('grpc.keepalive_time_ms', 10_000),
    ('grpc.keepalive_timeout_ms', 5_000),
    ('grpc.http2.ping_timeout_ms', 5_000),  # what actually enforces the 5 s in this gRPC version (default 60 s)
    ('grpc.keepalive_permit_without_calls', 1),
    ('grpc.http2.max_pings_without_data', 0),  # keep pinging while no commands flow (default stops after 2)
]

MAX_RETRY_DELAY = 10  # seconds between reconnect attempts, at most


class Spoke:
    def __init__(self, node_id, commands, hub_addr=None):
        self.node_id = node_id
        self.commands = commands  # command name -> handler function
        self.hub_addr = hub_addr or os.environ.get('GSE_HUB_ADDR', 'localhost:50051')
        self.connected = False  # True while registered with the hub
        self._outgoing = None  # current session's message queue; publish() puts telemetry on it

        self._thread = None
        self._loop = None
        self._task = None

    def start(self):
        """Start the spoke in a background thread. Returns immediately."""
        # daemon=True: the controller program can always exit, even if the spoke is stuck.
        self._thread = threading.Thread(
            target=asyncio.run, args=(self._main(),), name=f'gse-spoke-{self.node_id}', daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=5):
        """Disconnect from the hub and stop the background thread."""
        if self._loop is not None:
            # The spoke runs on its own event loop in another thread, so ask that loop to cancel it.
            self._loop.call_soon_threadsafe(self._task.cancel)
        if self._thread is not None:
            self._thread.join(timeout)

    def publish(self, values):
        """Send telemetry to the hub: a dict of name -> number/string/bool (e.g. {'pt1': 512.3}).
        Safe to call from any thread. Dropped if the hub link is down (telemetry is lossy by design),
        and never raises into the controller program."""
        try:
            outgoing = self._outgoing
            if not self.connected or outgoing is None:
                return
            update = controller_pb2.StatusUpdate()
            update.timestamp.GetCurrentTime()
            update.data.update(values)
            self._loop.call_soon_threadsafe(outgoing.put_nowait, controller_pb2.SpokeMessage(status=update))
        except Exception:
            log.exception('%s: could not publish telemetry', self.node_id)

    async def _main(self):
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        try:
            await self._run_forever()
        except asyncio.CancelledError:
            pass  # stop() was called
        finally:
            self.connected = False
            log.info('%s: spoke stopped', self.node_id)

    async def _run_forever(self):
        """Connect to the hub, and reconnect whenever the connection ends."""
        retry_delay = 1
        async with grpc.aio.insecure_channel(self.hub_addr, options=KEEPALIVE_OPTIONS) as channel:
            hub = controller_pb2_grpc.ControllerStub(channel)
            while True:
                try:
                    await self._session(hub)
                    log.warning('%s: hub closed the connection', self.node_id)
                except grpc.aio.AioRpcError as error:
                    if error.code() == grpc.StatusCode.ALREADY_EXISTS:
                        # Another spoke connected with the same node_id. Reconnecting would just kick it
                        # off again, and the two would keep replacing each other, so stop instead.
                        log.error('%s: %s. Is another spoke using this node_id? Not reconnecting.',
                                  self.node_id, error.details())
                        return
                    log.warning('%s: lost connection to hub at %s (%s)', self.node_id, self.hub_addr, error.code().name)
                except Exception:
                    # Never let a bug in here take down the controller program: log it and reconnect.
                    log.exception('%s: unexpected error', self.node_id)

                # Retry quickly after a working connection drops; back off while the hub stays unreachable.
                if self.connected:
                    retry_delay = 1
                self.connected = False
                log.info('%s: reconnecting in %d s', self.node_id, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, MAX_RETRY_DELAY)

    async def _session(self, hub):
        """One connection to the hub: say hello, then answer commands until the connection ends."""
        # Messages to the hub go through this queue; gRPC sends whatever outgoing_messages() yields.
        outgoing = self._outgoing = asyncio.Queue()
        outgoing.put_nowait(controller_pb2.SpokeMessage(hello=controller_pb2.Hello(node_id=self.node_id)))

        async def outgoing_messages():
            while True:
                yield await outgoing.get()

        # wait_for_ready: if the hub isn't up yet, wait for it instead of failing right away.
        stream = hub.Connect(outgoing_messages(), wait_for_ready=True)
        await stream.wait_for_connection()  # returns once the hub has registered this spoke
        self.connected = True
        log.info('%s: connected to hub at %s', self.node_id, self.hub_addr)

        async for command in stream:
            response = await self._handle(command)
            outgoing.put_nowait(controller_pb2.SpokeMessage(response=response))

    async def _handle(self, command):
        """Run the handler for one command and build the Response for it."""
        response = controller_pb2.Response(command_id=command.command_id)
        name = command.command_name

        handler = self.commands.get(name)
        if handler is None:
            response.status = controller_pb2.FAILED
            response.message = f'unknown command: {name}'
            return response

        try:
            # one command at a time; run handlers concurrently if a slow one starts delaying others
            # Handlers block (hardware calls), so run them in a worker thread to keep the connection responsive.
            result = await asyncio.to_thread(handler, dict(command.args))
            if result:
                response.data.update(result)
            response.status = controller_pb2.COMPLETED
        except Exception as error:
            log.exception('%s: command %s failed', self.node_id, name)
            response.ClearField('data')
            response.status = controller_pb2.FAILED
            response.message = f'{type(error).__name__}: {error}'
        return response


# Test spoke: `python spoke.py <node_id>`. Also an example of how a controller wires in a Spoke.
if __name__ == '__main__':
    import time

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

    def ping(args):
        return {}

    def echo(args):
        return dict(args)

    def slow(args):
        time.sleep(float(args.get('seconds', '3')))
        return {}

    def fail(args):
        raise RuntimeError(args.get('reason', 'requested failure'))

    spoke = Spoke(sys.argv[1], {'ping': ping, 'echo': echo, 'slow': slow, 'fail': fail})
    spoke.start()
    try:
        n = 0
        while True:  # stands in for the controller's existing main loop
            n += 1
            spoke.publish({'counter': n, 'uptime': round(n * 0.1, 1)})  # example telemetry
            time.sleep(0.1)
    except KeyboardInterrupt:
        spoke.stop()