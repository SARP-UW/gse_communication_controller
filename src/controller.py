import os
import struct
from typing import List, Dict

from src.radio import Radio
from src.rs485_bus import RS485Bus
from src.passthrough_valve import PassthroughValve
from src.passthrough_pressure_sensor import PassthroughPressureSensor
from src.qdc_actuator import QDCActuator

# Repo root — used to resolve __rel__ paths from config
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tracks whether a Controller is already alive (singleton enforcement)
_controller_init: bool = False


def _resolve_config_path(path: str) -> str:
    """Converts a config path string to an absolute path.

    Handles the __rel__ prefix (relative to repo root) and normalises
    Windows-style backslashes.
    """
    path = path.replace("\\", "/")
    if path.startswith("__rel__/"):
        return os.path.join(_REPO_ROOT, path[len("__rel__/"):])
    return path


class Controller:

    def __init__(self, radio: Radio, rs485: RS485Bus,
                 valves: List[PassthroughValve],
                 sensors: List[PassthroughPressureSensor],
                 qdc_actuators: List[QDCActuator]) -> None:
        """
        Initialises a Controller with communication interfaces and hardware drivers.

        Args:
            radio: Initialised Radio instance.
            rs485: Initialised RS485Bus instance.
            valves: List of initialised PassthroughValve instances.
            sensors: List of initialised PassthroughPressureSensor instances.
            qdc_actuators: List of initialised QDCActuator instances.
        """
        # Set before singleton check so __del__ -> shutdown() is safe if __init__ raises
        self._shutdown_flag: bool = False
        self._radio: Radio = radio
        self._rs485: RS485Bus = rs485

        global _controller_init
        if _controller_init:
            raise RuntimeError("Controller has already been initialized")
        _controller_init = True

        self._active_link: str = "rs485"
        self._rs485_rx_buffer: bytearray = bytearray()

        self._passthrough_valves: List[PassthroughValve] = valves
        self._passthrough_pressure_sensors: List[PassthroughPressureSensor] = sensors
        self._qdc_actuators: List[QDCActuator] = qdc_actuators

    @classmethod
    def from_config(cls, config: Dict) -> "Controller":
        """
        Initialises a Controller from the full config dictionary.

        Args:
            config: The parsed config.json dict.
        """
        radio_cfg = {
            "radio_config_path": _resolve_config_path(config["radio"]["config_file"]),
            "channel": config["radio"]["channel"],
        }
        radio = Radio.from_config(radio_cfg)
        rs485 = RS485Bus.from_config(config["rs485_bus"])

        fc_cfg = config.get("flight_computer", {})

        valves = [
            PassthroughValve.from_config(v)
            for v in fc_cfg.get("passthrough_valves", [])
        ]
        sensors = [
            PassthroughPressureSensor.from_config(s)
            for s in fc_cfg.get("passthrough_pressure_sensors", [])
        ]
        qdc_actuators = [
            QDCActuator.from_config(q)
            for q in config.get("qdc_actuator", [])
        ]

        return cls(radio, rs485, valves, sensors, qdc_actuators)

    def __del__(self) -> None:
        self.shutdown()

    # ------------------------------------------------------------------
    # Communication link
    # ------------------------------------------------------------------

    @property
    def comm_link_type(self) -> str:
        """The active communication link ("rs485" or "radio")."""
        return self._active_link

    @comm_link_type.setter
    def comm_link_type(self, new_link: str) -> None:
        """Switch the active transmit link ("rs485" or "radio")."""
        if new_link not in ("rs485", "radio"):
            raise ValueError(f"Invalid comm link type: {new_link!r}. Must be 'rs485' or 'radio'.")
        self._active_link = new_link

    # ------------------------------------------------------------------
    # Packet I/O
    # ------------------------------------------------------------------

    def receive_packets(self) -> List[bytearray]:
        """
        Returns all packets received since the last call, from both radio and RS485.
        Cannot be invoked after shutdown.

        RS485 frames are expected to be length-prefixed (2 bytes big-endian).
        Radio delivers discrete packets directly.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot receive packets: Controller is shutdown")

        packets: List[bytearray] = []

        # Drain radio — delivers complete packets
        packets.extend(self._radio.receive())

        # Drain RS485 — raw byte stream; parse 2-byte length-prefixed frames
        raw = self._rs485.read()
        if raw:
            self._rs485_rx_buffer.extend(raw)
        while len(self._rs485_rx_buffer) >= 2:
            length = struct.unpack_from(">H", self._rs485_rx_buffer)[0]
            if len(self._rs485_rx_buffer) < 2 + length:
                break  # incomplete frame — wait for more bytes
            packet = bytearray(self._rs485_rx_buffer[2:2 + length])
            self._rs485_rx_buffer = self._rs485_rx_buffer[2 + length:]
            packets.append(packet)

        return packets

    def transmit_packets(self, packets: List[bytearray]) -> None:
        """
        Transmits packets on the active communication link.
        RS485 packets are length-prefixed (2 bytes big-endian) before sending.
        Cannot be invoked after shutdown.

        Args:
            packets: List of bytearrays to transmit.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot transmit packets: Controller is shutdown")

        if self._active_link == "radio":
            self._radio.transmit(packets)
        else:  # rs485
            for packet in packets:
                framed = struct.pack(">H", len(packet)) + packet
                self._rs485.write(bytearray(framed))

    # ------------------------------------------------------------------
    # Hardware — passthrough valves
    # ------------------------------------------------------------------

    @property
    def passthrough_valve_info(self) -> List[Dict]:
        """Static info for all passthrough valves: id, name, default_state."""
        return [
            {"id": v.input, "name": v.name, "default_state": v.default_state}
            for v in self._passthrough_valves
        ]

    @property
    def passthrough_valve_states(self) -> Dict[int, Dict]:
        """Live state of all passthrough valves keyed by input id. Cannot be called after shutdown."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot read valve states after shutdown")
        return {
            v.input: {"state": v.state, "override": v.override}
            for v in self._passthrough_valves
        }

    def set_passthrough_valve_state(self, valve_id: int, override: bool) -> None:
        """Sets override state of a passthrough valve by id. Cannot be called after shutdown."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot set valve state after shutdown")
        for v in self._passthrough_valves:
            if v.input == valve_id:
                v.override = override
                return
        raise ValueError(f"No passthrough valve with id: {valve_id}")

    # ------------------------------------------------------------------
    # Hardware — passthrough pressure sensors
    # ------------------------------------------------------------------

    @property
    def passthrough_pressure_sensor_info(self) -> List[Dict]:
        """Static info for all passthrough pressure sensors: id, name, pressure_range."""
        return [
            {
                "id": s.input,
                "name": s.name,
                "pressure_range": {"min": s.min_pressure, "max": s.max_pressure},
            }
            for s in self._passthrough_pressure_sensors
        ]

    @property
    def passthrough_pressure_sensor_data(self) -> Dict[int, float]:
        """Latest pressure reading (PSI) for each sensor keyed by input id. Cannot be called after shutdown."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot read pressure sensor data after shutdown")
        return {s.input: s.pressure for s in self._passthrough_pressure_sensors}

    # ------------------------------------------------------------------
    # Hardware — QDC actuators
    # ------------------------------------------------------------------

    @property
    def qdc_actuator_info(self) -> List[Dict]:
        """Static info for all QDC actuators: id, wire_1_locked_state, wire_2_locked_state."""
        return [
            {
                "id": q.actuator_id,
                "wire_1_locked_state": q.wire_1_locked_state,
                "wire_2_locked_state": q.wire_2_locked_state,
            }
            for q in self._qdc_actuators
        ]

    @property
    def qdc_actuator_states(self) -> Dict[int, str]:
        """Live state of all QDC actuators keyed by actuator_id. Cannot be called after shutdown."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot read QDC states after shutdown")
        return {q.actuator_id: q.state for q in self._qdc_actuators}

    def set_qdc_actuator_state(self, actuator_id: int, state: str) -> None:
        """Sets state of a QDC actuator by id ("locked" or "released"). Cannot be called after shutdown."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot set QDC state after shutdown")
        for q in self._qdc_actuators:
            if q.actuator_id == actuator_id:
                q.state = state
                return
        raise ValueError(f"No QDC actuator with id: {actuator_id}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """
        Shuts down the controller, stopping all internal threads and hardware.
        Safe to call multiple times.
        """
        global _controller_init
        if self._shutdown_flag:
            return
        self._shutdown_flag = True
        _controller_init = False

        # hasattr guards: fields may not exist if __init__ raised before assigning them
        for v in getattr(self, '_passthrough_valves', []):
            if not v.is_shutdown:
                v.shutdown()
        for s in getattr(self, '_passthrough_pressure_sensors', []):
            if not s.is_shutdown:
                s.shutdown()
        for q in getattr(self, '_qdc_actuators', []):
            if not q.is_shutdown:
                q.shutdown()
        if hasattr(self, '_radio') and not self._radio.is_shutdown:
            self._radio.shutdown()
        if hasattr(self, '_rs485') and not self._rs485.is_shutdown:
            self._rs485.shutdown()
