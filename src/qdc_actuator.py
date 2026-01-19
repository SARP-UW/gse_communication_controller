from enum import Enum
from typing import Dict
from . import settings

if not settings.MOCK_MODE:
    import board
    from digitalio import DigitalInOut, Direction
    
    # QDC actuator GPIO pins (relays)
    QDC_ACT_WIRE_1_PIN = board.D9
    QDC_ACT_WIRE_2_PIN = board.D10
    
# Tracks initialization of QDC actuator
qdc_act_init: bool = False
    
class QDCActuator:
    """
    Class which represents a QDC actuator connected to the controller.
    """
    
    def __init__(self, wire_1_locked_state: str, wire_2_locked_state: str) -> None:
        """
        Initializes a QDCActuator object with the given parameters. Starts in locked state.
        
        Args:
            wire_1_locked_state: Voltage of actuator wire 1 when locked ("high" or "low").
            wire_2_locked_state: Voltage of actuator wire 2 when locked ("high" or "low").
        """
        if wire_1_locked_state not in ["high", "low"]:
            raise ValueError(f"QDC actuator has invalid wire 1 locked state: {wire_1_locked_state}")
        if wire_2_locked_state not in ["high", "low"]:
            raise ValueError(f"QDC actuator has invalid wire 2 locked state: {wire_2_locked_state}")
        
        # Ensure only one QDC actuator is initialized
        if qdc_act_init:
            raise RuntimeError("QDC actuator has already been initialized")
        qdc_act_init = True
        
        self._wire_1_locked_state: str = wire_1_locked_state
        self._wire_2_locked_state: str = wire_2_locked_state
        self._state: str = "locked"
        self._shutdown_flag: bool = False
        
        if not settings.MOCK_MODE:
            self._wire_1_io: DigitalInOut = DigitalInOut(QDC_ACT_WIRE_1_PIN)
            self._wire_1_io.direction = Direction.OUTPUT
            self._wire_1_io.value = (wire_1_locked_state == "high")
            
            self._wire_2_io: DigitalInOut = DigitalInOut(QDC_ACT_WIRE_2_PIN)
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
                
        wire_1_locked_state = config['wire_1_locked_state']
        if not isinstance(wire_1_locked_state, str):
            raise ValueError(f"QDC actuator config 'wire_1_locked_state' must be a string, got: {type(wire_1_locked_state).__name__}")
        
        wire_2_locked_state = config['wire_2_locked_state']
        if not isinstance(wire_2_locked_state, str):
            raise ValueError(f"QDC actuator config 'wire_2_locked_state' must be a string, got: {type(wire_2_locked_state).__name__}")
        
        return cls(
            wire_1_locked_state = wire_1_locked_state,
            wire_2_locked_state = wire_2_locked_state
        )
        
    def __del__(self) -> None:
        """
        Destructor for QDCActuator - shuts down the actuator.
        """
        self.shutdown()

    def __str__(self) -> str:
        """
        Gets string representation of QDCActuator (ommits current state info).
        """
        return f"QDCActuator(wire_1_locked_state = {self._wire_1_locked_state}, wire_2_locked_state = {self._wire_2_locked_state})"
    
    @property
    def is_shutdown(self) -> bool:
        """
        Whether the QDC actuator has been shutdown.
        """
        return self._shutdown_flag
    
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
    def state(self) -> str:
        """
        Current state of the QDC actuator ("locked" or "released"). Cannot be called after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot get state of QDC actuator after shutdown")
        return self._state
    
    @state.setter
    def state(self, new_state: str) -> None:
        """
        Sets the state of the QDC actuator ("locked" or "released"). Cannot be called after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot change state of QDC actuator after shutdown")
        if new_state not in ["locked", "released"]:
            raise ValueError(f"QDC actuator cannot be set to invalid state: {new_state} (must be 'locked' or 'released')")
        
        if self._state != new_state and not settings.MOCK_MODE:
                self._state = new_state
                if new_state == "locked":
                    self._wire_1_io.value = (self._wire_1_locked_state == "high")
                    self._wire_2_io.value = (self._wire_2_locked_state == "high")
                else:
                    self._wire_1_io.value = (self._wire_1_locked_state != "high")
                    self._wire_2_io.value = (self._wire_2_locked_state != "high")
                    
    def shutdown(self) -> None:
        """
        Shuts down the QDC actuator, sets it to locked state.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot shutdown QDC actuator more than once")
        qdc_act_init = False
        self._shutdown_flag = True
        if not settings.MOCK_MODE:
            self._wire_1_io.deinit()
            self._wire_2_io.deinit()
        
    
        