import json
import argparse
import os
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
        default=f'{os.path.dirname(__file__)}/config/default/config.json',
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
        website = Website(
            port=config['website']['host'],
            website_log_path=os.path.join(os.path.dirname(__file__), 'logs', 'website_log.txt'),
            flight_computer=flight_computer
        )

        print("SYSTEM STATUS: System running!")
        print(f"SYSTEM STATUS: Website at: http://{_get_ip_str()}:{config['website']['host']}")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nSYSTEM STATUS: Stopping system...")
        if website:
            website.shutdown()
        if controller:
            controller.shutdown()

if __name__ == "__main__":
    main()