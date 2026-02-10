import time, threading
from flask import Flask
from flask_socketio import SocketIO, emit

class Website:
    def __init__(self, flight_computer=None):
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        self.flight_computer = flight_computer   #pass FlightComputer() here

        self._streaming = False
        self._stream_thread = None
        self._client_count = 0
        self._lock = threading.Lock()

        # WebSocket events
        self.socketio.on_event("connect", self.ws_connect)
        self.socketio.on_event("disconnect", self.ws_disconnect)
        self.socketio.on_event("telemetry/start", self.ws_start_stream)
        self.socketio.on_event("telemetry/stop", self.ws_stop_stream)

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

    def ws_connect(self):
        with self._lock:
            self._client_count += 1
            clients = self._client_count
        emit("status", {"ok": True, "msg": "connected", "clients": clients})

    def ws_disconnect(self):
        with self._lock:
            self._client_count = max(0, self._client_count - 1)
            no_clients = (self._client_count == 0)
            if no_clients:
                self._streaming = False  # stop if nobody is watching

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

            self._stream_thread = threading.Thread(
                target=self._telemetry_loop,
                args=(sample_hz,),
                daemon=True
            )
            self._stream_thread.start()

        emit("status", {"ok": True, "msg": "stream started", "sample_hz": sample_hz})

    def ws_stop_stream(self):
        with self._lock:
            self._streaming = False
        emit("status", {"ok": True, "msg": "stream stopped"})

    def _telemetry_loop(self, sample_hz: int):
        period = 1.0 / sample_hz
        last_err_ms = 0

        while True:
            with self._lock:
                if not self._streaming:
                    break

            try:
                payload = {
                    "ts_ms": int(time.time() * 1000),
                    "fc": self.read_telemetry_snapshot()
                }
                # broadcast to everyone
                self.socketio.emit("telemetry", payload)

            except Exception as e:
                now_ms = int(time.time() * 1000)
                if now_ms - last_err_ms > 1000:
                    self.socketio.emit("status", {"ok": False, "error": str(e)})
                    last_err_ms = now_ms
            self.socketio.sleep(period)

    def run(self, host="0.0.0.0", port=5000):
        self.socketio.run(self.app, host=host, port=port)

if __name__ == "__main__":
    Website().run(port=5001)
