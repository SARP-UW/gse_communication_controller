from src.radio import Radio
from src.rs485_bus import RS485Bus
from src.qdc_actuator import QDCActuator
from src.passthrough_valve import PassthroughValve
from src.passthrough_pressure_sensor import PassthroughPressureSensor
from src.logger import Logger
from typing import Dict, List

# Data from flight comptuer:
    # Flight computer sensor data
    # Flight computer status
    # Flight computer valve/servo states

# Data from CC:
    # CC passthrough sensor data
    # CC passthrough valve states
    # CC status data

# Loggers:
    # Status Logger
    # Flight computer sensor logger
    # Flight computer valve/servo state logger

# Flight Computer Sensors
    # 2x IMU - [accel x (2 bytes), accel y (2 bytes), accel z (2 bytes), gyro x (2 bytes), gyro y (2 bytes), gyro z (2 bytes)] - 12 bytes each
    # 2x Magnetometer - [mag x (2 bytes), mag y (2 bytes), mag z (2 bytes)] - 6 bytes each
    # 2x barometer - 3 bytes each (reads pressure)
    # 2x Temperature sensor - temperature (2 bytes) (one is on power board, one is on sensor board)
    # GPS - [latitude (4 bytes), longitude (4 bytes), altitude (4 bytes), velocity x (2 bytes), velocity y (2 bytes), velocity z (2 bytes), time (4 bytes)] - 22 bytes
    # ADC - 3 bytes per data point (max of 24 pressure sensors, 24 RTDs, 3 strain guages)
    
    # 3x current sensors - 2 bytes each

# Flight computer valves/servos
    # 12 actuator outputs
    # 8 servo outputs
    
# Downlink Packets (from FC to CC):

    # Sensor data packet:
        # 0x01
        # <IMU 1 accel x (2 bytes)>
        # <IMU 1 accel y (2 bytes)>
        # <IMU 1 accel z (2 bytes)>
        # <IMU 1 gyro x (2 bytes)>
        # <IMU 1 gyro y (2 bytes)>
        # <IMU 1 gyro z (2 bytes)>
        # <IMU 2 accel x (2 bytes)>
        # <IMU 2 accel y (2 bytes)>
        # <IMU 2 accel z (2 bytes)>
        # <IMU 2 gyro x (2 bytes)>
        # <IMU 2 gyro y (2 bytes)>
        # <IMU 2 gyro z (2 bytes)>
        # <Magnetometer 1 mag x (2 bytes)>
        # <Magnetometer 1 mag y (2 bytes)>
        # <Magnetometer 1 mag z (2 bytes)>
        # <Magnetometer 2 mag x (2 bytes)>
        # <Magnetometer 2 mag y (2 bytes)>
        # <Magnetometer 2 mag z (2 bytes)>
        # <Barometer 1 pressure (3 bytes)>
        # <Barometer 2 pressure (3 bytes)>
        # <Temperature sensor 1 temperature (2 bytes)>
        # <Temperature sensor 2 temperature (2 bytes)>
        # <Current sensor 1 current (2 bytes)>
        # <Current sensor 2 current (2 bytes)>
        # <Current sensor 3 current (2 bytes)>

    # GPS data packet
        # 0x02
        # <Latitude (4 bytes)>
        # <Longitude (4 bytes)>
        # <Altitude (4 bytes)>
        # <Velocity x (2 bytes)>
        # <Velocity y (2 bytes)>
        # <Velocity z (2 bytes)>
        # <Time (4 bytes)>
            
    # ADC data packet
        # 0x03
        # <packet index (1 byte)>
        # <data point (3 bytes)> (repeat for each sensor in adc config for this packet index)
            
    # State packet
        # 0x04
        # <valve state (1 bit)> (repeat for each valve in status protocol, pad to byte boundary)
        # <servo state (2 bytes)> (repeat for each servo in status protocol)

    # comm packet:
        # 0x05
        # <ping id (2 bytes)>
        # <system mode (1 byte)>
        # <processor time (4 bytes)> (ms since startup)
        # <last command id (2 bytes)>
        # <last command status (1 byte)>
        # <message count (1 byte)>
        # <message 1 tag (1 byte)> (optional) (repeat for each desired message)
        
        # NOTE: After comm packet is sent over radio, FC is expected
        # The comm packet is expected every 100 ms, with 10 ms given for a response.         
        
        # Command status values
            # 0x00 Command waiting
            # 0x01 Command in progress
            # 0x02 Command completed successfully
            # 0x03 Command failed due to invalid tag
            # 0x04 Command failed due to invalid arguments
            # 0x05 Command failed due to out of range arguments
            # 0x06 Command failed due to hardware error
            # 0x07 Command failed due to timeout
            # 0x08 Command failed due to invalid system state
            # 0x09 Command aborted by flight computer
            # 0x0A Command awaiting confirmation

