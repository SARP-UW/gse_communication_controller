"""
Bench test REPL: drive each hardware path the main loop uses, one command at a time.

    python3 -m src.bench [-c config/default/config.json]
"""
import argparse
import cmd
import json
import os
import threading
import time

from src.controller import Controller
from src.flight_computer import FlightComputer

_DEFAULT_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config/default/config.json')
_COMM_POLL_INTERVAL = 0.005  # same as main.py


class Bench(cmd.Cmd):
    prompt = "(gse) "

    def __init__(self, controller: Controller, flight_computer: FlightComputer) -> None:
        super().__init__()
        self.controller = controller
        self.fc = flight_computer
        self.verbose = True
        self._loop_thread = None
        self._loop_stop = threading.Event()
        self.intro = "GSE bench. 'help' lists commands."
        self.do_loop("on")

    # --- comm loop (mirrors main.py) ---

    def _comm_loop(self) -> None:
        while not self._loop_stop.is_set():
            try:
                for packet in self.controller.receive_packets():
                    self._log("RX", packet)
                    ping_id = self.fc.process_packet(packet)
                    if ping_id is not None:
                        response = self.fc.build_comm_response(ping_id)
                        self.controller.transmit_packets([response])
                        self._log("TX", response)
            except Exception as e:
                print(f"\ncomm loop error: {e!r}")
            time.sleep(_COMM_POLL_INTERVAL)

    def _log(self, direction: str, packet: bytes) -> None:
        if self.verbose:
            print(f"\n{direction} [{self.controller.comm_link_type}] {bytes(packet).hex(' ')}")

    def do_loop(self, arg: str) -> None:
        """loop on|off  - auto-respond to FC comm packets (like main.py)"""
        if arg == "on" and self._loop_thread is None:
            self._loop_stop.clear()
            self._loop_thread = threading.Thread(target=self._comm_loop, daemon=True)
            self._loop_thread.start()
        elif arg == "off" and self._loop_thread is not None:
            self._loop_stop.set()
            self._loop_thread.join()
            self._loop_thread = None
        print(f"comm loop: {'ON' if self._loop_thread else 'OFF'}")

    def do_verbose(self, arg: str) -> None:
        """verbose on|off  - print RX/TX hex"""
        self.verbose = arg != "off"

    # --- CC hardware ---

    def do_valves(self, arg: str) -> None:
        """valves  - list passthrough valve states"""
        states = self.controller.passthrough_valve_states
        for v in self.controller.passthrough_valve_info:
            print(f"  {v['id']} {v['name']:<20} {states[v['id']]}")

    def do_valve(self, arg: str) -> None:
        """valve <id> on|off  - set passthrough valve override (relay)"""
        valve_id, state = arg.split()
        self.controller.set_passthrough_valve_state(int(valve_id), state == "on")
        self.do_valves("")

    def do_qdc(self, arg: str) -> None:
        """qdc [<id> locked|released]  - show or set QDC actuators"""
        if arg:
            actuator_id, state = arg.split()
            self.controller.set_qdc_actuator_state(int(actuator_id), state)
        for actuator_id, state in self.controller.qdc_actuator_states.items():
            print(f"  {actuator_id} {state}")

    def do_pressure(self, arg: str) -> None:
        """pressure  - read passthrough pressure sensors (PSI)"""
        data = self.controller.passthrough_pressure_sensor_data
        for s in self.controller.passthrough_pressure_sensor_info:
            print(f"  {s['id']} {s['name']:<20} {data[s['id']]:.2f}")

    # --- links ---

    def do_link(self, arg: str) -> None:
        """link [rs485|radio]  - show or set the TX link (RX always listens on both)"""
        if arg:
            self.controller.comm_link_type = arg
        print(f"link: {self.controller.comm_link_type}")

    def do_send(self, arg: str) -> None:
        """send <hex>  - transmit one packet on the active link (RS485 adds the length prefix)"""
        packet = bytearray.fromhex(arg)
        self.controller.transmit_packets([packet])
        self._log("TX", packet)

    def do_rawrs485(self, arg: str) -> None:
        """rawrs485 <hex>  - write raw bytes to RS485, no framing (scope tests)"""
        self.controller._rs485.write(bytearray.fromhex(arg))

    # --- flight computer ---

    def do_fc(self, arg: str) -> None:
        """fc  - show last FC comm status"""
        print(f"  mode={self.fc.mode} last_ping={self.fc._last_ping_id} uptime={self.fc.time_since_start}ms")
        print(f"  command: {self.fc.command_status}")

    def do_fcvalve(self, arg: str) -> None:
        """fcvalve <id> <0|1>  - queue FC valve command for the next comm response"""
        valve_id, state = arg.split()
        self.fc.set_valve(int(valve_id), int(state))

    def do_fcpulse(self, arg: str) -> None:
        """fcpulse <id> <ms>  - queue FC valve pulse"""
        valve_id, duration_ms = arg.split()
        self.fc.pulse_valve(int(valve_id), int(duration_ms))

    def do_fcmode(self, arg: str) -> None:
        """fcmode <n>  - queue FC system mode change"""
        self.fc.mode = int(arg)

    def do_fclink(self, arg: str) -> None:
        """fclink <0|1>  - queue FC comm link change (0 = RS485, 1 = radio)"""
        self.fc.comm_link = int(arg)

    # --- plumbing ---

    def do_quit(self, arg: str) -> bool:
        """quit  - shut down hardware and exit"""
        return True

    do_EOF = do_quit

    def emptyline(self) -> None:
        pass

    def onecmd(self, line: str):
        try:
            return super().onecmd(line)
        except Exception as e:
            print(f"error: {e!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GSE bench test REPL")
    parser.add_argument('-c', '--config', default=_DEFAULT_CONFIG)
    with open(parser.parse_args().config) as f:
        config = json.load(f)

    controller = Controller.from_config(config)
    flight_computer = FlightComputer.from_config(config['flight_computer'])
    bench = Bench(controller, flight_computer)
    try:
        bench.cmdloop()
    except KeyboardInterrupt:
        pass
    finally:
        bench.do_loop("off")
        flight_computer.shutdown()
        controller.shutdown()


if __name__ == "__main__":
    main()
