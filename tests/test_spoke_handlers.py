"""Tests that every Spoke command handler works end to end.

Each command is sent through Spoke's real response path (Spoke._handle), so a
handler that returns data protobuf can't encode (int dict keys, bytes, ...)
fails here the same way it would for the hub.

Runs on a laptop: hardware is mocked via settings.MOCK_MODE.

    pipenv run python -m unittest tests.test_spoke_handlers -v
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from collections import deque
from unittest import mock

from google.protobuf import struct_pb2

# Mock hardware BEFORE importing anything that touches it (board, RPi.GPIO, ...)
import src.settings as settings
settings.MOCK_MODE = True
settings.RADIO_MOCK_MODE = True

from src.controller import Controller
from src.flight_computer import FlightComputer, MAGIC_NUM, _FC_BYTEORDER as BYTEORDER
from src.spoke import Spoke
from src.spoke_handlers import build_handlers

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'generated'))
import controller_pb2  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO_ROOT, 'config', 'default', 'config.json')

# Public Controller / FlightComputer members that intentionally have no command
NOT_EXPOSED = {
    'shutdown', 'from_config',                 # lifecycle, owned by main()
    'process_packet', 'build_comm_response',   # main-loop internals (100 ms comm cycle)
}

# Public member -> the command(s) that expose it
CONTROLLER_COVERAGE = {
    'comm_link_type': ['get_comm_link', 'set_comm_link'],
    'receive_packets': ['receive_packets'],    # handler drains packets the main loop received
    'transmit_packets': ['transmit_packets'],  # handler queues packets for the main loop to send
    'passthrough_valve_info': ['passthrough_valve_info'],
    'passthrough_valve_states': ['passthrough_valve_states'],
    'set_passthrough_valve_state': ['set_passthrough_valve_state'],
    'passthrough_pressure_sensor_info': ['passthrough_pressure_sensor_info'],
    'passthrough_pressure_sensor_data': ['passthrough_pressure_sensor_data'],
    'qdc_actuator_info': ['qdc_actuator_info'],
    'qdc_actuator_states': ['qdc_actuator_states'],
    'set_qdc_actuator_state': ['set_qdc_actuator_state'],
}

FC_COVERAGE = {
    'adc_sensor_info': ['adc_sensor_info'],
    'valve_info': ['valve_info'],
    'servo_info': ['servo_info'],
    'mode_info': ['mode_info'],
    'custom_command_info': ['custom_command_info'],
    'adc_sensor_data': ['adc_sensor_data'],
    'valve_states': ['valve_states'],
    'servo_states': ['servo_states'],
    'mode': ['mode', 'set_mode'],
    'sleep': ['sleep', 'set_sleep'],
    'comm_link': ['comm_link', 'set_fc_comm_link'],
    'time_since_start': ['time_since_start'],
    'is_ready': ['is_ready'],
    'command_status': ['command_status'],
    'set_valve': ['set_valve'],
    'pulse_valve': ['pulse_valve'],
    'set_servo': ['set_servo'],
    'pulse_servo': ['pulse_servo'],
    'restart': ['restart'],
    'send_custom_command': ['send_custom_command'],
}


def public_members(cls):
    return {name for name in dir(cls) if not name.startswith('_')}


class SpokeHandlerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(CONFIG_PATH) as f:
            config = json.load(f)

        cls._tmp = tempfile.TemporaryDirectory()
        fc_config = dict(config['flight_computer'])
        for key in ('sensor_log_path', 'state_log_path', 'status_log_path'):
            fc_config[key] = os.path.join(cls._tmp.name, os.path.basename(fc_config[key]))

        cls.config = config
        cls.controller = Controller.from_config(config)  # singleton: one per test run
        cls.fc = FlightComputer.from_config(fc_config)
        cls.received_for_hub = deque(maxlen=1000)
        cls.to_transmit = deque(maxlen=100)
        cls.handlers = build_handlers(cls.controller, cls.fc, cls.received_for_hub, cls.to_transmit)
        cls.spoke = Spoke('cc', cls.handlers)

    @classmethod
    def tearDownClass(cls):
        cls.controller.shutdown()
        cls._tmp.cleanup()

    # ---------------------------------------------------------------- helpers

    def call(self, name, **args):
        """Send one command through Spoke's real handling path; return (status, data dict, message)."""
        command = controller_pb2.Command(command_name=name, args=args, command_id=1)
        response = asyncio.run(self.spoke._handle(command))
        data = {k: _to_py(v) for k, v in response.data.items()}
        return response.status, data, response.message

    def assertCompleted(self, name, expected_keys=(), **args):
        status, data, message = self.call(name, **args)
        self.assertEqual(status, controller_pb2.COMPLETED, f"{name} failed: {message}")
        for key in expected_keys:
            self.assertIn(key, data, f"{name} response missing key {key!r}: {data}")
        return data

    def assertFailed(self, name, **args):
        status, _, message = self.call(name, **args)
        self.assertEqual(status, controller_pb2.FAILED, f"{name} should have failed with args {args}")
        self.assertTrue(message, f"{name} failed without an error message")

    # ---------------------------------------------------------------- coverage

    def test_every_controller_member_has_a_command(self):
        exposed = public_members(Controller) - NOT_EXPOSED
        self.assertEqual(exposed - CONTROLLER_COVERAGE.keys(), set(),
                         "Controller members with no Spoke command")
        for member, commands in CONTROLLER_COVERAGE.items():
            for command in commands:
                self.assertIn(command, self.handlers, f"Controller.{member}: command {command!r} not registered")

    def test_every_flight_computer_member_has_a_command(self):
        exposed = public_members(FlightComputer) - NOT_EXPOSED
        self.assertEqual(exposed - FC_COVERAGE.keys(), set(),
                         "FlightComputer members with no Spoke command")
        for member, commands in FC_COVERAGE.items():
            for command in commands:
                self.assertIn(command, self.handlers, f"FlightComputer.{member}: command {command!r} not registered")

    def test_unknown_command_fails(self):
        self.assertFailed('not_a_command')

    # ---------------------------------------------------------------- controller

    def test_receive_packets(self):
        self.received_for_hub.extend([bytearray([0x01, 0x02]), bytearray([0xff])])
        data = self.assertCompleted('receive_packets', ['packets', 'count'])
        self.assertEqual(data['packets'], ['0102', 'ff'])
        self.assertEqual(data['count'], 2)
        self.assertEqual(self.assertCompleted('receive_packets')['count'], 0)  # drained

    def test_transmit_packets(self):
        self.to_transmit.clear()
        data = self.assertCompleted('transmit_packets', ['queued', 'waiting'], packets='0a0b, ff01')
        self.assertEqual(data['queued'], 2)
        self.assertEqual(list(self.to_transmit), [bytearray([0x0a, 0x0b]), bytearray([0xff, 0x01])])
        self.assertFailed('transmit_packets')
        self.assertFailed('transmit_packets', packets='zz')
        self.to_transmit.clear()

    def test_comm_link(self):
        self.assertCompleted('set_comm_link', link='radio')
        self.assertEqual(self.assertCompleted('get_comm_link', ['active_link'])['active_link'], 'radio')
        self.assertCompleted('set_comm_link', link='rs485')
        self.assertEqual(self.assertCompleted('get_comm_link')['active_link'], 'rs485')
        self.assertFailed('set_comm_link', link='wifi')
        self.assertFailed('set_comm_link')

    def test_passthrough_valves(self):
        info = self.assertCompleted('passthrough_valve_info', ['valves'])['valves']
        self.assertEqual(len(info), len(self.config['passthrough_valves']))
        states = self.assertCompleted('passthrough_valve_states', ['valve_states'])['valve_states']
        self.assertEqual(set(states), {str(v['input']) for v in self.config['passthrough_valves']})

        data = self.assertCompleted('set_passthrough_valve_state', ['id', 'state'], id='1', override='true')
        self.assertTrue(data['state']['override'])
        self.assertCompleted('set_passthrough_valve_state', id='1', override='false')
        self.assertFailed('set_passthrough_valve_state', id='1', override='maybe')
        self.assertFailed('set_passthrough_valve_state', id='99', override='true')
        self.assertFailed('set_passthrough_valve_state', id='abc', override='true')

    def test_passthrough_pressure_sensors(self):
        info = self.assertCompleted('passthrough_pressure_sensor_info', ['sensor_info'])['sensor_info']
        self.assertEqual(len(info), len(self.config['passthrough_pressure_sensors']))
        data = self.assertCompleted('passthrough_pressure_sensor_data', ['sensor_data'])['sensor_data']
        self.assertEqual(set(data), {str(s['input']) for s in self.config['passthrough_pressure_sensors']})

    def test_qdc_actuators(self):
        info = self.assertCompleted('qdc_actuator_info', ['qdc_actuator_info'])['qdc_actuator_info']
        self.assertEqual(len(info), len(self.config['qdc_actuator']))
        self.assertCompleted('qdc_actuator_states', ['qdc_actuator_states'])

        self.assertCompleted('set_qdc_actuator_state', ['id', 'state'], id='1', state='released')
        self.assertEqual(self.assertCompleted('qdc_actuator_states')['qdc_actuator_states']['1'], 'released')
        self.assertCompleted('set_qdc_actuator_state', id='1', state='locked')
        self.assertFailed('set_qdc_actuator_state', id='99', state='locked')
        self.assertFailed('set_qdc_actuator_state', id='1')

    # ---------------------------------------------------------------- flight computer: info

    def test_fc_info(self):
        fc_cfg = self.config['flight_computer']
        for command, cfg_key in [('adc_sensor_info', 'adc_sensors'), ('valve_info', 'valves'),
                                 ('servo_info', 'servos'), ('mode_info', 'modes'),
                                 ('custom_command_info', 'custom_commands')]:
            with self.subTest(command=command):
                data = self.assertCompleted(command, [command])
                self.assertEqual(len(data[command]), len(fc_cfg[cfg_key]))

    # ---------------------------------------------------------------- flight computer: state

    def test_fc_state_getters_before_any_packets(self):
        for command in ['adc_sensor_data', 'valve_states', 'servo_states', 'mode', 'sleep',
                        'comm_link', 'time_since_start', 'is_ready', 'command_status']:
            with self.subTest(command=command):
                self.assertCompleted(command, [command])

    def test_fc_state_getters_after_packets(self):
        # ADC packet index 1: sensors [1, 2] (from config), 3-byte signed little-endian values
        self.fc.process_packet(MAGIC_NUM + bytearray([0x03, 0x01])
                               + (1234).to_bytes(3, BYTEORDER, signed=True)
                               + (-56).to_bytes(3, BYTEORDER, signed=True))
        # State packet: valve 1 open, valve 2 closed; servos 100, 200, 300
        self.fc.process_packet(bytearray([0x04, 0b01])
                               + (100).to_bytes(2, BYTEORDER) + (200).to_bytes(2, BYTEORDER)
                               + (300).to_bytes(2, BYTEORDER))
        # Comm packet: ping 7, mode 1, uptime 5000 ms, cmd id 3, status 0x02, 0 messages
        self.fc.process_packet(bytearray([0x05]) + (7).to_bytes(2, BYTEORDER) + bytes([1])
                               + (5000).to_bytes(4, BYTEORDER) + (3).to_bytes(2, BYTEORDER)
                               + bytes([0x02, 0x00]))

        adc = self.assertCompleted('adc_sensor_data')['adc_sensor_data']
        self.assertEqual(adc['1'], 1234)
        self.assertEqual(adc['2'], -56)
        self.assertEqual(self.assertCompleted('valve_states')['valve_states'], {'1': 1, '2': 0})
        self.assertEqual(self.assertCompleted('servo_states')['servo_states'], {'1': 100, '2': 200, '3': 300})
        self.assertEqual(self.assertCompleted('mode')['mode'], 1)
        self.assertEqual(self.assertCompleted('time_since_start')['time_since_start'], 5000)
        status = self.assertCompleted('command_status')['command_status']
        self.assertEqual(status['status_id'], 0x02)
        self.assertEqual(status['status_name'], 'completed successfully')

    # ---------------------------------------------------------------- flight computer: commands

    # (command, hub args, expected response, args the handler should hand to _set_next_command)
    FC_COMMANDS = [
        ('set_valve', {'id': '1', 'state': '1'}, {'id': 1, 'state': 1}, [1, 1]),
        ('pulse_valve', {'id': '1', 'duration_ms': '500'}, {'id': 1, 'duration_ms': 500}, [1, 500]),
        ('set_servo', {'id': '2', 'value': '90'}, {'id': 2, 'value': 90}, [2, 90]),
        ('pulse_servo', {'id': '2', 'value': '90', 'duration_ms': '500'},
         {'id': 2, 'value': 90, 'duration_ms': 500}, [2, 90, 500]),
        ('set_mode', {'new_mode': '1'}, {'new_mode': 1}, [1]),
        ('set_fc_comm_link', {'new_link': '1'}, {'new_link': 1}, [1]),
        ('set_sleep', {'value': 'true'}, {'value': 'true'}, []),
        ('send_custom_command', {'id': '2', 'args': '1,2,3'}, {'id': 2, 'args': [1, 2, 3]}, [1, 2, 3]),
        ('restart', {}, {'restart_requested': True}, []),
    ]

    def test_fc_commands_parse_args_and_respond(self):
        # _set_next_command has a known bug (see test_fc_command_is_actually_queued), so record
        # its calls instead: this checks the handlers themselves, not the queueing logic.
        for name, args, expected, queued_args in self.FC_COMMANDS:
            with self.subTest(command=name), \
                 mock.patch.object(self.fc, '_set_next_command') as set_next:
                data = self.assertCompleted(name, expected.keys(), **args)
                self.assertEqual(data, expected)
                set_next.assert_called_once()
                self.assertEqual(set_next.call_args.args[2], queued_args)

    def test_fc_commands_reject_bad_args(self):
        bad = [
            ('set_valve', {'id': 'abc', 'state': '1'}),
            ('set_valve', {'id': '1'}),
            ('pulse_valve', {'id': '1'}),
            ('set_servo', {'id': '2', 'value': '90.5'}),
            ('pulse_servo', {'id': '2', 'value': '90'}),
            ('set_mode', {}),
            ('set_fc_comm_link', {'new_link': 'radio'}),
            ('set_sleep', {'value': 'yes'}),
            ('send_custom_command', {'id': '2', 'args': '1,x'}),
        ]
        for name, args in bad:
            with self.subTest(command=name, args=args), \
                 mock.patch.object(self.fc, '_set_next_command'):
                self.assertFailed(name, **args)

    def test_fc_command_is_actually_queued_and_sent(self):
        # Uses the REAL _set_next_command and build_comm_response, like the main loop does.
        self.assertCompleted('set_valve', id='1', state='1')
        self.assertEqual((self.fc._next_command_type, self.fc._next_command_tag, self.fc._next_command_args),
                         (0x00, 0x00, [1, 1]))

        uplink = self.fc.build_comm_response(ping_id=1)
        # magic(8) + type(1) + ping(2) + time(4) + valid(1) + cmd id(2) + type(1) + tag(1) + valve id(1) + state(1)
        self.assertEqual(uplink[15], 0x01, "command valid byte not set")
        self.assertEqual(list(uplink[18:22]), [0x00, 0x00, 1, 1])
        self.assertIsNone(self.fc._next_command_type, "command should be cleared after sending")


def _to_py(value):
    """Turn protobuf Struct/ListValue values into plain Python, with whole-number floats back to ints."""
    if isinstance(value, struct_pb2.Struct):
        return {k: _to_py(v) for k, v in value.items()}
    if isinstance(value, struct_pb2.ListValue):
        return [_to_py(v) for v in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


if __name__ == '__main__':
    unittest.main()
