import time, threading
from typing import Callable
from flask import Flask, request
from flask_socketio import SocketIO, emit

class Website:
    def __init__(self, flight_computer=None):
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        self.flight_computer = flight_computer   #pass FlightComputer() here

        self._start_time_ms = int(time.time() * 1000)
        self._streaming = False
        self._sample_hz = 0
        self._stream_thread = None
        self._client_count = 0
        self._telemetry_seq = 0
        self._last_payload_seq = 0
        self._event_seq = 0
        self._action_seq = 0
        self._lock = threading.Lock()

        # WebSocket events
        self.socketio.on_event("connect", self.ws_connect)
        self.socketio.on_event("disconnect", self.ws_disconnect)
        self.socketio.on_event("telemetry/start", self.ws_start_stream)
        self.socketio.on_event("telemetry/stop", self.ws_stop_stream)
        self.socketio.on_event("command", self.ws_command)

    # ---------- helpers ----------
    @staticmethod
    def _jsonify_keys(d):
        """Convert dict keys to strings so it's JSON-safe."""
        if not isinstance(d, dict):
            return d
        return {str(k): v for k, v in d.items()}

    def read_telemetry_snapshot(self):
        """One clean snapshot of everything useful."""
        if self.flight_computer is None:
            raise RuntimeError("No flight_computer passed into Website(...)")

        fc = self.flight_computer
        return {
            "time_since_start_ms": fc.time_since_start,
            "mode": fc.mode,
            "sleep": fc.sleep,
            "is_ready": fc.is_ready,
            "adc": self._jsonify_keys(fc.adc_sensor_data),
            "valves": self._jsonify_keys(fc.valve_states),
            "servos": self._jsonify_keys(fc.servo_states),
            "command_status": fc.command_status,
        }

    def build_telemetry_payload(self):
        """Minimal payload contract emitted to clients."""
        with self._lock:
            self._telemetry_seq += 1
            seq = self._telemetry_seq
            self._last_payload_seq = seq
            client_count = self._client_count
            sample_hz = self._sample_hz
            streaming = self._streaming

        return {
            "ts_ms": int(time.time() * 1000),
            "seq": seq,
            "fc": self.read_telemetry_snapshot(),
            "api": {
                "connected_clients": client_count,
                "sample_hz": sample_hz,
                "streaming": streaming,
                "last_payload_seq": seq,
                "uptime_ms": int(time.time() * 1000) - self._start_time_ms,
            },
        }

    def _emit_event(self, event_type: str, **fields):
        with self._lock:
            self._event_seq += 1
            event_id = self._event_seq
        payload = {
            "ts_ms": int(time.time() * 1000),
            "event_id": event_id,
            "type": event_type,
            **fields,
        }
        self.socketio.emit("event", payload)

    def _next_action_id(self) -> int:
        with self._lock:
            self._action_seq += 1
            return self._action_seq

    @staticmethod
    def _set_mode(fc, command: dict) -> None:
        fc.mode = int(command["mode"])

    @staticmethod
    def _set_sleep(fc, command: dict) -> None:
        sleep_value = command["sleep"]
        if not isinstance(sleep_value, bool):
            raise ValueError("sleep must be a boolean")
        fc.sleep = sleep_value

    def _execute_command(self, command: dict) -> None:
        if self.flight_computer is None:
            raise RuntimeError("No flight_computer passed into Website(...)")

        fc = self.flight_computer
        cmd_type = command.get("type")
        command_map: dict[str, Callable] = {
            "set_valve": lambda target_fc, cmd: target_fc.set_valve(int(cmd["valve_id"]), int(cmd["state"])),
            "pulse_valve": lambda target_fc, cmd: target_fc.pulse_valve(int(cmd["valve_id"]), int(cmd["duration_ms"])),
            "set_servo": lambda target_fc, cmd: target_fc.set_servo(int(cmd["servo_id"]), float(cmd["value"])),
            "pulse_servo": lambda target_fc, cmd: target_fc.pulse_servo(
                int(cmd["servo_id"]),
                float(cmd["value"]),
                int(cmd["duration_ms"]),
            ),
            "set_mode": self._set_mode,
            "set_sleep": self._set_sleep,
            "custom_command": lambda target_fc, cmd: target_fc.send_custom_command(
                int(cmd["command_id"]),
                [int(v) for v in cmd.get("args", [])],
            ),
        }

        command_handler = command_map.get(cmd_type)
        if command_handler is None:
            raise ValueError(f"Unsupported command type: {cmd_type}")
        command_handler(fc, command)

    def _run_command(self, action_id: int, source_client_id: str, command: dict) -> None:
        cmd_type = command.get("type", "unknown")
        self._emit_event(
            "action_started",
            action_id=action_id,
            source_client_id=source_client_id,
            command=command,
            command_type=cmd_type,
        )

        try:
            self._execute_command(command)
            self._emit_event(
                "action_completed",
                action_id=action_id,
                source_client_id=source_client_id,
                command=command,
                command_type=cmd_type,
            )
            self.socketio.emit("telemetry", self.build_telemetry_payload())
        except Exception as e:
            self._emit_event(
                "action_failed",
                action_id=action_id,
                source_client_id=source_client_id,
                command=command,
                command_type=cmd_type,
                reason=str(e),
            )
            self.socketio.emit("status", {"ok": False, "error": str(e), "action_id": action_id})

    def ws_connect(self, auth=None):
        with self._lock:
            self._client_count += 1
            clients = self._client_count
        emit("status", {"ok": True, "msg": "connected", "clients": clients})
        self._emit_event("state_changed", connected_clients=clients)

    def ws_disconnect(self, reason=None):
        with self._lock:
            self._client_count = max(0, self._client_count - 1)
            no_clients = (self._client_count == 0)
            clients = self._client_count
            if no_clients:
                self._streaming = False  # stop if nobody is watching
                self._sample_hz = 0
            streaming = self._streaming
            sample_hz = self._sample_hz
        self._emit_event("state_changed", connected_clients=clients, streaming=streaming, sample_hz=sample_hz)

    def ws_start_stream(self, data=None):
        data = data or {}
        sample_hz = data.get("sample_hz", 50)

        # coerce + validate
        try:
            sample_hz = int(sample_hz)
        except (TypeError, ValueError):
            emit("status", {"ok": False, "error": "sample_hz must be an integer"})
            return

        if not (1 <= sample_hz <= 1000):
            emit("status", {"ok": False, "error": "sample_hz out of bounds (1..1000)"})
            return

        with self._lock:
            if self._streaming:
                emit("status", {"ok": True, "msg": "already streaming"})
                return
            self._streaming = True
            self._sample_hz = sample_hz

            self._stream_thread = threading.Thread(
                target=self._telemetry_loop,
                args=(sample_hz,),
                daemon=True
            )
            self._stream_thread.start()

        emit("status", {"ok": True, "msg": "stream started", "sample_hz": sample_hz})
        self._emit_event("state_changed", streaming=True, sample_hz=sample_hz)

    def ws_stop_stream(self, data=None):
        with self._lock:
            self._streaming = False
            self._sample_hz = 0
        emit("status", {"ok": True, "msg": "stream stopped"})
        self._emit_event("state_changed", streaming=False, sample_hz=0)

    def ws_command(self, data=None):
        command = data or {}
        if not isinstance(command, dict):
            emit("status", {"ok": False, "error": "command payload must be an object"})
            return
        if "type" not in command:
            emit("status", {"ok": False, "error": "command.type is required"})
            return

        source_client_id = str(getattr(request, "sid", "unknown"))
        action_id = self._next_action_id()
        self._emit_event(
            "command_accepted",
            action_id=action_id,
            source_client_id=source_client_id,
            command=command,
            command_type=command.get("type"),
        )
        emit("status", {"ok": True, "msg": "command accepted", "action_id": action_id})

        t = threading.Thread(
            target=self._run_command,
            args=(action_id, source_client_id, command),
            daemon=True,
        )
        t.start()

    def _telemetry_loop(self, sample_hz: int):
        period = 1.0 / sample_hz
        last_err_ms = 0

        while True:
            with self._lock:
                if not self._streaming:
                    break

            try:
                payload = self.build_telemetry_payload()
                # broadcast to everyone
                self.socketio.emit("telemetry", payload)

            except Exception as e:
                now_ms = int(time.time() * 1000)
                if now_ms - last_err_ms > 1000:
                    self.socketio.emit("status", {"ok": False, "error": str(e)})
                    self._emit_event("action_failed", reason=str(e))
                    last_err_ms = now_ms
            time.sleep(period)

    def run(self, host="0.0.0.0", port=5000):
        self.socketio.run(self.app, host=host, port=port)

if __name__ == "__main__":
    Website().run(port=5001)
