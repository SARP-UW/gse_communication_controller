import datetime
import threading
from src.radio import Radio
from src.rs485_bus import RS485Bus
from src.qdc_actuator import QDCActuator
from src.passthrough_valve import PassthroughValve
from src.passthrough_pressure_sensor import PassthroughPressureSensor
from src.logger import Logger
from threading import Lock
from typing import Dict, List, Literal, Optional
import struct
import time as _time

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

# Sent at top every packet
# Magic number: 0x4A424D454A4D5352

# Downlink Packets (from FC to CC):

    # IMU, magnetometer, temp signed
    # barometer unsigned
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

    # unsigned
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
        # <data point (3 bytes) signed> (repeat for each sensor in adc config for this packet index)
            
    # State packet
        # 0x04
        # <valve state (1 bit)> (repeat for each valve in status protocol, pad to byte boundary)
        # <servo state (2 bytes) unsigned> (repeat for each servo in status protocol)

    # all unsigned
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

MAGIC_NUM = bytearray([0x4A, 0x42, 0x4D, 0x45, 0x4A, 0x4D, 0x53, 0x52])
# TODO: confirm byte order with FC team
_FC_BYTEORDER: Literal['little', 'big'] = 'little'

class FlightComputer:
    
    def __init__(self, rs485_bus: RS485Bus, radio: Radio) -> None:
        self._rs485_bus = rs485_bus
        self._radio = radio
        # --- static info (populated from config) ---
        self._adc_sensor_info: List[Dict] = []
        self._valve_info: List[Dict] = []
        self._servo_info: List[Dict] = []
        self._mode_info: List[Dict] = []
        self._custom_command_info: List[Dict] = []

        # --- live state (updated from downlink packets) ---
        self._adc_sensor_data: Dict[int, float] = {}
        self._imu_sensor_data: Dict[int, Dict[str, float]] = {}
        self._magnetometer_sensor_data: Dict[int, Dict[str, float]] = {}
        self._barometer_sensor_data: Dict[int, float] = {}
        self._temperature_sensor_data: Dict[int, float] = {}
        self._current_sensor_data: Dict[int, float] = {}
        self._gps_sensor_data: Dict[str, float] = {}
        self._valve_states: Dict[int, str] = {}
        self._servo_states: Dict[int, float] = {}
        self._mode: int = 0
        self._sleep: bool = False
        self._comm_link: int = 0
        self._time_since_start: int = 0
        self._is_ready: bool = True
        self._command_status: Dict = {
            "cmd_tag": None,
            "status_id": 0x00,
            "status_name": "waiting",
            "status_description": "Command waiting",
        }
        self._last_ping_id: int = None
        self._command_id: int = None
        self._next_command_type: bytes = None
        self._next_command_tag: bytes = None
        self._next_command_args: List[int] = []
        self._last_command_id: int = None
        self._messages: List = []
        self._command_sent: bool = False
        self._command_lock: threading.Lock = threading.Lock()

        self._pending_command: Optional[dict] = None
        self._next_command_id: int = 0
        self._adc_packet_map: Dict[int, List[int]] = {}  # packet_index -> ordered list of sensor ids
        self._shutdown_flag: bool = False
        
        self._sensor_logger: Optional[Logger] = None
        self._state_logger: Optional[Logger] = None
        self._status_logger: Optional[Logger] = None

        self._status_message_lookup: Optional[Dict] = None

        read_downlink_thread = threading.Thread(target = self._read_downlink_loop, daemon = True)
        read_downlink_thread.start()
        
    def __del__(self) -> None:
        """
        Destructor for FlightComputer, shuts down system.
        """
        self.shutdown()
        
    def __str__(self) -> str:
        """
        Gets string representation of FlightComputer.
        """
        ...
    
    @classmethod
    def from_config(cls, config: Dict) -> "FlightComputer":
        """
        Initializes a FlightComputer object from a configuration dictionary.

        Args:
            config: The 'flight_computer' section of the main config dict.
        """
        if 'adc_sensors' not in config:
            raise KeyError("Flight computer config missing key: 'adc_sensors'")
        if 'valves' not in config:
            raise KeyError("Flight computer config missing key: 'valves'")
        if 'servos' not in config:
            raise KeyError("Flight computer config missing key: 'servos'")
        if 'modes' not in config:
            raise KeyError("Flight computer config missing key: 'modes'")
        if 'custom_commands' not in config:
            raise KeyError("Flight computer config missing key: 'custom_commands'")

        if not isinstance(config['adc_sensors'], list):
            raise ValueError(f"Flight computer config 'adc_sensors' must be a list, got: {type(config['adc_sensors']).__name__}")
        if not isinstance(config['valves'], list):
            raise ValueError(f"Flight computer config 'valves' must be a list, got: {type(config['valves']).__name__}")
        if not isinstance(config['servos'], list):
            raise ValueError(f"Flight computer config 'servos' must be a list, got: {type(config['servos']).__name__}")
        if not isinstance(config['modes'], list):
            raise ValueError(f"Flight computer config 'modes' must be a list, got: {type(config['modes']).__name__}")
        if not isinstance(config['custom_commands'], list):
            raise ValueError(f"Flight computer config 'custom_commands' must be a list, got: {type(config['custom_commands']).__name__}")

        fc = cls()

        # Populate static info from config
        fc._adc_sensor_info = [
            {
                "id": sensor['protocol_index'],
                "name": sensor['name'],
                "type": sensor['type']
            }
            for sensor in config['adc_sensors']
        ]

        # Build packet_index -> [sensor_id, ...] map (sorted by protocol_index within each packet)
        packet_map: Dict[int, List[int]] = {}
        for sensor in config['adc_sensors']:
            pidx = sensor.get('packet_index', 1)
            packet_map.setdefault(pidx, []).append(sensor['protocol_index'])
        for pidx in packet_map:
            packet_map[pidx].sort()
        fc._adc_packet_map = packet_map

        fc._valve_info = [
            {
                "id": valve['protocol_index'],
                "name": valve['name']
            }
            for valve in config['valves']
        ]

        fc._servo_info = [
            {
                "id": servo['protocol_index'],
                "name": servo['name'],
                "type": servo['type']
            }
            for servo in config['servos']
        ]

        fc._mode_info = [
            {
                "id": mode['tag'],
                "name": mode['name'],
                "description": mode['description']
            }
            for mode in config['modes']
        ]

        fc._custom_command_info = [
            {
                "id": cmd['tag'],
                "name": cmd['name'],
                "description": cmd['description'],
                "args": cmd.get('args', [])
            }
            for cmd in config['custom_commands']
        ]

        # Initialize live state dicts from static info
        fc._adc_sensor_data = {sensor['id']: 0.0 for sensor in fc._adc_sensor_info}
        fc._valve_states = {valve['id']: "unknown" for valve in fc._valve_info}
        fc._servo_states = {servo['id']: 0.0 for servo in fc._servo_info}

        sensor_columns = [s['name'] for s in config['adc_sensors']]
        fc._sensor_logger = Logger(config['sensor_log_path'], sensor_columns)
        
        valve_columns = [v['name'] for v in config['valves']]
        servo_columns = [s['name'] for s in config['servos']]
        fc._state_logger = Logger(config['state_log_path'], valve_columns + servo_columns)
        
        fc._status_message_lookup = {                                                                                                                                                            
            msg['tag']: msg['message'] for msg in config.get('status_messages', [])                                                                                                                                         
        }    
        fc._status_logger = Logger(config['status_log_path'], ['event', 'description'])
        fc._status_logger.log_data(['startup', 'Flight computer object initialized from config'])

        return fc
    
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
        return list(self._adc_sensor_info)
    
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
        return list(self._valve_info)
        
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
        return list(self._servo_info)
    
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
        return list(self._mode_info)
        
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
        return list(self._custom_command_info)
    
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
        if self._shutdown_flag:
            raise RuntimeError("Cannot read ADC sensor data after shutdown")
        return dict(self._adc_sensor_data)
    
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
        if self._shutdown_flag:
            raise RuntimeError("Cannot read valve states after shutdown")
        return dict(self._valve_states)
    
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
        if self._shutdown_flag:
            raise RuntimeError("Cannot read servo states after shutdown")
        return dict(self._servo_states)
    
    @property
    def mode(self) -> int:
        """
        ID of the flight computer"s current mode.
        Cannot be invoked after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot read mode after shutdown")
        return self._mode
    
    @property
    def sleep(self) -> bool:
        """
        True if the flight computer is currently in sleeping.
        Cannot be invoked after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot read sleep state after shutdown")
        return self._sleep

    @property
    def comm_link(self) -> int:
        """
        Current comm link. 0 = RS495, 1 = radio
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot read sleep state after shutdown")
        return self._comm_link
        
    @property
    def time_since_start(self) -> int:
        """
        Time since the flight computer started in milliseconds. 
        Cannot be invoked after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot read time_since_start after shutdown")
        return self._time_since_start
    
    @property
    def is_ready(self) -> bool:
        """
        True if the flight computer is ready to accept a new command request, false otherwise.
        Cannot be invoked after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot read is_ready after shutdown")
        return self._is_ready
    
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
        if self._shutdown_flag:
            raise RuntimeError("Cannot read command_status after shutdown")
        return dict(self._command_status)
    
    def _read_downlink_loop(self, sample_hz: int):
        """
        Parses data from flight computer and sends command packet as necessary
        """
        # Read rs485, if not there, then try radio. Need to set frequency? what if buf in
        # middle of packet stream?  this loop handle collecting and packing?

        last_rs485_packet = bytearray()
        while not self._shutdown_flag:
            rs485_buf = self._rs485_bus.read()
            radio_buf = self._radio.receive()

            # rs485 is one stream of bytes, so have to handle getting middle of a packet?
            if len(rs485_buf) > 0:
                if MAGIC_NUM in rs485_buf:
                    if rs485_buf.find(MAGIC_NUM) == 0 and len(last_rs485_packet) > 0:
                        self._parse_packet(self, last_rs485_packet)
                        last_rs485_packet = bytearray()

                    rs485_buf_list = rs485_buf.split(MAGIC_NUM)

                    if len(last_rs485_packet) > 0:
                        last_rs485_packet += rs485_buf_list[0]
                        del rs485_buf_list[0]
                        self._parse_packet(self, last_rs485_packet[:])
                        last_rs485_packet = bytearray()
                    for packet in rs485_buf_list:
                        self._parse_packet(self, packet[:])
                else:
                    if len(last_rs485_packet) > 0:
                        last_rs485_packet += rs485_buf
            
            # Assuming each radio packet is the full packet
            if len(radio_buf) > 0:
                for packet in radio_buf:
                    if radio_buf.find(MAGIC_NUM) == 0:
                        self._parse_packet(self, packet[8:])

    def _parse_packet(self, packet: bytearray):
        """
        Determines what kind of packet it is and parses accordingly
        """
        match packet[0]:
            case 0x01:
                self._parse_sensor_packet(self, packet[1:])
            case 0x02:
                self._parse_gps_packet(self, packet[1:])
            case 0x03:
                self._parse_adc_packet(self, packet[1:])
            case 0x04:
                self._parse_state_packet(self, packet[1:])
            case 0x05:
                self._parse_comm_packet(self, packet[1:])
            case _:
                raise ValueError(f"Invalid packet type: {packet[0]} > 5")

    def _parse_sensor_packet(self, packet: bytearray):
        """
        Parses sensor packet
        """
        self._imu_sensor_data[1]["accel_x"] = int.from_bytes(packet[0:2], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[1]["accel_y"] = int.from_bytes(packet[2:4], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[1]["accel_z"] = int.from_bytes(packet[4:6], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[1]["gyro_x"] = int.from_bytes(packet[6:8], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[1]["gyro_y"] = int.from_bytes(packet[8:10], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[1]["gyro_z"] = int.from_bytes(packet[10:12], _FC_BYTEORDER, signed=True)

        self._imu_sensor_data[2]["accel_x"] = int.from_bytes(packet[12:14], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[2]["accel_y"] = int.from_bytes(packet[14:16], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[2]["accel_z"] = int.from_bytes(packet[16:18], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[2]["gyro_x"] = int.from_bytes(packet[18:20], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[2]["gyro_y"] = int.from_bytes(packet[20:22], _FC_BYTEORDER, signed=True)
        self._imu_sensor_data[2]["gyro_z"] = int.from_bytes(packet[22:24], _FC_BYTEORDER, signed=True)

        self._magnetometer_sensor_data[1]["mag_x"] = int.from_bytes(packet[24:26], _FC_BYTEORDER, signed=True)
        self._magnetometer_sensor_data[1]["mag_y"] = int.from_bytes(packet[26:28], _FC_BYTEORDER, signed=True)
        self._magnetometer_sensor_data[1]["mag_z"] = int.from_bytes(packet[28:30], _FC_BYTEORDER, signed=True)

        self._magnetometer_sensor_data[2]["mag_x"] = int.from_bytes(packet[30:32], _FC_BYTEORDER, signed=True)
        self._magnetometer_sensor_data[2]["mag_y"] = int.from_bytes(packet[32:34], _FC_BYTEORDER, signed=True)
        self._magnetometer_sensor_data[2]["mag_z"] = int.from_bytes(packet[34:36], _FC_BYTEORDER, signed=True)

        self._barometer_sensor_data[1] = int.from_bytes(packet[36:39], _FC_BYTEORDER)
        self._barometer_sensor_data[2] = int.from_bytes(packet[39:42], _FC_BYTEORDER)

        self._temperature_sensor_data[1] = int.from_bytes(packet[42:44], _FC_BYTEORDER, signed=True)
        self._temperature_sensor_data[2] = int.from_bytes(packet[44:46], _FC_BYTEORDER, signed=True)

        self._current_sensor_data[1] = int.from_bytes(packet[46:48], _FC_BYTEORDER)
        self._current_sensor_data[2] = int.from_bytes(packet[48:50], _FC_BYTEORDER)
        self._current_sensor_data[3] = int.from_bytes(packet[50:52], _FC_BYTEORDER)

    def _parse_gps_packet(self, packet: bytearray):
        """
        Parses GPS data packet
        """
        self._gps_sensor_data["latitude"] = int.from_bytes(packet[0:4], _FC_BYTEORDER)
        self._gps_sensor_data["longitude"] = int.from_bytes(packet[4:8], _FC_BYTEORDER)
        self._gps_sensor_data["altitude"] = int.from_bytes(packet[8:12], _FC_BYTEORDER)
        self._gps_sensor_data["velocity_x"] = int.from_bytes(packet[12:14], _FC_BYTEORDER)
        self._gps_sensor_data["velocity_y"] = int.from_bytes(packet[14:16], _FC_BYTEORDER)
        self._gps_sensor_data["velocity_z"] = int.from_bytes(packet[16:18], _FC_BYTEORDER)
        self._gps_sensor_data["time"] = int.from_bytes(packet[18:22], _FC_BYTEORDER)

    def _parse_adc_packet(self, packet: bytearray):
        """
        Parses ADC data packet
        """
        if len(packet) < len(self._adc_sensor_info) * 3:
            return
        if packet[0] == 0x00: # packet index. Need more later?
            for i in range(len(self._adc_sensor_info)):
                self._adc_sensor_data[self._adc_sensor_info[i]["id"]] = int.from_bytes(packet[1 + i:1 + i * 3], _FC_BYTEORDER, signed=True)
            self._sensor_logger.log_data([
                str(self._adc_sensor_data[s['id']]) for s in self._adc_sensor_info
            ])

    def _parse_state_packet(self, packet: bytearray):
        """
        Parses state packet
        """
        valve_count = len(self._valve_info)
        valve_num_bytes = valve_count / 8 if valve_count % 8 == 0 else valve_count / 8 + 1

        if len(packet) < valve_num_bytes + len(self._servo_info) * 3:
            return

        for i in range(valve_num_bytes):
            for j in range(max(8, valve_count - (8 * i))):
                self._valve_states[self._valve_info[(i * 8) + j]["id"]] = (packet[i] >> j) & 1

        for i in range(len(self._servo_info)):
            self._servo_states[self._servo_info[i]["id"]] = int.from_bytes(packet[valve_num_bytes + i:valve_num_bytes + i * 3], _FC_BYTEORDER)

        self._state_logger.log_data(
            [str(self._valve_states[v['id']]) for v in self._valve_info] +
            [str(self._servo_states[s['id']]) for s in self._servo_info]
        )

    def _parse_comm_packet(self, packet: bytearray):
        """
        Parses comm packet
        """
        if (self._last_ping_id != None):
            if (int.from_bytes(packet[0:2], _FC_BYTEORDER) != self._last_ping_id + 1):
                self._status_logger.log_data(["missed_ping", f"expected {self._last_ping_id + 1}, got {int.from_bytes(packet[0:2], _FC_BYTEORDER)}"])
        self._last_ping_id = int.from_bytes(packet[0:2], _FC_BYTEORDER)
        self._mode = packet[2]
        self._time_since_start = int.from_bytes(packet[3:7], _FC_BYTEORDER)

        curr_command_id = int.from_bytes(packet[7:9], _FC_BYTEORDER)
        if curr_command_id != self._last_command_id:
            self._status_logger.log_data(["command_status_change", f"cmd_id {curr_command_id}, status {self._command_status_id_to_name(packet[9])}"])

        self._command_status["cmd_tag"] = curr_command_id
        self._command_status["status_id"] = packet[9]
        self._command_status["status_name"] = self._command_status_id_to_name(packet[9])

        for i in range(packet[10]):
            self._messages.append(packet[11 + i])
        
        self._send_comm_packet(self)


    def _command_status_id_to_name(self, id: bytes):
        """
        Converts from command status id (bytes) to command status name
        """
        match id:
            case 0x00:
                return "waiting"
            case 0x01:
                return "in progress"
            case 0x02:
                return "failed due to invalid tag"
            case 0x03:
                return "failed due to invalid arguments"
            case 0x04:
                return "failed due to invalid arguments"
            case 0x05:
                return "failed due to out of range arguments"
            case 0x06:
                return "failed due to hardware error"  
            case 0x07:
                return "failed due to timeout"
            case 0x08:
                return "failed due to invalid system state"
            case 0x09:
                return "aborted by flight computer"
            case 0x0A:
                return "awaiting confirmation"
            case _:
                raise ValueError(f"Invalid status id: {id} > 0x0A")

    def _send_comm_packet(self):
        """
        Send comm packet
        """
        packet = bytearray()
        packet.append(0x01)
        packet.append(int.to_bytes(self._last_ping_id, 2))
        packet.append(int.to_bytes(datetime.now(), 4))
        
        self._command_lock.acquire()
        if self._next_command_type != None and self._next_command_tag != None:
            packet.append(0x01)
            self._command_id += 1
            packet.append(int.to_bytes(self._command_id, 2))
            packet.append(self._next_command_type, 1)
            self._append_next_command_args(self, packet)
            self._command_sent = True
        else:
            packet.append(0x00)
        
        self._command_lock.release()

        self._rs485_bus.write(packet)
        self._radio.transmit(packet)

    def _append_next_command_args(self, packet: bytearray):
        if self._next_command_type == 0x00:
            match self._next_command_tag:
                case 0x00:
                    if len(self._next_command_args) != 2:
                        return ValueError(f"Expecting 2 arguments for {self._next_command_tag} but received {len(self._next_command_args)}")
                    packet.append(int.to_bytes(self._next_command_args[0], 1))
                    packet.append(int.to_bytes(self._next_command_args[1], 1))
                case 0x01:
                    if len(self._next_command_args) != 2:
                        return ValueError(f"Expecting 2 arguments for {self._next_command_tag} but received {len(self._next_command_args)}")
                    packet.append(int.to_bytes(self._next_command_args[0], 1))
                    packet.append(int.to_bytes(self._next_command_args[1], 2))
                case 0x02:
                    if len(self._next_command_args) != 2:
                        return ValueError(f"Expecting 2 arguments for {self._next_command_tag} but received {len(self._next_command_args)}")
                    packet.append(int.to_bytes(self._next_command_args[0], 1))
                    packet.append(int.to_bytes(self._next_command_args[1], 2))
                case 0x03:
                    if len(self._next_command_args) != 2:
                        return ValueError(f"Expecting 3 arguments for {self._next_command_tag} but received {len(self._next_command_args)}")
                    packet.append(int.to_bytes(self._next_command_args[0], 1))
                    packet.append(int.to_bytes(self._next_command_args[1], 2))
                    packet.append(int.to_bytes(self._next_command_args[2], 2))
                # Finish when commands confirmed
                case _:
                    ... # do nothing. Do we need default case?

        # Discussing with Mark
                    
    def _set_next_command(self, command_type: bytes, command_tag: bytes, args: List[int]):
        if self._shutdown_flag:
            raise RuntimeError("Cannot set mode after shutdown")
        
        if not self._command_sent:
            return ValueError(f"Previous command not sent yet. Prev command id {self._command_id + 1} tag: {self._next_command_tag}")
        if self._command_status["status_id"] != 0x02:
            return ValueError(f"Previous command not completed yet. Prev command id {self._command_id + 1} status: {self._command_status_id_to_name}")
        
        self._command_lock.acquire()
        self._next_command_type = command_type
        self._next_command_tag = command_tag
        self._next_command_args = args
        self._command_sent = False
        self._command_lock.release()

    def set_valve(self, valve_id: int, state: int) -> None:
        """
        Enqueues a "change valve state" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            valve_id (int): The ID of the valve to set.
            state (int): The new state of the valve (0 = closed, 1 = open).
        """
        args = [valve_id, state]
        self._set_next_command(self, 0x00, 0x00, args) # + args
        
    def pulse_valve(self, valve_id: int, duration_ms: int) -> None:
        """
        Enqueues a "pulse valve" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            valve_id (int): The ID of the valve to pulse.
            duration_ms (int): The duration to pulse the valve in milliseconds.
        """
        args = [valve_id, duration_ms]
        self._set_next_command(self, 0x00, 0x01, args)
        
    def set_servo(self, servo_id: int, value: float) -> None:
        """
        Enqueues a "change servo state" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            servo_id (int): The ID of the servo to set.
            value (float): The new position of the servo (speed, degrees, or percent).
        """
        args = [servo_id, value]
        self._set_next_command(self, 0x00, 0x02, args)
    
    def pulse_servo(self, servo_id: int, value: float, duration_ms: int) -> None:
        """
        Enqueues a "pulse servo" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            servo_id (int): The ID of the servo to pulse.
            value (float): The position to pulse the servo to.
            duration_ms (int): The duration to pulse the servo in milliseconds.
        """
        args = [servo_id, value, duration_ms]
        self._set_next_command(self, 0x00, 0x03, args)

    def restart(self):
        """
        Restarts flight computer. Requres 2 commands to confirm
        """
        self._set_next_command(self, 0x00, 0x06, [])

    @mode.setter
    def mode(self, new_mode: int) -> None:
        """
        Sets the current mode of the flight computer. 
        Cannot be changed after shutdown.
        """
        args = [new_mode]
        self._set_next_command(self, 0x00, 0x04, args)


    @comm_link.setter
    def comm_link(self, new_link: int) -> None:
        """
        Set comm_link

        Args:
        new_link: 0 = RS485, 1 = radio
        """
        args = [new_link]
        self._set_next_command(self, 0x00, 0x05, args)


    @sleep.setter
    def sleep(self, value: bool) -> None:
        """
        Sets whether the flight computer is sleeping. 
        Cannot be changed after shutdown.

        value: False = wake, True = sleep
        """
        if value == self._sleep:
            raise ValueError(f"Flight computer is already in {value}")
        if value:
            self._set_next_command(self, 0x00, 0x04, [])
        else:
            self._set_next_command(self, 0x00, 0x05, [])
    
    def send_custom_command(self, command_id: int, args: List[int]) -> None:
        """
        Enqueues a custom command for the flight computer. Cannot be invoked after shutdown.

        Args:
            command_id (int): The tag of the custom command to send.
            args (List[int]): A list of byte-valued arguments for the command.
        """
        self._set_next_command(self, 0x01, 0x00, args) # add args and change 0x00 to from config
        
    def shutdown(self) -> None:
        """
        Shuts down flight computer, stopping all active threads.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot shutdown flight computer more than once")
        self._status_logger.log_data(['shutdown', 'flight computer shutdown'])
        self.read_downlink_thread.stop()
        self._shutdown_flag = True