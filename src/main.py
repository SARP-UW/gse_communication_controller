import json
import argparse
import os
import signal
import time
import socket
from collections import deque
from src.controller import Controller
from src.flight_computer import FlightComputer
from src.website import Website
from src.logger import Logger
from src.spoke import Spoke
from src.radio import RADIO_MAX_PACKET_SIZE


def _get_ip_str() -> str:
    """
    Gets the IP address of this device as a string, or <device ip> if unknown.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            if ip and not ip.startswith('127.'):
                return ip
        finally:
            s.close()
    except Exception:
        pass
    return "<device ip>"

def main():
    """
    Main entry point for the Comm Controller program.
    """
    parser = argparse.ArgumentParser(
        description='Comm Controller - Flight Computer Communication and GSE Management',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=
            """
            Example usage:
            python main.py --config config/default/config.json
            python main.py -c config/default/config.json
            """
    )
    parser.add_argument(
        '-c', '--config',
        type=str,
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config/default/config.json'),
        help='Path to configuration file (default: config/default/config.json)'
    )
    args = parser.parse_args()

    def load_config(config_path: str) -> dict:
        """
        Loads a JSON configuration file from the given path.
        """
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in {config_path}: {e.msg}", e.doc, e.pos)

    # Treat SIGTERM (systemctl stop, Pi shutdown) the same as Ctrl-C for graceful hardware shutdown
    def _handle_sigterm(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _handle_sigterm)

    print("SYSTEM STATUS: Starting system...")

    controller = None
    flight_computer = None
    website = None
    spoke = None

    try:
        config = load_config(args.config)

        print("SYSTEM STATUS: Initializing controller...")
        controller = Controller.from_config(config)

        print("SYSTEM STATUS: Initializing flight computer...")
        flight_computer = FlightComputer.from_config(config['flight_computer'])

        print("SYSTEM STATUS: Initializing loggers...")
        cc_sensor_logger = Logger(
            config['cc_sensor_log_path'],
            [s['name'] for s in config['passthrough_pressure_sensors']]
        )

        print("SYSTEM STATUS: Initializing website...")
        # Note: config['website']['host'] holds the port number (8080), not a hostname.
        _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        website = Website(
            port=config['website']['host'],
            website_log_path=os.path.join(_repo_root, 'logs', 'website_log.txt'),
            flight_computer=flight_computer,
            controller=controller
        )

        received_for_hub = deque(maxlen=1000)

        def receive_packets(args):
            packets = []
            while received_for_hub:
                packets.append(received_for_hub.popleft().hex())
            return {'packets': packets, 'count': len(packets)}

        to_transmit = deque(maxlen=100)

        def transmit_packets(args):
            if 'packets' not in args:
                raise KeyError("missing arg 'packets'")
            packets = []
            for i, hex_str in enumerate(args['packets'].split(',')):
                packet = bytearray.fromhex(hex_str.strip()) 
                if not 1 <= len(packet) <= RADIO_MAX_PACKET_SIZE:
                    raise ValueError(f"packet {i} is {len(packet)} bytes; must be 1-{RADIO_MAX_PACKET_SIZE}")
                packets.append(packet)
            to_transmit.extend(packets)
            return {'queued': len(packets), 'waiting': len(to_transmit)}
        
        def get_comm_link(args):
            return {'active_link': controller.comm_link_type}
        
        def set_comm_link(args):
            controller.comm_link_type = args['link']

        def passthrough_valve_info(args):
            return {"valves" : controller.passthrough_valve_info}
        
        def passthrough_valve_states(args):
            return {"valve_states" : {str(k) : v for k,v in controller.passthrough_valve_states.items()}}
        
        def set_passthrough_valve_state(args):
            valve_id = int(args['id'])
            override = args['override'].strip().lower()
            if override not in ('true', 'false'):
                raise ValueError('override must be true or false')
            controller.set_passthrough_valve_state(valve_id, override == 'true')
            return {'id' : valve_id, 'state' : controller.passthrough_valve_states[valve_id]}

        def passthrough_pressure_sensor_info(args):
            return  {"sensor_info" : controller.passthrough_pressure_sensor_info}
        
        def passthrough_pressure_sensor_data(args):
            return {"sensor_data" : {str(k): v for k,v in controller.passthrough_pressure_sensor_data.items()}}

        def qdc_actuator_info(args):
            return {"qdc_actuator_info" : controller.qdc_actuator_info}
        
        def qdc_actuator_states(args):
            return {"qdc_actuator_states" : {str(k) : v for k,v in controller.qdc_actuator_states.items()}}
        
        def set_qdc_actuator_state(args):
            actuator_id = int(args['id'])
            state = args['state'].strip().lower()
            controller.set_qdc_actuator_state(actuator_id, state)
            return {'id' : actuator_id, 'state' : state}

        spoke = Spoke('cc', {
            'receive_packets': receive_packets,
            'transmit_packets': transmit_packets,
            'get_comm_link' : get_comm_link,
            'set_comm_link' : set_comm_link,
            "passthrough_valve_info" : passthrough_valve_info,
            "passthrough_valve_states" : passthrough_valve_states,
            "set_passthrough_valve_state" : set_passthrough_valve_state,
            "passthrough_pressure_sensor_info" : passthrough_pressure_sensor_info,
            "passthrough_pressure_sensor_data" : passthrough_pressure_sensor_data,
            "qdc_actuator_info" : qdc_actuator_info,
            "qdc_actuator_states" : qdc_actuator_states,
            "set_qdc_actuator_state" : set_qdc_actuator_state,
        })

        spoke.start()

        print("SYSTEM STATUS: System running!")
        print(f"SYSTEM STATUS: Website at: http://{_get_ip_str()}:{config['website']['host']}")

        # print("Setting passthrough state in main")
        # horribly written test that iterates through each valve and flips through each state
        # state = True
        # idx = 1
        # while True:
        #     print(f"Setting valve {idx} state to {state}")
        #     for i in range(3):
        #         state = not state
        #         controller.set_passthrough_valve_state(idx, state)
        #         time.sleep(2)
        #     idx += 1
        #     if idx == 5:
        #         idx = 1

        # print(f"Valve States: {controller.passthrough_valve_states}")
        # controller.set_qdc_actuator_state(1, 1)

        # slightly better written test that iterates through qdc states
        # states = ["locked", "released"]
        # actuator_id = 1
        # state_idx = 0

        # while True:
        #     print(f"Setting actuator {actuator_id} state to {states[state_idx]}")
        #     controller.set_qdc_actuator_state(actuator_id, states[state_idx])
        #     time.sleep(2)
            
        #     state_idx += 1
        #     if state_idx == len(states):
        #         state_idx = 0
        #         actuator_id = 2 if actuator_id == 1 else 1

        # extremely minimal rs485 test
        # Test write does not raise
        # controller._rs485.write(bytearray([0x01, 0x02, 0x03]))
        # print("PASS: write did not raise")

        # 0x55 rs485 test
        # while True:
        #     time.sleep(0.0001)
        #     controller._rs485.write(bytearray([0x55]))
        #     print("sent 0x55")

        # # Test read does not raise and returns bytearray
        # time.sleep(0.1)
        # rx = controller._rs485.read()
        # assert isinstance(rx, bytearray), f"Expected bytearray, got {type(rx)}"
        # print(f"PASS: read returned bytearray of length {len(rx)}")

        # print("RS485Bus tests passed!")

        
        # Comm loop: poll both links every 5 ms, respond to FC comm heartbeats
        _COMM_POLL_INTERVAL = 0.005  # 5 ms — well within the 10 ms response window
        _tick = 0
        while True:
            packets = controller.receive_packets()
            received_for_hub.extend(packets)  # share with the spoke's receive_packets handler
            for packet in packets:
                ping_id = flight_computer.process_packet(packet)
                if ping_id is not None:
                    # FC sent a comm packet — respond immediately
                    response = flight_computer.build_comm_response(ping_id)
                    # Send any packets queued by the spoke's transmit_packets handler after the response
                    hub_packets = []
                    while to_transmit:
                        hub_packets.append(to_transmit.popleft())
                    controller.transmit_packets([response] + hub_packets)
            _tick += 1
            if _tick % 20 == 0:
                sensor_data = controller.passthrough_pressure_sensor_data
                cc_sensor_logger.log_data([
                    str(sensor_data[s['input']])
                    for s in config['passthrough_pressure_sensors']
                ])
            time.sleep(_COMM_POLL_INTERVAL)

    except KeyboardInterrupt:
        print("\nSYSTEM STATUS: Stopping system...")
        if spoke:
            spoke.stop()
        if website:
            website.shutdown()
        if flight_computer:
            flight_computer.shutdown()
        if controller:
            controller.shutdown()

if __name__ == "__main__":
    main()
