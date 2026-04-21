from src.radio import Radio
from src.rs485_bus import RS485Bus
from src.qdc_actuator import QDCActuator
from src.passthrough_valve import PassthroughValve
from src.passthrough_pressure_sensor import PassthroughPressureSensor
from src.logger import Logger
from threading import Lock
from typing import Dict, List, Optional
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
        # --- static info (populated from config) ---
        self._adc_sensor_info: List[Dict] = []
        self._valve_info: List[Dict] = []
        self._servo_info: List[Dict] = []
        self._mode_info: List[Dict] = []
        self._custom_command_info: List[Dict] = []

        # --- live state (updated from downlink packets) ---
        self._adc_sensor_data: Dict[int, float] = {}
        self._valve_states: Dict[int, str] = {}
        self._servo_states: Dict[int, float] = {}
        self._mode: int = 0
        self._sleep: bool = False
        self._time_since_start: int = 0
        self._is_ready: bool = True
        self._command_status: Dict = {
            "cmd_tag": None,
            "status_id": 0x00,
            "status_name": "waiting",
            "status_description": "Command waiting",
        }

        self._pending_command: Optional[dict] = None
        self._next_command_id: int = 0
        self._adc_packet_map: Dict[int, List[int]] = {}  # packet_index -> ordered list of sensor ids
        self._shutdown_flag: bool = False
        # Protects _pending_command accessed from website thread (writers) and comm loop (reader)
        self._command_lock: Lock = Lock()

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
        ID of the flight computer's current mode.
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
    
    def set_valve(self, valve_id: int, state: int) -> None:
        """
        Enqueues a "change valve state" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            valve_id (int): The ID of the valve to set.
            state (int): The new state of the valve (0 = closed, 1 = open).
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot set valve after shutdown")
        with self._command_lock:
            self._next_command_id = (self._next_command_id + 1) & 0xFFFF  # wrap to fit H format
            self._pending_command = {
                "id": self._next_command_id,
                "type": 0x00,   # static command
                "tag": 0x00,    # change valve state
                "args": bytearray([valve_id & 0xFF, state & 0xFF]),
            }

    def pulse_valve(self, valve_id: int, duration_ms: int) -> None:
        """
        Enqueues a "pulse valve" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            valve_id (int): The ID of the valve to pulse.
            duration_ms (int): The duration to pulse the valve in milliseconds.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot pulse valve after shutdown")
        with self._command_lock:
            self._next_command_id = (self._next_command_id + 1) & 0xFFFF
            self._pending_command = {
                "id": self._next_command_id,
                "type": 0x00,
                "tag": 0x01,    # pulse valve
                "args": struct.pack(">BH", valve_id & 0xFF, duration_ms),
            }

    def set_servo(self, servo_id: int, value: float) -> None:
        """
        Enqueues a "change servo state" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            servo_id (int): The ID of the servo to set.
            value (float): The new position of the servo (speed, degrees, or percent).
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot set servo after shutdown")
        with self._command_lock:
            self._next_command_id = (self._next_command_id + 1) & 0xFFFF
            self._pending_command = {
                "id": self._next_command_id,
                "type": 0x00,
                "tag": 0x02,    # change servo state
                "args": struct.pack(">Bh", servo_id & 0xFF, int(value)),
            }

    def pulse_servo(self, servo_id: int, value: float, duration_ms: int) -> None:
        """
        Enqueues a "pulse servo" command for the flight computer. Cannot be invoked after shutdown.

        Args:
            servo_id (int): The ID of the servo to pulse.
            value (float): The position to pulse the servo to.
            duration_ms (int): The duration to pulse the servo in milliseconds.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot pulse servo after shutdown")
        with self._command_lock:
            self._next_command_id = (self._next_command_id + 1) & 0xFFFF
            self._pending_command = {
                "id": self._next_command_id,
                "type": 0x00,
                "tag": 0x03,    # pulse servo
                "args": struct.pack(">BhH", servo_id & 0xFF, int(value), duration_ms),
            }
        
    @mode.setter
    def mode(self, new_mode: int) -> None:
        """
        Sets the current mode of the flight computer. 
        Cannot be changed after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot set mode after shutdown")
        self._mode = new_mode
    
    @sleep.setter
    def sleep(self, value: bool) -> None:
        """
        Sets whether the flight computer is sleeping. 
        Cannot be changed after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot set sleep state after shutdown")
        self._sleep = value
    
    def send_custom_command(self, command_id: int, args: List[int]) -> None:
        """
        Enqueues a custom command for the flight computer. Cannot be invoked after shutdown.

        Args:
            command_id (int): The tag of the custom command to send.
            args (List[int]): A list of byte-valued arguments for the command.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot send custom command after shutdown")
        with self._command_lock:
            self._next_command_id = (self._next_command_id + 1) & 0xFFFF
            self._pending_command = {
                "id": self._next_command_id,
                "type": 0x01,   # custom command
                "tag": command_id & 0xFF,
                "args": bytearray(args),
            }
        
    def process_packet(self, packet: bytearray) -> Optional[int]:
        """
        Processes a downlink packet from the flight computer and updates internal state.

        Returns the ping_id if this was a comm packet (type 0x05), otherwise None.
        Cannot be invoked after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot process packets after shutdown")
        if not packet:
            return None

        ptype = packet[0]
        if ptype == 0x03:
            self._process_adc_packet(packet)
        elif ptype == 0x04:
            self._process_state_packet(packet)
        elif ptype == 0x05:
            return self._process_comm_packet(packet)
        # 0x01 (sensor data) and 0x02 (GPS) are skipped — no state model yet
        return None

    def _process_comm_packet(self, packet: bytearray) -> Optional[int]:
        # type(B) + ping_id(H) + mode(B) + proc_time(I) + last_cmd_id(H) + last_cmd_status(B) + msg_count(B)
        if len(packet) < 12:
            return None
        _, ping_id, mode, proc_time, _, last_cmd_status, _ = struct.unpack_from(">BHBIHBB", packet)
        self._time_since_start = proc_time
        self._mode = mode
        # Update command status from last_cmd_status
        status_map = {
            0x00: ("waiting", "Command waiting"),
            0x01: ("in_progress", "Command in progress"),
            0x02: ("completed", "Command completed successfully"),
            0x03: ("failed_tag", "Command failed: invalid tag"),
            0x04: ("failed_args", "Command failed: invalid arguments"),
            0x05: ("failed_range", "Command failed: out of range arguments"),
            0x06: ("failed_hw", "Command failed: hardware error"),
            0x07: ("failed_timeout", "Command failed: timeout"),
            0x08: ("failed_state", "Command failed: invalid system state"),
            0x09: ("aborted", "Command aborted by flight computer"),
            0x0A: ("awaiting_confirm", "Command awaiting confirmation"),
        }
        status_name, status_desc = status_map.get(last_cmd_status, ("unknown", "Unknown status"))
        self._command_status["status_id"] = last_cmd_status
        self._command_status["status_name"] = status_name
        self._command_status["status_description"] = status_desc
        # Not ready when FC is actively processing or waiting for confirmation
        self._is_ready = last_cmd_status not in (0x01, 0x0A)
        return ping_id

    def _process_adc_packet(self, packet: bytearray) -> None:
        if len(packet) < 2:
            return
        packet_index = packet[1]
        sensor_ids = self._adc_packet_map.get(packet_index, [])
        offset = 2
        for sensor_id in sensor_ids:
            if offset + 3 > len(packet):
                break
            raw = (packet[offset] << 16) | (packet[offset + 1] << 8) | packet[offset + 2]
            self._adc_sensor_data[sensor_id] = float(raw)
            offset += 3

    def _process_state_packet(self, packet: bytearray) -> None:
        num_valves = len(self._valve_info)
        num_valve_bytes = (num_valves + 7) // 8
        if len(packet) < 1 + num_valve_bytes:
            return
        valve_bytes = packet[1:1 + num_valve_bytes]
        for i, valve in enumerate(sorted(self._valve_info, key=lambda v: v["id"])):
            byte_idx = i // 8
            bit_idx = i % 8
            state_bit = (valve_bytes[byte_idx] >> bit_idx) & 1
            self._valve_states[valve["id"]] = "open" if state_bit else "closed"
        offset = 1 + num_valve_bytes
        for servo in sorted(self._servo_info, key=lambda s: s["id"]):
            if offset + 2 > len(packet):
                break
            value = struct.unpack_from(">h", packet, offset)[0]
            self._servo_states[servo["id"]] = float(value)
            offset += 2

    def build_comm_response(self, ping_id: int) -> bytearray:
        """
        Builds an uplink comm packet (type 0x01) echoing ping_id.
        Includes one pending command if queued; clears the queue after.
        Cannot be invoked after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot build comm response after shutdown")

        timestamp = int(_time.time())
        # Atomic read-and-clear under lock to prevent race with website thread writers
        with self._command_lock:
            command = self._pending_command
            self._pending_command = None

        if command is None:
            # type(B) + ping_id(H) + timestamp(I) + command_valid(B)
            return bytearray(struct.pack(">BHIB", 0x01, ping_id, timestamp, 0))

        cmd_id = command.get("id", 0)
        cmd_type = command.get("type", 0)
        cmd_tag = command.get("tag", 0)
        cmd_args = command.get("args", bytearray())
        # type(B) + ping_id(H) + timestamp(I) + command_valid(B) + cmd_id(H) + cmd_type(B) + cmd_tag(B) + args
        header = struct.pack(">BHIBHBB", 0x01, ping_id, timestamp, 1, cmd_id, cmd_type, cmd_tag)
        return bytearray(header) + bytearray(cmd_args)

    def shutdown(self) -> None:
        """
        Shuts down flight computer, stopping all active threads.
        """
        if self._shutdown_flag:
            return
        self._shutdown_flag = True