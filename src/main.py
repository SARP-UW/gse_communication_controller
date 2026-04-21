import json
import argparse
import os
import signal
import time
import socket
from src.controller import Controller
from src.flight_computer import FlightComputer
from src.website import Website

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

    try:
        config = load_config(args.config)

        print("SYSTEM STATUS: Initializing controller...")
        controller = Controller.from_config(config)

        print("SYSTEM STATUS: Initializing flight computer...")
        flight_computer = FlightComputer.from_config(config['flight_computer'])

        print("SYSTEM STATUS: Initializing website...")
        # Note: config['website']['host'] holds the port number (8080), not a hostname.
        _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        website = Website(
            port=config['website']['host'],
            website_log_path=os.path.join(_repo_root, 'logs', 'website_log.txt'),
            flight_computer=flight_computer
        )

        print("SYSTEM STATUS: System running!")
        print(f"SYSTEM STATUS: Website at: http://{_get_ip_str()}:{config['website']['host']}")

        # Comm loop: poll both links every 5 ms, respond to FC comm heartbeats
        _COMM_POLL_INTERVAL = 0.005  # 5 ms — well within the 10 ms response window
        while True:
            packets = controller.receive_packets()
            for packet in packets:
                ping_id = flight_computer.process_packet(packet)
                if ping_id is not None:
                    # FC sent a comm packet — respond immediately
                    response = flight_computer.build_comm_response(ping_id)
                    controller.transmit_packets([response])
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