from src.radio import Radio
from src.rs485_bus import RS485Bus
from src.qdc_actuator import QDCActuator
from src.valve import Valve
from src.pressure_sensor import PressureSensor
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
    # GENERAL FORMAT:
    # <TAG> <ALT TAG (?)> <DATA>

    # Sensor data packet:
        # Length: 52 bytes
        # FORMAT:
            # <0x00>
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
        # Length: 22 bytes
        # FORMAT:
            # <0x01>
            # <Latitude (4 bytes)>
            # <Longitude (4 bytes)>
            # <Altitude (4 bytes)>
            # <Velocity x (2 bytes)>
            # <Velocity y (2 bytes)>
            # <Velocity z (2 bytes)>
            # <Time (4 bytes)>
            
    # ADC data packet
        # Length: <?> (max 64 bytes)
        # FORMAT:
            # <0x02>
            # <?> (alt tag, 1 byte)
            # <?> (data, variable length)
        # Alt tag:
            # Denotes target packet mapping to use in config (adc_sensor_protocol)
        # Data:
            # 3 byte data points ordered according to index in target packet mapping.

            
    # Status packet
        # Length: <?> (max 64 bytes)
        # FORMAT:
            # <0x03>
            # <?> (data)
        # Data packet:
            # Variable size data points ordered according to index in config (status_protocol)
            # If "type" of data point is "valve" data is 1 bit (0 = closed, 1 = open)
            # If "type" of data point is "continuous_servo" data is 2 bytes (map 0 - "max_value" to 0 - "max_speed" deg/s)
            # If "type" of data point is "linear_servo" data is 2 bytes (map 0 - "max_value" to 0 - 100% extension)
            # If "type" of data point is "positional_servo" data is 2 bytes (map 0 - "max_value" to 0 - 360 degrees)             
            
    # Message packet
        # Length: 2 bytes
        # FORMAT:
            # <0x04>
            # <?> (message ID, 1 byte)
        # Message ID:
            # Denotes specific message ID in config (message_protocol)
    
            

FLIGHT_COMPUTER_RX_PROTOCOL = {
    "sensor"
}

class FlightComputer:
    
    def __init__(self, radio: Radio, rs485_bus: RS485Bus, qdc_actuator: QDCActuator, pst_valves: List[Valve], pst_pressure_sensors: List[PressureSensor], 
                 status_logger: Logger, fc_sensor_logger: Logger, pst_sensor_logger: Logger, sys_state_logger: Logger, commands: List[Dict]) -> None:
        ...
        
    def __del__(self) -> None:
        ...
        
    def __str__(self) -> str:
        """
        Gets string representation of FlightComputer.
        """
        
            
    