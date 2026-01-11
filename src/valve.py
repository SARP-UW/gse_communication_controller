from enum import Enum
from typing import Dict
from . import settings

# Hardware dependent libraries and initialization
if not settings.MOCK_MODE: 
    import board
    from digitalio import DigitalInOut, Direction

    # Mapping of valve IDs to their corresponding GPIO pins <TODO: Update pins>
    VALVE_PIN_MAP: Dict[int, int] = {
        1: board.D13,
        2: board.D6,
        3: board.D5,
        4: board.D11,
    }
    
# Number of supported valves
VALVE_COUNT = 4

class ValveState(Enum):
    """
    Denotes the state of a valve.
    """
    CLOSED = "closed"
    OPEN = "open"

class Valve:
    """
    Class which represents a valve connected to the controller.
    """

    def __init__(self, id: int, name: str, default_state: ValveState) -> None:
        """
        Initializes a Valve object with the given parameters.
        
        Args:
            id: The unique ID of this valve.
            name: The name of this valve.
            default_state: The default state of this valve (when not powered).
        """
        if id > VALVE_COUNT:
            raise ValueError(f"Valve has invalid ID: {id} > {VALVE_COUNT}")
        if id < 1:
            raise ValueError(f"Valve has invalid ID: {id} < 1")
        
        self._id = id
        self.name = name
        self._default_state = default_state
        self._state = default_state
           
        if not settings.MOCK_MODE:
            self._io = DigitalInOut(VALVE_PIN_MAP[id])
            self._io.direction = Direction.OUTPUT
            self._io.value = False

    @classmethod
    def from_config(cls, config: Dict) -> "Valve":
        """
        Initializes a Valve object from a configuration dictionary.
        
        Args:
            config: The target configuration dict.
        """
        if 'id' not in config:
            raise KeyError(f"Valve config missing key: 'id'")
        if 'name' not in config:
            raise KeyError(f"Valve config missing key: 'name'")
        if 'default_state' not in config:
            raise KeyError(f"Valve config missing key: 'default_state'")
        
        try:
            id = int(config['id'])
        except (ValueError, TypeError):
            raise ValueError(f"Valve config 'id' must be an integer, got: {type(config['id']).__name__}")
        
        name = config['name']
        if not isinstance(name, str):
            raise ValueError(f"Valve config 'name' must be a string, got: {type(name).__name__}")
        
        default_state_str = config['default_state']
        if not isinstance(default_state_str, str):
            raise ValueError(f"Valve config 'default_state' must be a string, got: {type(default_state_str).__name__}")
        
        try:
            default_state = ValveState[default_state_str.strip().upper()]
        except (KeyError, AttributeError):
            raise ValueError(f"Valve config has invalid default_state (not \"open\" or \"closed\"): {default_state_str}")
        
        return cls(
            id = id,
            name = name,
            default_state = default_state
        )

    def __str__(self) -> str:
        """
        Gets string representation of Valve.
        """
        return f"Valve(id = {self._id}, name = {self.name}, default_state = {self._default_state}, state = {self._state})"

    @property
    def id(self) -> int:
        """
        Unique ID of this valve.
        """
        return self._id
        
    @property
    def default_state(self) -> ValveState:
        """
        Default state of this valve (when not powered).
        """
        return self._default_state
                
    @property
    def state(self) -> ValveState:
        """
        Current state of this valve.
        """
        return self._state
        
    @state.setter
    def state(self, new_state: ValveState) -> None:
        """
        Updates the current state of this valve.
        """
        if self._state != new_state:
            self._state = new_state
            if not settings.MOCK_MODE:
                if self._default_state == ValveState.CLOSED:
                    self._io.value = (new_state == ValveState.OPEN)
                else:
                    self._io.value = (new_state == ValveState.CLOSED)
            