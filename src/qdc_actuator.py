from typing import Dict, List
from . import settings

if not settings.MOCK_MODE:
    import board
    from digitalio import DigitalInOut, Direction

# Tracks which actuator_ids are currently initialized (max 2)
qdc_act_init_list: List[int] = []

class QDCActuator:
    """
    Class which represents a QDC actuator connected to the controller.
    """

    def __init__(self, actuator_id: int, wire_1_pin: int, wire_2_pin: int,
                 wire_1_locked_state: str, wire_2_locked_state: str) -> None:
        """
        Initializes a QDCActuator. Starts in locked state.

        Args:
            actuator_id: ID of this actuator (1 or 2).
            wire_1_pin: BCM GPIO pin number for wire 1.
            wire_2_pin: BCM GPIO pin number for wire 2.
            wire_1_locked_state: Voltage of wire 1 when locked ("high" or "low").
            wire_2_locked_state: Voltage of wire 2 when locked ("high" or "low").
        """
        if actuator_id not in (1, 2):
            raise ValueError(f"QDC actuator has invalid id: {actuator_id} (must be 1 or 2)")
        if wire_1_locked_state not in ("high", "low"):
            raise ValueError(f"QDC actuator has invalid wire 1 locked state: {wire_1_locked_state}")
        if wire_2_locked_state not in ("high", "low"):
            raise ValueError(f"QDC actuator has invalid wire 2 locked state: {wire_2_locked_state}")

        # Allow up to 2 instances, one per actuator_id
        if actuator_id in qdc_act_init_list:
            raise RuntimeError(f"QDC actuator {actuator_id} has already been initialized")
        qdc_act_init_list.append(actuator_id)

        self._actuator_id: int = actuator_id
        self._wire_1_locked_state: str = wire_1_locked_state
        self._wire_2_locked_state: str = wire_2_locked_state
        self._state: str = "locked"
        self._shutdown_flag: bool = False

        if not settings.MOCK_MODE:
            # Pin numbers are configurable — resolve via board module at runtime
            self._wire_1_io: DigitalInOut = DigitalInOut(getattr(board, f"D{wire_1_pin}"))
            self._wire_1_io.direction = Direction.OUTPUT
            self._wire_1_io.value = (wire_1_locked_state == "high")

            self._wire_2_io: DigitalInOut = DigitalInOut(getattr(board, f"D{wire_2_pin}"))
            self._wire_2_io.direction = Direction.OUTPUT
            self._wire_2_io.value = (wire_2_locked_state == "high")

    @classmethod
    def from_config(cls, config: dict) -> "QDCActuator":
        """
        Initializes a QDCActuator from a configuration dictionary.

        Args:
            config: Dict with keys: actuator_id, wire_1_pin, wire_2_pin,
                    wire_1_locked_state, wire_2_locked_state.
        """
        for key in ("actuator_id", "wire_1_pin", "wire_2_pin",
                    "wire_1_locked_state", "wire_2_locked_state"):
            if key not in config:
                raise KeyError(f"QDC actuator config missing key: '{key}'")

        wire_1_locked_state = config["wire_1_locked_state"]
        if not isinstance(wire_1_locked_state, str):
            raise ValueError(f"QDC actuator config 'wire_1_locked_state' must be a string")

        wire_2_locked_state = config["wire_2_locked_state"]
        if not isinstance(wire_2_locked_state, str):
            raise ValueError(f"QDC actuator config 'wire_2_locked_state' must be a string")

        try:
            actuator_id = int(config["actuator_id"])
        except (ValueError, TypeError):
            raise ValueError(f"QDC actuator config 'actuator_id' must be an integer")
        try:
            wire_1_pin = int(config["wire_1_pin"])
        except (ValueError, TypeError):
            raise ValueError(f"QDC actuator config 'wire_1_pin' must be an integer")
        try:
            wire_2_pin = int(config["wire_2_pin"])
        except (ValueError, TypeError):
            raise ValueError(f"QDC actuator config 'wire_2_pin' must be an integer")

        return cls(
            actuator_id=actuator_id,
            wire_1_pin=wire_1_pin,
            wire_2_pin=wire_2_pin,
            wire_1_locked_state=wire_1_locked_state,
            wire_2_locked_state=wire_2_locked_state,
        )

    def __del__(self) -> None:
        self.shutdown()

    def __str__(self) -> str:
        return (f"QDCActuator(actuator_id={self._actuator_id}, "
                f"wire_1_locked_state={self._wire_1_locked_state}, "
                f"wire_2_locked_state={self._wire_2_locked_state})")

    @property
    def actuator_id(self) -> int:
        """ID of this actuator (1 or 2)."""
        return self._actuator_id

    @property
    def is_shutdown(self) -> bool:
        """True if this actuator has been shutdown."""
        return self._shutdown_flag

    @property
    def wire_1_locked_state(self) -> str:
        """Voltage of wire 1 when locked ("high" or "low")."""
        return self._wire_1_locked_state

    @property
    def wire_2_locked_state(self) -> str:
        """Voltage of wire 2 when locked ("high" or "low")."""
        return self._wire_2_locked_state

    @property
    def state(self) -> str:
        """Current state ("locked" or "released"). Cannot be called after shutdown."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot get state of QDC actuator after shutdown")
        return self._state

    @state.setter
    def state(self, new_state: str) -> None:
        """Sets actuator state ("locked" or "released"). Cannot be called after shutdown."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot change state of QDC actuator after shutdown")
        if new_state not in ("locked", "released"):
            raise ValueError(f"QDC actuator cannot be set to invalid state: {new_state}")

        if self._state != new_state:
            self._state = new_state
            if not settings.MOCK_MODE:
                if new_state == "locked":
                    self._wire_1_io.value = (self._wire_1_locked_state == "high")
                    self._wire_2_io.value = (self._wire_2_locked_state == "high")
                else:
                    self._wire_1_io.value = (self._wire_1_locked_state != "high")
                    self._wire_2_io.value = (self._wire_2_locked_state != "high")

    def shutdown(self) -> None:
        """Shuts down this actuator and frees its slot. Safe to call only once."""
        if self._shutdown_flag:
            raise RuntimeError("Cannot shutdown QDC actuator more than once")
        self._shutdown_flag = True
        # Free the slot so another instance with this id can be created later
        if self._actuator_id in qdc_act_init_list:
            qdc_act_init_list.remove(self._actuator_id)
        if not settings.MOCK_MODE:
            self._wire_1_io.deinit()
            self._wire_2_io.deinit()
