from typing import List, Dict

class Controller:
    
    def __init__(self):
        """
        Initialize a Controller object with the given parameters.
        """
        ...
        
    @classmethod
    def from_config(cls, config: Dict) -> "Controller":
        """
        Initializes a Controller object from a configuration dictionary.
        
        Args:
            config: The target configuration dict.
        """
        ...
        
    def __del__(self):
        """
        Destructor for the Controller class, shuts down the controller.
        """
        ...
        
    @property
    def passthrough_valve_info(self) -> List[Dict]:
        """
        List of dicts containing information about all passthrough valves.
        
        Format:
            [
                {
                    id: <passthrough valve id (int)>,
                    name: <passthrough valve name (str)>
                }
            ]
        """
        ...
        
    @property
    def qdc_actuator_info(self) -> List[Dict]:
        """
        List of dicts containing information about all QDC actuators.
        
        Format:
            [
                {
                    id: <qdc actuator id (int)>,
                    name: <qdc actuator name (str)>
                }
            ]
        """
        ...
        
    @property
    def passthrough_pressure_sensor_info(self) -> List[Dict]:
        """
        List of dicts containing information about all passthrough pressure sensors.
        
        Format:
            [
                {
                    id: <passthrough pressure sensor id (int)>,
                    name: <passthrough pressure sensor name (str)>,
                    pressure_range: {
                        min: <min output pressure in psi (float)>,
                        max: <max output pressure in psi (float)>
                    }
                }
            ]
        """
        ...
        
    @property
    def passthrough_valve_states(self) -> Dict[int, Dict]:
        """
        Dict containing the states of all passthrough valves. 
        Cannot be invoked after shutdown.
        
        Format:
            {
                <valve_id>: {
                    state: <state of valve as known from controller ("open", "closed", or "unknown")>,
                    override: <true if the valve is currently being overriden, false otherwise>
                }
                ... (repeated for each valve)   
            }
        """
        ...
    
    @property
    def qdc_actuator_states(self) -> Dict[int, str]:
        """
        Dict containing the states of all QDC actuators.
        Cannot be invoked after shutdown.
        
        Format:
            {
                <qdc actuator id>: <state of actuator as known from controller ("locked" or "released")>
                ... (repeated for each actuator)
            }
        """
        ...
        
    @property
    def passthrough_pressure_sensor_data(self) -> Dict[int, float]:
        """
        Dict containing the pressure readings of all passthrough pressure sensors.
        Cannot be invoked after shutdown.
        
        Format:
            {
                <sensor_id>: <current pressure reading in psi (float)>
                ... (repeated for each sensor)
            }
        """
        ...
    
    def set_passthrough_valve_state(self, valve_id: int, override: bool) -> None:
        """
        Sets the override state of the specified passthrough valve.
        Cannot be invoked after shutdown.
        
        Parameters:
            valve_id (int): The ID of the passthrough valve to modify.
            override (bool): True to override the valve (power it), false to release override.
        """
        ...
        
    def set_qdc_actuator_state(self, actuator_id: int, state: str) -> None:
        """
        Sets the state of the specified QDC actuator.
        Cannot be invoked after shutdown.
        
        Parameters:
            actuator_id (int): The ID of the QDC actuator to modify.
            state (str): The desired state ("locked" or "released").
        """
        ...
        
    @property
    def comm_link_type(self) -> str:
        """
        The current communication link used by the controller ("rs485" or "radio").
        """
        ...
        
    @comm_link_type.setter
    def comm_link_type(self, new_link: str) -> None:
        """
        Sets the communication link used by the controller.
        
        Args:
            new_link: The desired communication link ("rs485" or "radio").
        """
        ...
        
    def transmit_packets(self, packets: List[bytearray]) -> None:
        """
        Transmits packets to the flight computer.
        
        Args:
            packets: A list of bytearrays containing the packets to transmit.
        """
        ...
        
    def receive_packets(self) -> List[bytearray]:
        """
        Gets list of packets (bytearrays) received from the flight computer since the last invocation.
        """
        ...
        
    def shutdown(self):
        """
        Shuts down the controller, stopping any internal threads.
        """
        ...
        
    