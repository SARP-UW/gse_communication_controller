"""Call every CC spoke command through the hub's REST API and report the results.

Needs the hub and a CC spoke running (see tests/run_mock_spoke.py):

    pipenv run python -m tests.hub_smoke [--url http://localhost:8000] [--node cc]

Exit code is 0 when every command returns the expected status; FC command handlers
that fail only because of the known _set_next_command bug are reported as KNOWN.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

# (command, args, expected status)
COMMANDS = [
    # controller
    ('receive_packets', {}, 'completed'),
    ('transmit_packets', {'packets': '0a0b,ff01'}, 'completed'),
    ('get_comm_link', {}, 'completed'),
    ('set_comm_link', {'link': 'radio'}, 'completed'),
    ('set_comm_link', {'link': 'rs485'}, 'completed'),
    ('passthrough_valve_info', {}, 'completed'),
    ('passthrough_valve_states', {}, 'completed'),
    ('set_passthrough_valve_state', {'id': '1', 'override': 'true'}, 'completed'),
    ('set_passthrough_valve_state', {'id': '1', 'override': 'false'}, 'completed'),
    ('passthrough_pressure_sensor_info', {}, 'completed'),
    ('passthrough_pressure_sensor_data', {}, 'completed'),
    ('qdc_actuator_info', {}, 'completed'),
    ('qdc_actuator_states', {}, 'completed'),
    ('set_qdc_actuator_state', {'id': '1', 'state': 'released'}, 'completed'),
    ('set_qdc_actuator_state', {'id': '1', 'state': 'locked'}, 'completed'),
    # flight computer: info
    ('adc_sensor_info', {}, 'completed'),
    ('valve_info', {}, 'completed'),
    ('servo_info', {}, 'completed'),
    ('mode_info', {}, 'completed'),
    ('custom_command_info', {}, 'completed'),
    # flight computer: state
    ('adc_sensor_data', {}, 'completed'),
    ('valve_states', {}, 'completed'),
    ('servo_states', {}, 'completed'),
    ('mode', {}, 'completed'),
    ('sleep', {}, 'completed'),
    ('comm_link', {}, 'completed'),
    ('time_since_start', {}, 'completed'),
    ('is_ready', {}, 'completed'),
    ('command_status', {}, 'completed'),
    # flight computer: commands
    ('set_valve', {'id': '1', 'state': '1'}, 'completed'),
    ('pulse_valve', {'id': '1', 'duration_ms': '500'}, 'completed'),
    ('set_servo', {'id': '2', 'value': '90'}, 'completed'),
    ('pulse_servo', {'id': '2', 'value': '90', 'duration_ms': '500'}, 'completed'),
    ('set_mode', {'new_mode': '1'}, 'completed'),
    ('set_fc_comm_link', {'new_link': '1'}, 'completed'),
    ('set_sleep', {'value': 'true'}, 'completed'),
    ('send_custom_command', {'id': '2', 'args': '1,2,3'}, 'completed'),
    ('restart', {}, 'completed'),
    # bad args: must come back as failed, not crash the spoke
    ('set_valve', {'id': 'abc', 'state': '1'}, 'failed'),
    ('set_passthrough_valve_state', {'id': '99', 'override': 'true'}, 'failed'),
    ('transmit_packets', {'packets': 'zz'}, 'failed'),
    ('set_sleep', {'value': 'yes'}, 'failed'),
    ('not_a_command', {}, 'failed'),
]

FC_COMMANDS = {'set_valve', 'pulse_valve', 'set_servo', 'pulse_servo', 'set_mode',
               'set_fc_comm_link', 'set_sleep', 'send_custom_command', 'restart'}
KNOWN_BUG = "unsupported operand type(s) for +: 'NoneType' and 'int'"  # _set_next_command, pending fix


def request(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b'{}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://localhost:8000')
    parser.add_argument('--node', default='cc')
    opts = parser.parse_args()

    try:
        _, spokes = request(f'{opts.url}/spokes')
    except urllib.error.URLError as error:
        sys.exit(f"Can't reach the hub at {opts.url} ({error.reason}). Is `fastapi run api.py` running?")
    if opts.node not in spokes:
        sys.exit(f"Spoke {opts.node!r} is not connected (connected: {spokes}). Is tests/run_mock_spoke.py running?")
    print(f"Connected spokes: {spokes}\n")

    counts = {'PASS': 0, 'KNOWN': 0, 'FAIL': 0}
    for name, args, expected in COMMANDS:
        http_status, body = request(f'{opts.url}/spokes/{opts.node}/commands',
                                    {'command_name': name, 'args': args})
        status = body.get('status', f'HTTP {http_status}')
        detail = body.get('message') or json.dumps(body.get('data', body))

        if status == expected:
            result = 'PASS'
        elif name in FC_COMMANDS and expected == 'completed' and KNOWN_BUG in (body.get('message') or ''):
            result = 'KNOWN'
        else:
            result = 'FAIL'
        counts[result] += 1

        shown_args = ','.join(f'{k}={v}' for k, v in args.items()) or '-'
        print(f"{result:5}  {name:34} {shown_args:30} {status:10} {detail[:90]}")

    print(f"\n{counts['PASS']} passed, {counts['KNOWN']} known _set_next_command failures, {counts['FAIL']} failed")
    sys.exit(1 if counts['FAIL'] else 0)


if __name__ == '__main__':
    main()
