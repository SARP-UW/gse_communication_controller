import json
import argparse
import os
import signal
import time
import socket
from src.controller import Controller
from src.flight_computer import FlightComputer
from src.website import Website
from src.logger import Logger

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

def print_comm_packet(packet: bytearray) -> None:
    """Prints each field of an FC comm packet (type 0x05) by name."""
    print("  magic:           ", packet[0:8].hex(" "))
    print("  packet_type:     ", hex(packet[8]))
    print("  ping_id:         ", int.from_bytes(packet[9:11], "big"))
    print("  system_mode:     ", packet[11])
    print("  processor_time:  ", int.from_bytes(packet[12:16], "big"), "ms")
    print("  last_command_id: ", int.from_bytes(packet[16:18], "big"))
    print("  last_cmd_status: ", hex(packet[18]))
    print("  message_count:   ", packet[19])
    print("  message_tags:    ", list(packet[20:20 + packet[19]]))

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

        print("SYSTEM STATUS: System running!")
        print(f"SYSTEM STATUS: Website at: http://{_get_ip_str()}:{config['website']['host']}")

        # Comm loop: poll both links every 5 ms, respond to FC comm heartbeats
        _COMM_POLL_INTERVAL = 0.002 # 0.005  # 5 ms — well within the 10 ms response window
        _tick = 0
        while True:
            packets = controller.receive_packets()

            for packet in packets:
                if packet[8] == 0x05:
                    print_comm_packet(packet)

                print("RX:", packet.hex(" "))
                ping_id = flight_computer.process_packet(packet)
                if ping_id is not None:
                    # FC sent a comm packet — respond immediately
                     response = flight_computer.build_comm_response(ping_id)
                     print("TX:", response.hex(" "))
                     print(f'ping id recieved -> {ping_id}')
                     controller.transmit_packets([response])
                     print(f'tx sent')

            # test command to toggle valve every 500 ticks (2.5 seconds at 5 ms per tick) 
            # if _tick % 500 == 0:
            #    flight_computer.set_valve(0, (_tick // 500) % 2)

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
        if website:
            website.shutdown()
        if flight_computer:
            flight_computer.shutdown()
        if controller:
            controller.shutdown()

if __name__ == "__main__":
    main()
