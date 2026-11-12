"""Run the CC spoke with mocked hardware, for testing against a real hub.

    pipenv run python -m tests.run_mock_spoke

Connects to the hub at GSE_HUB_ADDR (default localhost:50051) as node 'cc', using the
real handlers from src/spoke_handlers.py. Every 100 ms it feeds the flight computer
fake ADC / state / comm packets, so the getter commands return changing values.
Ctrl-C to stop.
"""
import json
import logging
import os
import tempfile
import time
from collections import deque

# Mock hardware BEFORE importing anything that touches it (board, RPi.GPIO, ...)
import src.settings as settings
settings.MOCK_MODE = True
settings.RADIO_MOCK_MODE = True

from src.controller import Controller
from src.flight_computer import FlightComputer
from src.spoke import Spoke
from src.spoke_handlers import build_handlers

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, 'config', 'default', 'config.json')


def fake_packets(tick: int):
    """One round of FC downlink packets with values that change each tick."""
    adc = (bytearray([0x03, 0x01])
           + (tick % 1000).to_bytes(3, 'little', signed=True)
           + (-(tick % 500)).to_bytes(3, 'little', signed=True))
    state = (bytearray([0x04, tick // 10 % 4])  # valve bits cycle 00, 01, 10, 11
             + (tick % 1000).to_bytes(2, 'little')
             + (500).to_bytes(2, 'little')
             + (1000 - tick % 1000).to_bytes(2, 'little'))
    comm = (bytearray([0x05])
            + (tick % 65536).to_bytes(2, 'little')  # ping id
            + bytes([0])                            # mode
            + (tick * 100).to_bytes(4, 'little')    # ms since start
            + (0).to_bytes(2, 'little')             # last command id
            + bytes([0x00, 0x00]))                  # command status, message count
    return [adc, state, comm]


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    tmp = tempfile.TemporaryDirectory()
    fc_config = dict(config['flight_computer'])
    for key in ('sensor_log_path', 'state_log_path', 'status_log_path'):
        fc_config[key] = os.path.join(tmp.name, os.path.basename(fc_config[key]))

    controller = Controller.from_config(config)
    flight_computer = FlightComputer.from_config(fc_config)
    received_for_hub = deque(maxlen=1000)
    to_transmit = deque(maxlen=100)

    spoke = Spoke('cc', build_handlers(controller, flight_computer, received_for_hub, to_transmit))
    spoke.start()
    print(f"Mock CC spoke running, connecting to hub at {spoke.hub_addr}. Ctrl-C to stop.")

    try:
        tick = 0
        while True:
            tick += 1
            for packet in fake_packets(tick):
                flight_computer.process_packet(packet)
                received_for_hub.append(packet)  # so receive_packets has something to return
            to_transmit.clear()  # stands in for the main loop sending queued packets
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        spoke.stop()
        controller.shutdown()
        tmp.cleanup()


if __name__ == '__main__':
    main()
