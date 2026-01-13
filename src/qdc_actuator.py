from enum import Enum
from typing import Dict
from . import settings

if not settings.MOCK_MODE:
    import board
    from digitalio import DigitalInOut, Direction
    
    # QDC actuator GPIO pins (relays)
    QDC_ACTUATOR_WIRE_1_PIN = board.D9
    QDC_ACTUATOR_WIRE_2_PIN = board.D10
    
class QDCActuatorState(Enum):
    """
    Denotes the state of a QDC actuator.
    """
    LOCKED = "locked"
    RELEASED = "released"
    
class QDCActuator:
    """
    Class which represents a QDC actuator connected to the controller.
    """
    
    def __init__(self, wire_1_locked_state: str, wire_2_locked_state: str) -> None:
        """
        Initializes a QDCActuator object with the given parameters.
        
        Args:
            wire_1_locked_state: Voltage of actuator wire 1 when locked ("high" or "low").
            wire_2_locked_state: Voltage of actuator wire 2 when locked ("high" or "low").
        """
        if wire_1_locked_state not in ["high", "low"]:
            raise ValueError(f"QDC actuator has invalid wire 1 locked state: {wire_1_locked_state}")
        if wire_2_locked_state not in ["high", "low"]:
            raise ValueError(f"QDC actuator has invalid wire 2 locked state: {wire_2_locked_state}")
        
        self._wire_1_locked_state = wire_1_locked_state
        self._wire_2_locked_state = wire_2_locked_state
        self._state = QDCActuatorState.LOCKED
        self._shutdown_flag = False
        
        if not settings.MOCK_MODE:
            self._wire_1_io = DigitalInOut(QDC_ACTUATOR_WIRE_1_PIN)
            self._wire_1_io.direction = Direction.OUTPUT
            self._wire_1_io.value = (wire_1_locked_state == "high")
            
            self._wire_2_io = DigitalInOut(QDC_ACTUATOR_WIRE_2_PIN)
            self._wire_2_io.direction = Direction.OUTPUT
            self._wire_2_io.value = (wire_2_locked_state == "high")
            
    @classmethod
    def from_config(cls, config: dict) -> "QDCActuator":
        """
        Initializes a QDCActuator object from a configuration dictionary.
        
        Args:
            config: The target configuration dict.
        """
        if 'wire_1_locked_state' not in config:
            raise KeyError(f"QDC actuator config missing key: 'wire_1_locked_state'")
        if 'wire_2_locked_state' not in config:
            raise KeyError(f"QDC actuator config missing key: 'wire_2_locked_state'")
        
        return cls(
            wire_1_locked_state = config['wire_1_locked_state'],
            wire_2_locked_state = config['wire_2_locked_state']
        )
        
    def __del__(self) -> None:
        self.shutdown()
        
    def __str__(self) -> str:
        """
        Gets string representation of QDCActuator.
        """
        return f"QDCActuator(wire_1_locked_state = {self._wire_1_locked_state}, wire_2_locked_state = {self._wire_2_locked_state})"
    
    @property
    def wire_1_locked_state(self) -> str:
        """
        Voltage of actuator wire 1 when locked ("high" or "low").
        """
        return self._wire_1_locked_state
    
    @property
    def wire_2_locked_state(self) -> str:
        """
        Voltage of actuator wire 2 when locked ("high" or "low").
        """
        return self._wire_2_locked_state
    
    @property
    def state(self) -> QDCActuatorState:
        """
        Current state of the QDC actuator. Cannot be called after shutdown().
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot get state of QDC actuator after shutdown")
        return self._state
    
    @state.setter
    def state(self, new_state: QDCActuatorState) -> None:
        """
        Sets the state of the QDC actuator (locked or released). Cannot be called after shutdown().
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot change state of QDC actuator after shutdown")
        if self._state != new_state:
            if not settings.MOCK_MODE:
                self._state = new_state
                if new_state == QDCActuatorState.LOCKED:
                    self._wire_1_io.value = (self._wire_1_locked_state == "high")
                    self._wire_2_io.value = (self._wire_2_locked_state == "high")
                else:
                    self._wire_1_io.value = (self._wire_1_locked_state != "high")
                    self._wire_2_io.value = (self._wire_2_locked_state != "high")
                    
    def shutdown(self) -> None:
        """
        Shuts down the QDC actuator, sets it to locked state.
        """
        if not self._shutdown_flag:
            self._shutdown_flag = True
            if not settings.MOCK_MODE:
                self._wire_1_io.deinit()
                self._wire_2_io.deinit()
        
    
        