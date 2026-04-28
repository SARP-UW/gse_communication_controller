/* =============================================================================
   config.js is SARP Launch Controller
   Hardware configuration: valves, servos, sensors, commands, FC modes.
   This is the file to edit when adding/removing hardware or commands.
============================================================================= */

/* -----------------------------------------------------------------------------
   VALVES
   Add a new object to this array for each valve on the rocket.
   id:   unique number
   name: display name shown in the UI
----------------------------------------------------------------------------- */
const VALVES = [
  { id: 1, name: 'Main Valve' },
  // Example: { id: 2, name: 'Vent Valve' },
];

/* -----------------------------------------------------------------------------
   SERVOS
   One entry per servo. Mode must be: 'angle', 'speed', or 'linear'.
   min/max/step: input constraints
   defaultVal:   starting value shown in UI
   unit:         display unit label
----------------------------------------------------------------------------- */
const SERVOS = [
  { id: 1, name: 'Servo 1', mode: 'angle',  unit: '°',   min: 0, max: 180,  step: 1,  defaultVal: 90 },
  { id: 2, name: 'Servo 2', mode: 'speed',  unit: 'RPM', min: 0, max: 5000, step: 10, defaultVal: 0  },
  { id: 3, name: 'Servo 3', mode: 'linear', unit: '%',   min: 0, max: 100,  step: 1,  defaultVal: 0  },
];

/* -----------------------------------------------------------------------------
   SENSORS
   One entry per sensor. Type must be: 'pressure', 'temperature', or 'force'.
   color: hex color used for the SmoothieChart line
   sim:   simulation settings (base value, random range, rate scale)
          — backend team: ignore sim block, it's only for the placeholder data
----------------------------------------------------------------------------- */
const SENSORS = [
  {
    id: 1, name: 'Main Pressure Sensor', type: 'pressure',
    unit: 'PSI', rateUnit: 'PSI/s', color: '#00aaff',
    sim: { base: 400, range: 80 },
  },
  {
    id: 2, name: 'Temperature Sensor', type: 'temperature',
    unit: '°C', rateUnit: '°C/s', color: '#ffaa00',
    sim: { base: 25, range: 10 },
  },
  {
    id: 3, name: 'Force Sensor', type: 'force',
    unit: 'N', rateUnit: 'N/s', color: '#00e5ff',
    sim: { base: 500, range: 200 },
  },
];

/* -----------------------------------------------------------------------------
   FLIGHT COMPUTER MODES
   name:   the mode identifier sent to the backend
   danger: if true, the button gets a red/danger style
           and is blocked when Safe Mode is ON
----------------------------------------------------------------------------- */
const FC_MODES = [
  { name: 'WAKE',     danger: false },
  { name: 'SLEEP',    danger: false },
  { name: 'ARMED',    danger: false },
  { name: 'SHUTDOWN', danger: true  },
];

/* -----------------------------------------------------------------------------
   COMMANDS
   name: command identifier sent to the backend
   desc: short description shown under the command name
   args: array of numerical arguments the command accepts
         - name:    internal key used when sending to backend
         - label:   display label in the UI
         - unit:    unit shown next to the input
         - default: pre-filled value in the input
----------------------------------------------------------------------------- */
const COMMANDS = [
  {
    name: 'ARM_ENGINE',
    desc: 'Arm the ignition system',
    args: [],
  },
  {
    name: 'FIRE_IGNITER',
    desc: 'Send ignition signal to engine',
    args: [
      { name: 'delay',    label: 'Delay',    unit: 's',  default: 0   },
      { name: 'duration', label: 'Duration', unit: 'ms', default: 500 },
    ],
  },
  {
    name: 'VENT_PRESSURE',
    desc: 'Open vent valve to relieve pressure',
    args: [
      { name: 'target', label: 'Target PSI', unit: 'PSI', default: 50 },
    ],
  },
  {
    name: 'SET_ABORT_THRESHOLD',
    desc: 'Set max pressure/temp before auto-abort',
    args: [
      { name: 'pressure', label: 'Pressure', unit: 'PSI', default: 800 },
      { name: 'temp',     label: 'Temp',     unit: '°C',  default: 150 },
    ],
  },
  {
    name: 'PING',
    desc: 'Request a status ping from the flight computer',
    args: [],
  },
];
