import os
import struct
from typing import List, Dict

from src.radio import Radio
from src.rs485_bus import RS485Bus

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

    def __init__(self, radio: Radio, rs485: RS485Bus) -> None:
        """
        Initialises a Controller with the given communication interfaces.

        Args:
            radio: Initialised Radio instance.
            rs485: Initialised RS485Bus instance.
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

        # Hardware (valves, pressure sensors, QDC) — not wired yet; stubs return empty
        self._passthrough_valves: list = []
        self._passthrough_pressure_sensors: list = []
        self._qdc_actuator = None

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
        return cls(radio, rs485)

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
    # Hardware state (stubs — not needed for comm loop)
    # ------------------------------------------------------------------

    @property
    def passthrough_valve_info(self) -> List[Dict]:
        return []

    @property
    def qdc_actuator_info(self) -> List[Dict]:
        return []

    @property
    def passthrough_pressure_sensor_info(self) -> List[Dict]:
        return []

    @property
    def passthrough_valve_states(self) -> Dict[int, Dict]:
        if self._shutdown_flag:
            raise RuntimeError("Cannot read valve states after shutdown")
        return {}

    @property
    def qdc_actuator_states(self) -> Dict[int, str]:
        if self._shutdown_flag:
            raise RuntimeError("Cannot read QDC states after shutdown")
        return {}

    @property
    def passthrough_pressure_sensor_data(self) -> Dict[int, float]:
        if self._shutdown_flag:
            raise RuntimeError("Cannot read pressure sensor data after shutdown")
        return {}

    def set_passthrough_valve_state(self, valve_id: int, override: bool) -> None:
        if self._shutdown_flag:
            raise RuntimeError("Cannot set valve state after shutdown")

    def set_qdc_actuator_state(self, actuator_id: int, state: str) -> None:
        if self._shutdown_flag:
            raise RuntimeError("Cannot set QDC state after shutdown")

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

        # hasattr guards: _radio/_rs485 may not exist if __init__ raised after assigning them
        if hasattr(self, '_radio') and not self._radio.is_shutdown:
            self._radio.shutdown()
        if hasattr(self, '_rs485') and not self._rs485.is_shutdown:
            self._rs485.shutdown()
