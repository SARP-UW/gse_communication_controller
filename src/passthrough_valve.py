from enum import Enum
from typing import Dict, List
from . import settings

# Hardware dependent libraries and initialization
if not settings.MOCK_MODE: 
    import board
    from digitalio import DigitalInOut, Direction

    # <TODO: Update pins>
    # Mapping of passthrough valve input number to their corresponding GPIO pins
    PST_VALVE_PIN_MAP = {
        1: board.D13,
        2: board.D6,
        3: board.D5,
        4: board.D11,
    }
    
# Number of supported passthrough valves
PST_VALVE_COUNT = 4

# List of inputs of initialized passthrough valves
pst_valve_init_list: List[int] = []

class PassthroughValve:
    """
    Class which represents a passthrough valve connected to the controller.
    """

    def __init__(self, input: int, name: str, default_state: str) -> None:
        """
        Initializes a PassthroughValve object with the given parameters.
        
        Args:
            input: The input number of this passthrough valve.
            name: The name of this passthrough valve.
            default_state: The default state of this passthrough valve (when not powered) ("open" or "closed").
        """
        if input > PST_VALVE_COUNT:
            raise ValueError(f"Passthrough valve has invalid input number: {input} > {PST_VALVE_COUNT}")
        if input < 1:
            raise ValueError(f"Passthrough valve has invalid input number: {input} < 1")
        if default_state not in ["open", "closed"]:
            raise ValueError(f"Passthrough valve has invalid default state (not \"open\" or \"closed\"): {default_state}")
        
        # Keep track of initialized valve inputs to prevent duplicates
        if input in pst_valve_init_list:
            raise RuntimeError(f"Passthrough valve with input {input} has already been initialized")
        pst_valve_init_list.append(input)
        
        self._input: int = input
        self.name: str = name
        self._default_state: str = default_state
        self._override_state: bool = False
        self._shutdown_flag: bool = False
        # Initialize GPIO pin used to control valve
        if not settings.MOCK_MODE:
            self._io: DigitalInOut = DigitalInOut(PST_VALVE_PIN_MAP[input])
            self._io.direction = Direction.OUTPUT
            self._io.value = False

    @classmethod
    def from_config(cls, config: Dict) -> "PassthroughValve":
        """
        Initializes a PassthroughValve object from a configuration dictionary.
        
        Args:
            config: The target configuration dict.
        """
        if 'input' not in config:
            raise KeyError(f"Passthrough valve config missing key: 'input'")
        if 'name' not in config:
            raise KeyError(f"Passthrough valve config missing key: 'name'")
        if 'default_state' not in config:
            raise KeyError(f"Passthrough valve config missing key: 'default_state'")
                
        name = config['name']
        if not isinstance(name, str):
            raise ValueError(f"Passthrough valve config 'name' must be a string, got: {type(name).__name__}")
        
        default_state = config['default_state']
        if not isinstance(default_state, str):
            raise ValueError(f"Passthrough valve config 'default_state' must be a string, got: {type(default_state).__name__}")
        
        try:
            input = int(config['input'])
        except (ValueError, TypeError):
            raise ValueError(f"Passthrough valve config 'input' must be an integer, got: {type(config['input']).__name__}")
        
        return cls(
            input = input,
            name = name,
            default_state = default_state
        )

    def __del__(self) -> None:
        """
        Destructor for PassthroughValve - shuts down the valve.
        """
        self.shutdown()

    def __str__(self) -> str:
        """
        Gets string representation of this passthrough valve (ommits current state info).
        """
        return f"PassthroughValve(input = {self._input}, name = {self.name}, default_state = {self._default_state})"

    @property
    def is_shutdown(self) -> bool:
        """
        True if this passthrough valve has been shutdown.
        """
        return self._shutdown_flag
    
    @property
    def input(self) -> int:
        """
        Input number of this passthrough valve.
        """
        return self._input
        
    @property
    def default_state(self) -> str:
        """
        Default state of this passthrough valve (when not powered).
        """
        return self._default_state

    @property
    def state(self) -> str:
        """
        Current state of this passthrough valve ("open", "closed", or "unknown"). Cannot be called after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot get state of passthrough valve after shutdown")
        if self._override_state:
            return "open" if self._default_state == "closed" else "closed"
        else:
            return "unknown"
        
    @property
    def override(self) -> bool:
        """
        True if this passthrough valve's state is currently being overriden (powered by controller). Cannot be called after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot get passthrough valve override state after shutdown")
        return self._override_state
    
    @override.setter
    def override(self, new_value: bool) -> None:
        """
        Sets the "override" state of this passthrough valve (if true valve is overriden to powered state). Cannot be called after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot modify passthrough valve override state after shutdown")
        if new_value != self._override_state:
            self._override_state = new_value
            if not settings.MOCK_MODE:
                self._io.value = new_value

    def shutdown(self) -> None:
        """
        Shuts down this passthrough valve.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot shutdown passthrough valve more than once")            
        self._shutdown_flag = True
        pst_valve_init_list.remove(self._input)
        if not settings.MOCK_MODE:
            self._io.value = False
            self._io.deinit()
            