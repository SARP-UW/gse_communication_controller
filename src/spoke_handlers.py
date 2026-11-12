"""Spoke command handlers for the CC node.

build_handlers() returns the command-name -> handler dict passed to Spoke('cc', ...).
Each handler takes the command's args (a dict of strings) and returns a dict
(sent back to the hub as `data`) or None. Raising means the command FAILED.
"""
from collections import deque
from typing import Callable, Dict

from src.controller import Controller
from src.flight_computer import FlightComputer
from src.radio import RADIO_MAX_PACKET_SIZE


def build_handlers(controller: Controller, flight_computer: FlightComputer,
                   received_for_hub: deque, to_transmit: deque) -> Dict[str, Callable]:
    """
    Builds the Spoke command dict.

    Args:
        controller: The running Controller.
        flight_computer: The running FlightComputer.
        received_for_hub: Packets received by the main loop, drained by receive_packets.
        to_transmit: Packets queued by transmit_packets, sent by the main loop.
    """

    ########################### controller.py handlers ###########################

    def receive_packets(args):
        packets = []
        while received_for_hub:
            packets.append(received_for_hub.popleft().hex())
        return {'packets': packets, 'count': len(packets)}

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

    ########################### flight_computer.py handlers ###########################

    def adc_sensor_info(args):
        return {'adc_sensor_info' : flight_computer.adc_sensor_info}

    def valve_info(args):
        return {'valve_info' : flight_computer.valve_info}

    def servo_info(args):
        return {'servo_info' : flight_computer.servo_info}

    def mode_info(args):
        return {'mode_info' : flight_computer.mode_info}

    def custom_command_info(args):
        return {'custom_command_info' : flight_computer.custom_command_info}

    def adc_sensor_data(args):
        return {'adc_sensor_data' : {str(k) : v for k,v in flight_computer.adc_sensor_data.items()}}

    def valve_states(args):
        return {'valve_states' : {str(k) : v for k,v in flight_computer.valve_states.items()}}

    def servo_states(args):
        return {'servo_states' : {str(k) : v for k,v in flight_computer.servo_states.items()}}

    def mode(args):
        return {'mode' : flight_computer.mode}

    def sleep(args):
        return {'sleep' : flight_computer.sleep}

    def comm_link(args):
        return {'comm_link' : flight_computer.comm_link}

    def time_since_start(args):
        return {'time_since_start' : flight_computer.time_since_start}

    def is_ready(args):
        return {'is_ready' : flight_computer.is_ready}

    def command_status(args):
        return {'command_status' : flight_computer.command_status}

    def set_valve(args):
        valve_id = int(args['id'])
        state = int(args['state'])
        flight_computer.set_valve(valve_id, state)
        return {'id' : valve_id, 'state' : state}

    def pulse_valve(args):
        pulse_id = int(args['id'])
        duration = int(args['duration_ms'])
        flight_computer.pulse_valve(pulse_id, duration)
        return {'id' : pulse_id, 'duration_ms' : duration}

    def set_servo(args):
        servo_id = int(args['id'])
        value = int(args['value'])
        flight_computer.set_servo(servo_id, value)
        return {'id' : servo_id, 'value' : value}

    def pulse_servo(args):
        servo_id = int(args['id'])
        value = int(args['value'])
        duration = int(args['duration_ms'])
        flight_computer.pulse_servo(servo_id, value, duration)
        return {'id' : servo_id, 'value' : value, 'duration_ms' : duration}

    def restart(args):
        flight_computer.restart()
        return {"restart_requested" : True}

    def set_mode(args):
        new_mode = int(args['new_mode'])
        flight_computer.mode = new_mode
        return {'new_mode' : new_mode}

    def set_fc_comm_link(args):
        new_link = int(args['new_link'])
        flight_computer.comm_link = new_link
        return {'new_link' : new_link}

    def set_sleep(args):
        value = args['value'].strip().lower()
        if value not in ('true', 'false'):
            raise ValueError('value not true or false')
        if (value == 'true'):
            flight_computer.sleep = True
        else :
            flight_computer.sleep = False
        return {'value' : value}

    def send_custom_command(args):
        command_id = int(args['id'])
        command_args = [int(x) for x in args['args'].split(',')]
        flight_computer.send_custom_command(command_id, command_args)
        return {'id' : command_id, 'args' : command_args}

    ########################### ########################### ###########################

    return {
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
        "adc_sensor_info" : adc_sensor_info,
        "valve_info" : valve_info,
        "servo_info" : servo_info,
        "mode_info" : mode_info,
        "custom_command_info" : custom_command_info,
        "adc_sensor_data" : adc_sensor_data,
        "valve_states" : valve_states,
        "servo_states" : servo_states,
        "mode" : mode,
        "sleep" : sleep,
        "comm_link" : comm_link,
        "time_since_start" : time_since_start,
        "is_ready" : is_ready,
        "command_status" : command_status,
        "set_valve" : set_valve,
        "pulse_valve" : pulse_valve,
        "set_servo" : set_servo,
        "pulse_servo" : pulse_servo,
        "restart" : restart,
        "set_mode" : set_mode,
        "set_fc_comm_link" : set_fc_comm_link,
        "set_sleep" : set_sleep,
        "send_custom_command" : send_custom_command,
    }