# Uplink Packets (from CC to FC):

    # comm packet:
        # 0x01
        # <ping id (2 bytes)>
        # <system time (4 bytes)> (unix timestamp)
        # <command valid (1 byte)> (0 = invalid, 1 = valid)
        # <command id (2 bytes)> (optional, only if command valid = 1)
        # <command type (1 byte)> (optional, only if command valid = 1)
        # <command tag (1 byte)> (optional, only if command valid = 1)
        # <command arguments (pre-determined variable length)> (optional, only if command valid = 1)

        # Command types
            # 0x00 Static command
            # 0x01 Custom command
            
        # Static command tags and args
            
            # Change valve state
                # 0x00
                # <valve id (1 byte)>
                # <new state (1 byte)> (0 = closed, 1 = open)
                
            # Pulse valve
                # 0x01
                # <valve id (1 byte)>
                # <pulse duration (2 bytes)> (in milliseconds)
                
            # Change servo state
                # 0x02
                # <servo id (1 byte)>
                # <new position (2 bytes)>
                
            # Pulse servo
                #0x03
                # <servo id (1 byte)>
                # <new position (2 bytes)>
                # <pulse duration (2 bytes)> (in milliseconds)
                
            # Set sys mode
                # 0x04
                # <new mode (1 byte)>
                
            # Set comm link
                # 0x05
                # <new link (1 byte)> (0 = RS485, 1 = radio)
                            
            # Sleep
                #0x04
                
            # Wake
                # 0x05
                 
            # Restart (2 commands to confirm)
                #0x06

