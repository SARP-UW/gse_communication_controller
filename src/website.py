import time, threading
import os
from typing import Callable, Dict
from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from .logger import Logger
from . import settings

# Minimum permissable port value
MIN_PORT_VALUE = 1

# Maximum permissable port value
MAX_PORT_VALUE = 65535

# Absolute path to website directory
_WEBSITE_TOP_DIR_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "website")

# Absolute path to website template folder
WEBSITE_TEMPLATE_FOLDER_PATH = os.path.join(_WEBSITE_TOP_DIR_PATH, "templates")
print(WEBSITE_TEMPLATE_FOLDER_PATH)
# Absolute path to website static folder
WEBSITE_STATIC_FOLDER_PATH = os.path.join(_WEBSITE_TOP_DIR_PATH, "static")

class Website:

    def _update_website(self) -> None:
        """
        Background thread method to periodically check user heartbeats.
        """
        interval = 1.0 / settings.WEBSITE_THREAD_UPDATE_RATE
        while True:
            with self._lock:
                if self._shutdown_flag:
                    break
                try:
                    current_time = time.time()
                    for user, last_heartbeat in dict(self._user_heartbeats).items():
                        if (current_time - last_heartbeat) > settings.WEBSITE_HEARTBEAT_TIMEOUT:
                            if settings.PRINT_WEBSITE_STATUS:
                                print(f"WEBSITE STATUS: User {user} disconnected.")
                            self._website_logger.log_data([user, "status", "User disconnected"])
                            del self._user_heartbeats[user]
                    time.sleep(interval)
                except Exception as e:
                    if settings.PRINT_WEBSITE_ERRORS:
                        print(f"WEBSITE ERROR: Update website error: {e}")

    def __init__(self, port: int, website_log_path: str, flight_computer=None, controller=None):
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")

        self.flight_computer = flight_computer   #pass FlightComputer() here
        self.controller = controller

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
        self._port = port
        self._shutdown_flag = False
        self._user_heartbeats: Dict[str, float] = {}
        self._website_logger = Logger(
            path = website_log_path,
            col = ["user", "type", "status"]
        )

        # WebSocket events
        self.socketio.on_event("connect", self.ws_connect)
        self.socketio.on_event("disconnect", self.ws_disconnect)
        self.socketio.on_event("telemetry/start", self.ws_start_stream)
        self.socketio.on_event("telemetry/stop", self.ws_stop_stream)
        self.socketio.on_event("command", self.ws_command)

        self._app = Flask(
            __name__,
            template_folder = WEBSITE_TEMPLATE_FOLDER_PATH,
            static_folder = WEBSITE_STATIC_FOLDER_PATH
        )
        self.socketio.init_app(self._app)

        @self._app.route('/')
        def home():
            return render_template('index.html')

        @self._app.get("/api/send_heartbeat")
        def send_heartbeat():
            """
            Heartbeat endpoint to keep track of connected users.
            """
            user = request.remote_addr
            with self._lock:
                if self._shutdown_flag:
                    if settings.PRINT_WEBSITE_ERRORS:
                        print(f"WEBSITE ERROR: User attempted to send heartbeat while website shut down.")
                    self._website_logger.log_data([user, "error", "Attempted to send heartbeat while website shut down."])
                    return jsonify({"status": "error", "message": "Website has been shut down"}), 500
                try:
                    if user not in self._user_heartbeats:
                        if settings.PRINT_WEBSITE_STATUS:
                            print(f"WEBSITE STATUS: User {user} connected.")
                        self._website_logger.log_data([user, "status", "User connected"])
                    self._user_heartbeats[user] = time.time()
                    return jsonify({"status": "success"})
                except Exception as e:
                    if settings.PRINT_WEBSITE_ERRORS:
                        print(f"WEBSITE ERROR: Failed to process heartbeat from {user}: {e}")
                    self._website_logger.log_data([user, "error", f"Failed to process heartbeat: {e}"])
                    return jsonify({"status": "error", "message": "Failed to process heartbeat"}), 500  

        if settings.PRINT_WEBSITE_STATUS:
            print(f"WEBSITE STATUS: Website running...")
            print(f"WEBSITE INFO: Website id: {id(self)}")
            print(f"WEBSITE INFO: Controller id: {id(self.flight_computer)}")
            print(f"WEBSITE INFO: Website port: {self._port}")
            print(f"WEBSITE INFO: Polling rate: {settings.WEBSITE_THREAD_UPDATE_RATE}Hz")
            print(f"WEBSITE INFO: Heartbeat timeout: {settings.WEBSITE_HEARTBEAT_TIMEOUT}s")
            print(f"WEBSITE INFO: Website logger: {str(self._website_logger)}")
            
        self._website_logger.log_data(["system", "status", "Server started"])
        self._website_logger.log_data(["system", "info", f"Website id: {id(self)}"])
        self._website_logger.log_data(["system", "info", f"Controller id: {id(self.flight_computer)}"])
        self._website_logger.log_data(["system", "info", f"Website port: {self._port}"])
        self._website_logger.log_data(["system", "info", f"Polling rate: {settings.WEBSITE_THREAD_UPDATE_RATE}Hz"])
        self._website_logger.log_data(["system", "info", f"Heartbeat timeout: {settings.WEBSITE_HEARTBEAT_TIMEOUT}s"])
        self._website_logger.log_data(["system", "info", f"Website logger: {str(self._website_logger)}"])

        # Start background thread to update website data
        update_website_thread = threading.Thread(target = self._update_website, daemon = True)
        update_website_thread.start()

        flask_thread = threading.Thread(
            target = lambda: self.socketio.run(self._app, host = '0.0.0.0', port = self._port),
            daemon = True
        )
        flask_thread.start()

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
        if self.controller is None:
            raise RuntimeError("No controller passed into Website(...)")
        
        fc = self.flight_computer
        cc = self.controller

        fc_snapshot = {
            "time_since_start_ms": fc.time_since_start,
            "mode": fc.mode,
            "sleep": fc.sleep,
            "is_ready": fc.is_ready,
            "adc": self._jsonify_keys(fc.adc_sensor_data),
            "valves": self._jsonify_keys(fc.valve_states),
            "servos": self._jsonify_keys(fc.servo_states),
            "command_status": fc.command_status,
        }
        cc_snapshot = {
            "sensors": self._jsonify_keys(cc.passthrough_pressure_sensor_data),
            "valves": self._jsonify_keys(cc.passthrough_valve_states),
            "qdc": self._jsonify_keys(cc.qdc_actuator_states),
        }
        return {
            "fc": fc_snapshot,
            "cc": cc_snapshot
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
            
            # Note, if i2c reads become slow enough to cause noticeable blocking we can consider moving the read outside the lock.
            telemetry_snapshot = self.read_telemetry_snapshot()
        return {
            "ts_ms": int(time.time() * 1000),
            "seq": seq,
            "fc": telemetry_snapshot["fc"],
            "cc": telemetry_snapshot["cc"],
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
        if cmd_type is None:
            raise ValueError(f"Unsupported command type: {cmd_type}")
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


    def __del__(self) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        """
        Shuts down the website. After this function is called, calls to other methods will raise an exception.
        """
        with self._lock:
            if self._shutdown_flag:
                return
            self._shutdown_flag = True
            if settings.PRINT_WEBSITE_STATUS:
                print(f"WEBSITE STATUS: Website shutting down")
            self._website_logger.log_data(["system", "status", "Server shutting down"])
