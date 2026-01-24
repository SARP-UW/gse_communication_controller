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
        # 0x00
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
        # 0x01
        # <Latitude (4 bytes)>
        # <Longitude (4 bytes)>
        # <Altitude (4 bytes)>
        # <Velocity x (2 bytes)>
        # <Velocity y (2 bytes)>
        # <Velocity z (2 bytes)>
        # <Time (4 bytes)>
            
    # ADC data packet
        # 0x02
        # <packet index (1 byte)>
        # <data point (3 bytes)> (repeat for each sensor in adc config for this packet index)
            
    # State packet
        # 0x03
        # <valve state (1 bit)> (repeat for each valve in status protocol, pad to byte boundary)
        # <servo state (2 bytes)> (repeat for each servo in status protocol)

    # Status packet
        # 0x04
        # <last command state (1 byte)>
        # <last command type (1 byte)> (optional)
        # <last command tag (1 byte)> (optional)
        # <last command arguments (variable length)> (optional)
        # <message tag (1 byte)> (repeated for each desired message) (optional)
        
                    
# Uplink Packets (from CC to FC):

    # Command packet
        # 0x00
        # <command type (1 byte)>
        # <command tag (1 byte)>
        # <command arguments (variable length)>
                   
    # More info:

        # Command state values
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
                
            # Sleep command
                #0x03
                
            # Soft restart command (requires two packets to confirm)
                # 0x04
                
            # Hard restart command (requires two packets to confirm)
                # 0x05
                
            # Safe system (requires two packets to confirm)
                # 0x06

class FlightComputer:
    
    def __init__(self, radio: Radio, rs485_bus: RS485Bus, qdc_actuator: QDCActuator, ps_valves: List[PassthroughValve], 
                 ps_pressure_sensors: List[PassthroughPressureSensor], status_logger: Logger, state_logger: Logger, 
                 sensor_logger: Logger, adc_sensors_cfg: List[Dict], valves_cfg: List[Dict], servos_cfg: List[Dict], 
                 custom_commands_cfg: List[Dict], status_messages_cfg: List[Dict]) -> None:
        
        self._radio: Radio = radio
        self._rs485_bus: RS485Bus = rs485_bus
        self._qdc_actuator: QDCActuator = qdc_actuator
        self._ps_valves: List[PassthroughValve] = ps_valves
        self._ps_pressure_sensors: List[PassthroughPressureSensor] = ps_pressure_sensors
        self._status_logger: Logger = status_logger
        self._state_logger: Logger = state_logger
        self._sensor_logger: Logger = sensor_logger
        self._adc_sensors_cfg: List[Dict] = adc_sensors_cfg
        self._valves_cfg: List[Dict] = valves_cfg
        self._servos_cfg: List[Dict] = servos_cfg
        self._custom_commands_cfg: List[Dict] = custom_commands_cfg
        self._status_messages_cfg: List[Dict] = status_messages_cfg
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
        
    
    
    def shutdown(self) -> None:
        """
        Shuts down flight computer, stopping all active threads.
        """
        ...
        
       
    
        
            
    
    