class FlightComputer:
    
    def __init__(self) -> None:
        ...
        
    def __del__(self) -> None:
        """
        Destructor for FlightComputer, shuts down system.
        """
        self._shutdown()
        
    def __str__(self) -> str:
        """
        Gets string representation of FlightComputer.
        """
        ...
    
    @property
    def adc_sensor_info(self) -> List[Dict]:
        """
        List of dicts containing information about all ADC sensors on the flight computer.
        
        Format:
            [
                {
                    id: <adc sensor id (int)>,
                    name: <adc sensor name (str)>,
                    type: <sensor type (str)>
                }
            ]
        """
        ...
    
    @property
    def valve_info(self) -> List[Dict]:
        """
        List of dicts containing information about all valves on the flight computer.
        
        Format:
            [
                {
                    id: <valve id (int)>,
                    name: <valve name (str)>,
                }
            ]
        """
        ...
        
    @property
    def servo_info(self) -> List[Dict]:
        """
        List of dicts containing information about all servos on the flight computer.
        
        Format:
            [
                {
                    id: <servo id (int)>,
                    name: <servo name (str)>,
                    type: <servo type (str)>
                }
            ]
        """
        ...
    
    @property
    def mode_info(self) -> List[Dict]:
        """
        List of dicts containing information about all modes supported by the flight computer.
        
        Format:
            [
                {
                    id: <mode id (int)>,
                    name: <mode name (str)>,
                    description: <mode description (str)>
                }
            ]
        """
        ...
        
    @property
    def custom_command_info(self) -> List[Dict]:
        """
        List of dicts containing information about all custom commands supported by the flight computer.
        
        Format:
            [
                {
                    id: <custom command id (int)>,
                    name: <custom command name (str)>,
                    description: <custom command description (str)>,
                    args: [
                        {
                            name: <argument name (str)>,
                            type: <argument type (str)>,
                            description: <argument description (str)>
                        }
                        ... (repeated for each argument)
                    ]
                }
                ... (repeated for each custom command)
            ]
        """
        ...  
    
    @property
    def adc_sensor_data(self) -> Dict[int, float]:
        """
        Dict of latest ADC sensor data from the flight computer. 
        Cannot be invoked after shutdown.
        
        Format:
            {
                <adc sensor id (int)>: <latest sensor reading (float)>,
                ... (repeated for each adc sensor)
            }
        """
        ...
    
    @property
    def valve_states(self) -> Dict[int, int]:
        """
        Dict containing states of all valves on the flight computer. 
        Cannot be invoked after shutdown.
        
        Format:
            {
                <valve id>: <state of valve ("open" or "closed")>,
                ... (repeated for each valve)
            }
        """
        ...
    
    @property
    def servo_states(self) -> Dict[int, float]:
        """
        Dict containing states of all servos on the flight computer.
        Cannot be invoked after shutdown.
        
        Format:
            {
                <servo id>: <state of servo (speed, degrees, percent) (float)>,
                ... (repeated for each servo)
            }
        """
        ...
    
    @property
    def mode(self) -> int:
        """
        ID of the flight computer's current mode.
        Cannot be invoked after shutdown.
        """
        ...
    
    @property
    def sleep(self) -> bool:
        """
        True if the flight computer is currently in sleeping.
        Cannot be invoked after shutdown.
        """
        ...
        
    @property
    def time_since_start(self) -> int:
        """
        Time since the flight computer started in milliseconds. 
        Cannot be invoked after shutdown.
        """
        ...
    
    @property
    def is_ready(self) -> bool:
        """
        True if the flight computer is ready to accept a new command request, false otherwise.
        Cannot be invoked after shutdown.
        """
        ...
    
    @property
    def command_status(self) -> Dict:
        """
        # TODO - need to finish docstring
        Dict containing status information about the last command sent to the flight computer.
        Cannot be invoked after shutdown.
        
        Format:
            {
                cmd_tag: <command tag (str)>,
                cmd_target: <id of target device (int)> (optional)
                status_id: <command status id (int)>,
                status_name: <command status name (str)>,
                status_description: <command status description (str)>
            }
        """
        ...
    
    def set_valve(self, valve_id: int, state: int) -> None:
        """
        Sets the state of a valve on the flight computer. Cannot be invoked after shutdown.
        
        Args:
            valve_id (int): The ID of the valve to set.
            state (int): The new state of the valve (0 = closed, 1 = open).
        """
        ...
        
    def pulse_valve(self, valve_id: int, duration_ms: int) -> None:
        """
        Pulses a valve on the flight computer for a specified duration. Cannot be invoked after shutdown.
        
        Args:
            valve_id (int): The ID of the valve to pulse.
            duration_ms (int): The duration to pulse the valve in milliseconds.
        """
        ...
        
    def set_servo(self, servo_id: int, value: float) -> None:
        """
        Sets the position of a servo on the flight computer. Cannot be invoked after shutdown.
        
        Args:
            servo_id (int): The ID of the servo to set.
            position (int, float): The new position of the servo (speed, degrees, percent).
        """
        ...
    
    def pulse_servo(self, servo_id: int, value: float, duration_ms: int) -> None:
        """
        Pulses a servo on the flight computer to a specified position for a specified duration. Cannot be invoked after shutdown.
        
        Args:
            servo_id (int): The ID of the servo to pulse.
            value (int, float): The position to pulse the servo to (speed, degrees, percent).
            duration_ms (int): The duration to pulse the servo in milliseconds.
        """
        ...
        
    @mode.setter
    def mode(self, new_mode: str) -> None:
        """
        Sets the current mode of the flight computer. 
        Cannot be changed after shutdown.
        """
        ...
    
    @sleep.setter
    def sleep(self, value: bool) -> None:
        """
        Sets whether the flight computer is sleeping. 
        Cannot be changed after shutdown.
        """
        ...
    
    def send_custom_command(self, command_id: int, args: List[int]) -> None:
        """
        Sends a custom command to the flight computer. Cannot be invoked after shutdown.
        
        Args:
            command_id (int): The ID of the custom command to send.
            args (List[int]): A list of arguments for the command.
        """
        ...
        
    def shutdown(self) -> None:
        """
        Shuts down flight computer, stopping all active threads.
        """
        ...