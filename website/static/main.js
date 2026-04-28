/* =============================================================================
   main.js — SARP Launch Controller
   All application logic: state, Socket.IO connection, rendering, interactions.
============================================================================= */


/* =============================================================================
   CONNECTION CONFIG
   Change these if the backend runs on a different host or port.
============================================================================= */
const BACKEND_URL    = 'http://localhost:8080';  // Socket.IO + HTTP base URL
const TELEMETRY_HZ   = 20;                        // How many packets/sec to request
const HEARTBEAT_MS   = 3000;                      // How often to ping /api/send_heartbeat


/* =============================================================================
   APPLICATION STATE
============================================================================= */
const STATE = {
  safeMode:         true,    // Whether safe mode is active
  commMode:         'radio', // 'radio' | 'wired'
  fcMode:           'WAKE',  // Current flight computer mode string
  backendConnected: false,   // Is the backend socket connected?
  fcConnected:      false,   // Is the flight computer reachable?
  altitude:         0,       // Current altitude in metres
  altitudeMax:      3000,    // Max altitude for the fill bar scale
  simulating:       false,   // True while running simulated data (starts false, set by startSimulation)
};


/* =============================================================================
   SOCKET.IO CONNECTION
   ─────────────────────────────────────────────────────────────────────────────
   Connects to the Flask-SocketIO backend, starts the telemetry stream,
   and wires up all incoming event handlers.
============================================================================= */
let socket = null;

function connectSocket() {
  // io() is provided by the Socket.IO client library loaded in index.html
  socket = io(BACKEND_URL, {
    reconnection:        true,
    reconnectionDelay:   1000,
    reconnectionAttempts: Infinity,
  });

  // ── Connection lifecycle ──────────────────────────────────────────────────

  socket.on('connect', () => {
    console.log('[SOCKET] Connected');
    setBackendConnected(true);
    stopSimulation();

    // Ask the backend to start streaming telemetry at our desired rate
    socket.emit('telemetry/start', { sample_hz: TELEMETRY_HZ });
    addNotification('info', `Socket connected — requesting ${TELEMETRY_HZ}Hz telemetry`);
  });

  socket.on('disconnect', (reason) => {
    console.log('[SOCKET] Disconnected:', reason);
    setBackendConnected(false);
    updateConnectionStatus(false, false);
    startSimulation(); // fall back to simulated data so UI isn't dead
    addNotification('error', `Socket disconnected: ${reason}`);
  });

  socket.on('connect_error', (err) => {
    console.warn('[SOCKET] Connection error:', err.message);
    setBackendConnected(false);
  });

  // ── Telemetry packets (main data stream) ─────────────────────────────────
  //
  // The backend emits "telemetry" at TELEMETRY_HZ every cycle.
  // Packet shape (from website.py build_telemetry_payload):
  // {
  //   ts_ms: number,
  //   seq:   number,
  //   fc: {
  //     time_since_start_ms: number,
  //     mode:                string,
  //     sleep:               boolean,
  //     is_ready:            boolean,
  //     adc:                 object,   ← sensor readings, format TBD (see TODO below)
  //     valves:              object,   ← { "1": <state>, ... }
  //     servos:              object,   ← { "1": <value>, ... }
  //     command_status:      any,      ← format TBD (see TODO below)
  //   },
  //   api: {
  //     connected_clients: number,
  //     sample_hz:         number,
  //     streaming:         boolean,
  //     uptime_ms:         number,
  //   }
  // }

  socket.on('telemetry', (packet) => {
    handleTelemetryPacket(packet);
  });

  // ── Backend events (action lifecycle + state changes) ─────────────────────
  //
  // The backend emits "event" for things like commands starting/completing/failing
  // and state changes (client count, streaming status, etc.)

  socket.on('event', (evt) => {
    handleBackendEvent(evt);
  });

  // ── Status messages ───────────────────────────────────────────────────────
  //
  // One-off responses to our socket emits (e.g. telemetry/start confirmation)

  socket.on('status', (data) => {
    if (!data.ok) {
      console.warn('[STATUS] Error from backend:', data.error);
      addNotification('error', `Backend: ${data.error}`);
    }
  });
}


/* =============================================================================
   TELEMETRY PACKET HANDLER
   Called on every incoming telemetry packet from the backend.
============================================================================= */
function handleTelemetryPacket(packet) {
  const fc  = packet.fc;
  const api = packet.api;

  if (!fc) return;

  // ── Flight computer connection ────────────────────────────────────────────
  updateConnectionStatus(true, fc.is_ready);

  // ── Mission elapsed time (fc.time_since_start_ms) ────────────────────────
  if (fc.time_since_start_ms !== undefined) {
    document.getElementById('mission-time').textContent =
      formatDuration(fc.time_since_start_ms);
  }

  // ── Sleep state (fc.sleep) ────────────────────────────────────────────────
  if (fc.sleep !== undefined) {
    const sleepEl = document.getElementById('fc-sleep-value');
    sleepEl.textContent = fc.sleep ? 'ON' : 'OFF';
    sleepEl.className   = fc.sleep ? 'sleep-on' : 'sleep-off';
  }

  // ── FC mode ───────────────────────────────────────────────────────────────
  // fc.mode from the backend is an integer (the FC stores modes as numbers).
  // We look it up in FC_MODES by id to get the display name.
  // If no match is found we show the raw value so nothing silently breaks.
  if (fc.mode !== undefined) {
    const modeEntry = FC_MODES.find(m => m.id === fc.mode);
    const modeName  = modeEntry ? modeEntry.name : String(fc.mode);
    if (modeName !== STATE.fcMode) {
      STATE.fcMode = modeName;
      document.getElementById('fc-mode-big').textContent   = modeName;
      document.getElementById('fc-mode-value').textContent = modeName;
      renderFcModeButtons();
    }
  }

  // ── Valve states ──────────────────────────────────────────────────────────
  if (fc.valves) {
    Object.entries(fc.valves).forEach(([id, state]) => {
      updateValveStatus(parseInt(id), state);
    });
  }

  // ── Servo states ──────────────────────────────────────────────────────────
  if (fc.servos) {
    Object.entries(fc.servos).forEach(([id, value]) => {
      updateServoDisplay(parseInt(id), value);
    });
  }

  // ── Sensor readings (ADC) ─────────────────────────────────────────────────
  // Format confirmed: { "1": 390.7, "2": 24.5 } — key = sensor ID, value = float
  // Rate is calculated by comparing to the previous reading * sample rate.
  if (fc.adc) {
    Object.entries(fc.adc).forEach(([id, value]) => {
      const sensorId = parseInt(id);
      const prev     = sensorValues[sensorId] ? sensorValues[sensorId].val : value;
      const rate     = (value - prev) * TELEMETRY_HZ;
      if (sensorValues[sensorId]) sensorValues[sensorId].val = value;
      updateSensorReading(sensorId, value, rate);
    });
  }

  // ── Command status ────────────────────────────────────────────────────────
  // Format confirmed: single byte 0x00-0x0A (see COMMAND_STATUS table below)
  if (fc.command_status !== undefined && fc.command_status !== null) {
    handleCommandStatus(fc.command_status);
  }

  // ── API / system status ───────────────────────────────────────────────────
  if (api) {
    // Backend uptime
    if (api.uptime_ms !== undefined) {
      document.getElementById('sys-uptime').textContent =
        formatDuration(api.uptime_ms);
    }

    // Connected client count
    if (api.connected_clients !== undefined) {
      document.getElementById('sys-clients').textContent = api.connected_clients;
    }

    // Streaming state
    if (api.streaming !== undefined) {
      const streamEl = document.getElementById('sys-streaming');
      streamEl.textContent = api.streaming ? 'ON' : 'OFF';
      streamEl.className   = 'sys-stat-value ' + (api.streaming ? 'streaming-on' : 'streaming-off');
    }

    // Sample rate
    if (api.sample_hz !== undefined) {
      document.getElementById('sys-hz').textContent =
        api.sample_hz > 0 ? `${api.sample_hz} Hz` : '-- Hz';
    }
  }
}


/* =============================================================================
   BACKEND EVENT HANDLER
   Handles the "event" socket messages for action lifecycle and state changes.
============================================================================= */
function handleBackendEvent(evt) {
  console.log('[EVENT]', evt.type, evt);

  switch (evt.type) {

    case 'action_started':
      // A command was accepted and is now running on the FC
      setExecutingCommand(evt.command_type || evt.command?.type || 'unknown');
      break;

    case 'action_completed':
      // Command finished successfully
      setExecutingCommand(null);
      addNotification('info', `Command completed: ${evt.command_type}`);
      break;

    case 'action_failed': {
      // Command failed — show the error
      setExecutingCommand(null);
      addNotification('error', `Command failed: ${evt.command_type} — ${evt.reason}`);
      // Highlight the matching command card in red if we can find it
      // Matches on socketType (the backend command type key) defined in config.js
      const failedCmd = COMMANDS.findIndex(c => c.socketType === evt.command_type);
      if (failedCmd >= 0) {
        const item  = document.getElementById(`cmd-${failedCmd}`);
        const errEl = document.getElementById(`cmd-err-${failedCmd}`);
        if (item && errEl) {
          item.classList.add('error');
          errEl.textContent = `ERR: ${evt.reason}`;
        }
      }
      break;
    }

    case 'command_accepted':
      // Backend acknowledged it received the command (before execution)
      addNotification('info', `Command accepted: ${evt.command_type} (action #${evt.action_id})`);
      break;

    case 'state_changed':
      // Something about the backend's state changed (client count, streaming, etc.)
      console.log('[STATE CHANGED]', evt);
      break;
  }
}


/* =============================================================================
   HEARTBEAT
   ─────────────────────────────────────────────────────────────────────────────
   The backend tracks connected users via GET /api/send_heartbeat.
   We call this on a timer so the backend knows the browser tab is still alive.
   The backend will mark us as disconnected if it stops receiving these.
============================================================================= */
function startHeartbeat() {
  // Send one immediately, then repeat on the interval
  sendHeartbeat();
  setInterval(sendHeartbeat, HEARTBEAT_MS);
}

async function sendHeartbeat() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/send_heartbeat`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // Heartbeat succeeded — backend is reachable
    // Note: this doesn't mean the FC is connected, only the backend server
  } catch (err) {
    console.warn('[HEARTBEAT] Failed:', err.message);
    // Don't update connection dots here — the socket disconnect handler does that
  }
}


/* =============================================================================
   CONNECTION STATUS UI
============================================================================= */

function setBackendConnected(connected) {
  STATE.backendConnected = connected;
  const dot = document.getElementById('backend-dot');
  dot.className = 'conn-dot ' + (connected ? 'connected' : 'disconnected');
}

/**
 * Update both connection indicator dots.
 * Called from the telemetry handler every packet.
 * @param {boolean} backendOk
 * @param {boolean} fcOk
 */
function updateConnectionStatus(backendOk, fcOk) {
  STATE.backendConnected = backendOk;
  STATE.fcConnected      = fcOk;
  document.getElementById('backend-dot').className = 'conn-dot ' + (backendOk ? 'connected' : 'disconnected');
  document.getElementById('fc-dot').className      = 'conn-dot ' + (fcOk      ? 'connected' : 'disconnected');
}


/* =============================================================================
   COMMAND SENDING
   ─────────────────────────────────────────────────────────────────────────────
   Commands go via socket.emit('command', { type, ...params })
   based on what we read in website.py's command_map.
   These are wired up but the backend API is still being built this week —
   they will work as soon as the backend is ready.
============================================================================= */

/**
 * Emit a command over the socket.
 * All specific send functions below call this.
 * @param {Object} payload - Must include a "type" field
 */
function emitCommand(payload) {
  if (!socket || !socket.connected) {
    addNotification('error', 'Cannot send command — socket not connected');
    return;
  }
  console.log('[CMD EMIT]', payload);
  socket.emit('command', payload);
}

/**
 * Open or close a valve.
 * Backend command type: "set_valve"
 * @param {number} valveId - Valve ID from config.js
 * @param {string} action  - 'open' | 'close'
 * @param {number|null} duration - For pulse only, in seconds
 */
function sendValveCommand(valveId, action, duration = null) {
  if (action === 'pulse') {
    // Pulse valve: backend expects duration_ms
    emitCommand({
      type:        'pulse_valve',
      valve_id:    valveId,
      duration_ms: Math.round((duration || 1.0) * 1000),
    });
  } else {
    // Open = state 1, Close = state 0
    emitCommand({
      type:     'set_valve',
      valve_id: valveId,
      state:    action === 'open' ? 1 : 0,
    });
  }
}

/**
 * Move a servo to a position/speed/linear value.
 * Backend command type: "set_servo"
 * @param {number} servoId - Servo ID from config.js
 * @param {string} mode    - 'angle' | 'speed' | 'linear'
 * @param {number} value   - Target value
 */
function sendServoCommand(servoId, mode, value) {
  emitCommand({
    type:     'set_servo',
    servo_id: servoId,
    value:    value,
  });
}

/**
 * Send a custom/named flight command.
 * Backend command type: "custom_command"
 * @param {string} commandName - Command name (for UI display)
 * @param {number} commandId   - Numeric ID the FC understands
 * @param {number[]} args      - Array of integer arguments
 */
function sendFlightCommand(commandName, commandId, args) {
  emitCommand({
    type:       'custom_command',
    command_id: commandId,
    args:       args,
  });
}

/**
 * Set the flight computer's operating mode.
 * Backend command type: "set_mode"
 * @param {string} modeName - Display name (e.g. 'WAKE')
 * @param {number} modeId   - Numeric mode ID the FC understands
 */
function sendFcModeChange(modeName, modeId) {
  emitCommand({
    type: 'set_mode',
    mode: modeId,
  });
}

/**
 * Set flight computer sleep state.
 * Backend command type: "set_sleep"
 * @param {boolean} sleep
 */
function sendSleep(sleep) {
  emitCommand({
    type:  'set_sleep',
    sleep: sleep,
  });
}

/**
 * Change communication mode.
 * Backend command type: "set_comm_link"
 * Confirmed: 0 = RS485 (wired), 1 = radio
 * @param {string} mode - 'radio' | 'wired'
 */
function sendCommModeChange(mode) {
  emitCommand({
    type: 'set_comm_link',
    link: mode === 'radio' ? 1 : 0,
  });
}

/* =============================================================================
   COMMAND STATUS HANDLER
   Called every telemetry packet with fc.command_status (byte 0x00-0x0A).
   Updates the executing bar and fires notifications on state transitions.
============================================================================= */

const COMMAND_STATUS = {
  0x00: { label: 'WAITING',               type: 'idle'    },
  0x01: { label: 'IN PROGRESS',           type: 'running' },
  0x02: { label: 'COMPLETED',             type: 'success' },
  0x03: { label: 'FAILED — INVALID TAG',  type: 'error'   },
  0x04: { label: 'FAILED — INVALID ARGS', type: 'error'   },
  0x05: { label: 'FAILED — OUT OF RANGE', type: 'error'   },
  0x06: { label: 'FAILED — HARDWARE',     type: 'error'   },
  0x07: { label: 'FAILED — TIMEOUT',      type: 'error'   },
  0x08: { label: 'FAILED — SYSTEM STATE', type: 'error'   },
  0x09: { label: 'ABORTED BY FC',         type: 'error'   },
  0x0A: { label: 'AWAITING CONFIRM',      type: 'running' },
};

// Track previous status to avoid firing duplicate notifications every packet
let _lastCommandStatus = null;

function handleCommandStatus(statusByte) {
  const status = COMMAND_STATUS[statusByte];
  if (!status) return;

  // Only act on transitions
  if (statusByte === _lastCommandStatus) return;
  _lastCommandStatus = statusByte;

  switch (status.type) {
    case 'idle':
      setExecutingCommand(null);
      break;

    case 'running':
      // Bar was already set when command was sent
      // Just add a notification for the special awaiting confirm state
      if (statusByte === 0x0A) {
        addNotification('warning', 'Command awaiting confirmation from FC');
      }
      break;

    case 'success':
      setExecutingCommand(null);
      addNotification('info', 'Command completed successfully');
      break;

    case 'error':
      setExecutingCommand(null);
      addNotification('error', `Command failed: ${status.label}`);
      break;
  }
}


/* =============================================================================
   VALVE RENDERING & ACTIONS
============================================================================= */

function renderValves() {
  const container = document.getElementById('valves-container');
  container.innerHTML = '';

  VALVES.forEach(v => {
    const card = document.createElement('div');
    card.className = 'card valve-card';
    card.id = `valve-card-${v.id}`;
    card.innerHTML = `
      <div class="card-title">${v.name} <span class="tag">ID: ${v.id}</span></div>
      <div class="valve-status-bar">
        <div class="valve-status-dot closed" id="valve-dot-${v.id}"></div>
        <span class="valve-status-text closed" id="valve-status-${v.id}">CLOSED</span>
      </div>
      <div class="valve-buttons" id="valve-btns-${v.id}">
        <button class="btn-valve btn-open"         onclick="valveAction(${v.id}, 'open')">OPEN</button>
        <button class="btn-valve btn-close active"  onclick="valveAction(${v.id}, 'close')">CLOSE</button>
        <button class="btn-valve btn-pulse"         onclick="valvePulse(${v.id})">PULSE</button>
      </div>
      <div class="valve-pulse-row">
        <label>DURATION</label>
        <input type="number" id="valve-pulse-${v.id}" value="1.0" step="0.1" min="0.1" max="60" />
        <span class="unit">sec</span>
      </div>
    `;
    container.appendChild(card);
  });
}

function valveAction(id, action) {
  if (STATE.safeMode) { showSafeModal(); return; }
  updateValveStatus(id, action === 'open' ? 1 : 0);
  sendValveCommand(id, action);
}

function valvePulse(id) {
  if (STATE.safeMode) { showSafeModal(); return; }
  const duration = parseFloat(document.getElementById(`valve-pulse-${id}`).value) || 1.0;
  sendValveCommand(id, 'pulse', duration);

  // Visual flash for the pulse duration
  const dot = document.getElementById(`valve-dot-${id}`);
  dot.style.background = 'var(--accent-amber)';
  dot.style.boxShadow  = 'var(--glow-amber)';
  setTimeout(() => { dot.style.background = ''; dot.style.boxShadow = ''; }, duration * 1000);
}

/**
 * Update a valve card's status display.
 * Called both from user actions and from incoming telemetry.
 * @param {number} id    - Valve ID
 * @param {number} state - 1 = open, 0 = closed (matches backend int convention)
 */
function updateValveStatus(id, state) {
  const dot    = document.getElementById(`valve-dot-${id}`);
  const status = document.getElementById(`valve-status-${id}`);
  const btns   = document.querySelectorAll(`#valve-btns-${id} .btn-valve`);
  if (!dot || !status) return;

  const isOpen = state === 1 || state === 'open' || state === true;
  btns.forEach(b => b.classList.remove('active'));

  if (isOpen) {
    dot.className    = 'valve-status-dot open';
    status.className = 'valve-status-text open';
    status.textContent = 'OPEN';
    if (btns[0]) btns[0].classList.add('active');
  } else {
    dot.className    = 'valve-status-dot closed';
    status.className = 'valve-status-text closed';
    status.textContent = 'CLOSED';
    if (btns[1]) btns[1].classList.add('active');
  }
}


/* =============================================================================
   SERVO RENDERING & ACTIONS
============================================================================= */

function renderServos() {
  const container = document.getElementById('servos-container');
  container.innerHTML = '';

  SERVOS.forEach(s => {
    const badgeClass = { angle: 'badge-angle', speed: 'badge-speed', linear: 'badge-linear' }[s.mode];
    const isLinear   = s.mode === 'linear';

    const card = document.createElement('div');
    card.className = 'card servo-card';
    card.innerHTML = `
      <div class="card-title">${s.name} <span class="tag">ID: ${s.id}</span></div>
      <span class="servo-mode-badge ${badgeClass}">${s.mode}</span>
      <div class="servo-input-group">
        <div class="servo-value-display" id="servo-display-${s.id}">
          ${s.defaultVal}<span class="unit">${s.unit}</span>
        </div>
        ${isLinear
          ? `<input type="range" class="servo-slider" id="servo-input-${s.id}"
               min="${s.min}" max="${s.max}" step="${s.step}" value="${s.defaultVal}"
               oninput="servoInputChanged(${s.id}, this.value, '${s.unit}')" />`
          : `<input type="number" class="servo-number-input" id="servo-input-${s.id}"
               min="${s.min}" max="${s.max}" step="${s.step}" value="${s.defaultVal}"
               oninput="servoInputChanged(${s.id}, this.value, '${s.unit}')" />`
        }
        <div class="servo-range-labels">
          <span>${s.min}${s.unit}</span>
          <div class="range-line"></div>
          <span>${s.max}${s.unit}</span>
        </div>
        <button class="btn-send" id="servo-send-${s.id}"
          onclick="servoSend(${s.id}, '${s.mode}')">▶ SEND</button>
      </div>
    `;
    container.appendChild(card);
  });
}

/** Update the large value readout above the servo input. */
function servoInputChanged(id, value, unit) {
  document.getElementById(`servo-display-${id}`).innerHTML =
    `${parseFloat(value).toFixed(1)}<span class="unit">${unit}</span>`;
}

/**
 * Also used by telemetry handler to update servo display from live data.
 * Accepts either (id, value) from telemetry or (id, value, unit) from user input.
 */
function updateServoDisplay(id, value, unit) {
  const servo = SERVOS.find(s => s.id === id);
  const u = unit || (servo ? servo.unit : '');
  const displayEl = document.getElementById(`servo-display-${id}`);
  if (displayEl) {
    displayEl.innerHTML = `${parseFloat(value).toFixed(1)}<span class="unit">${u}</span>`;
  }
  // Also keep the input in sync with live telemetry value
  const inputEl = document.getElementById(`servo-input-${id}`);
  if (inputEl) inputEl.value = value;
}

function servoSend(id, mode) {
  if (STATE.safeMode) { showSafeModal(); return; }
  const value = parseFloat(document.getElementById(`servo-input-${id}`).value);
  sendServoCommand(id, mode, value);

  const btn = document.getElementById(`servo-send-${id}`);
  btn.classList.add('sent');
  btn.textContent = '✓ SENT';
  setTimeout(() => { btn.classList.remove('sent'); btn.textContent = '▶ SEND'; }, 1200);
}


/* =============================================================================
   SENSOR RENDERING & SMOOTHIECHARTS
============================================================================= */
const sensorCharts = {};
const sensorSeries = {};
const sensorValues = {}; // tracks last value for simulation rate calculation

function renderSensors() {
  const container = document.getElementById('sensors-container');
  container.innerHTML = '';

  SENSORS.forEach(s => {
    sensorValues[s.id] = { val: 0 };

    const card = document.createElement('div');
    card.className = 'card sensor-card';
    card.innerHTML = `
      <div class="card-title">${s.name} <span class="tag">ID: ${s.id}</span></div>
      <div class="sensor-readings">
        <div class="reading-block">
          <div class="reading-label">VALUE</div>
          <div class="reading-value ${s.type}" id="sensor-val-${s.id}">
            0<span class="reading-unit">${s.unit}</span>
          </div>
        </div>
        <div class="reading-block">
          <div class="reading-label">RATE</div>
          <div class="reading-value rate-neg" id="sensor-rate-${s.id}">
            0.0<span class="reading-unit">${s.rateUnit}</span>
          </div>
        </div>
      </div>
      <div class="sensor-chart-wrap">
        <canvas id="chart-${s.id}" width="260" height="70"></canvas>
      </div>
    `;
    container.appendChild(card);
  });

  // Initialise a SmoothieChart for each sensor canvas.
  // Wrapped in try-catch so if SmoothieCharts fails to load from CDN,
  // the sensor cards still render with 0 values rather than crashing everything.
  SENSORS.forEach(s => {
    try {
      const chart = new SmoothieChart({
        millisPerPixel: 40,
        grid: {
          fillStyle:        'transparent',
          strokeStyle:      'rgba(255,255,255,0.04)',
          lineWidth:        1,
          millisPerLine:    3000,
          verticalSections: 3,
        },
        labels:   { disabled: true },
        minValue: 0,
      });

      const series = new TimeSeries();
      chart.addTimeSeries(series, {
        strokeStyle: s.color,
        fillStyle:   hexToRgba(s.color, 0.08),
        lineWidth:   2,
      });

      chart.streamTo(document.getElementById(`chart-${s.id}`), 500);
      sensorCharts[s.id] = chart;
      sensorSeries[s.id] = series;
    } catch (e) {
      console.error(`[SENSOR] Failed to init chart for sensor ${s.id}:`, e);
    }
  });
}

/**
 * Push a live reading into a sensor card and its chart.
 * Called by the telemetry handler (real) or simulation (fallback).
 */
function updateSensorReading(sensorId, value, rate) {
  if (!sensorSeries[sensorId]) return;
  const sensor = SENSORS.find(s => s.id === sensorId);
  if (!sensor) return;

  sensorSeries[sensorId].append(Date.now(), value);

  document.getElementById(`sensor-val-${sensorId}`).innerHTML =
    `${value.toFixed(1)}<span class="reading-unit">${sensor.unit}</span>`;

  const rateEl = document.getElementById(`sensor-rate-${sensorId}`);
  rateEl.innerHTML =
    `${rate >= 0 ? '+' : ''}${rate.toFixed(1)}<span class="reading-unit">${sensor.rateUnit}</span>`;
  rateEl.className = `reading-value ${rate >= 0 ? 'rate-pos' : 'rate-neg'}`;
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}


/* =============================================================================
   ALTITUDE DISPLAY
============================================================================= */
function updateAltitudeDisplay(metres) {
  STATE.altitude = metres;
  const pct = Math.min(100, (metres / STATE.altitudeMax) * 100);
  document.getElementById('alt-value').textContent = metres.toFixed(1);
  document.getElementById('alt-bar').style.width   = pct + '%';
  document.getElementById('baro-abs').textContent  = (101.3 - metres * 0.012).toFixed(1) + ' kPa';
  document.getElementById('baro-temp').textContent = (25 - metres * 0.0065).toFixed(1) + ' °C';
}


/* =============================================================================
   FLIGHT COMPUTER MODE
============================================================================= */
function renderFcModeButtons() {
  const container = document.getElementById('fc-mode-buttons');
  container.innerHTML = '';

  FC_MODES.forEach(m => {
    const btn = document.createElement('button');
    btn.className =
      'btn-mode' +
      (m.danger            ? ' danger' : '') +
      (STATE.fcMode === m.name ? ' active' : '');
    btn.textContent = m.name;
    btn.onclick = () => {
      if (STATE.safeMode && m.danger) { showSafeModal(); return; }
      applyFcMode(m.name, m.id);
    };
    container.appendChild(btn);
  });
}

function applyFcMode(name, id) {
  STATE.fcMode = name;
  document.getElementById('fc-mode-big').textContent   = name;
  document.getElementById('fc-mode-value').textContent = name;
  renderFcModeButtons();
  sendFcModeChange(name, id);
  addNotification('info', `FC mode set to ${name}`);
}


/* =============================================================================
   COMMUNICATION MODE
============================================================================= */
function setCommMode(mode) {
  STATE.commMode = mode;
  document.getElementById('comm-radio').classList.toggle('active', mode === 'radio');
  document.getElementById('comm-wired').classList.toggle('active', mode === 'wired');
  sendCommModeChange(mode);
  addNotification('info', `Comm mode: ${mode.toUpperCase()}`);
}


/* =============================================================================
   COMMAND INTERFACE
============================================================================= */
function renderCommands() {
  const list = document.getElementById('commands-list');
  list.innerHTML = '';

  COMMANDS.forEach((cmd, idx) => {
    const argsHtml = cmd.args.map(a => `
      <div class="cmd-arg-row">
        <label>${a.label}</label>
        <input type="number" id="cmd-${idx}-arg-${a.name}" value="${a.default}" step="any" />
        <span class="arg-unit">${a.unit}</span>
      </div>
    `).join('');

    const item = document.createElement('div');
    item.className = 'cmd-item';
    item.id = `cmd-${idx}`;
    item.innerHTML = `
      <div class="cmd-name">${cmd.name}</div>
      <div class="cmd-desc">${cmd.desc}</div>
      ${cmd.args.length ? `<div class="cmd-args">${argsHtml}</div>` : ''}
      <button class="btn-exec-cmd" id="cmd-btn-${idx}">▶ EXECUTE</button>
      <div class="cmd-error-msg" id="cmd-err-${idx}"></div>
    `;
    list.appendChild(item);

    // addEventListener instead of onclick attribute — avoids CSP blocking on
    // dynamically rendered elements in some browser/Live Server configurations
    document.getElementById(`cmd-btn-${idx}`).addEventListener('click', () => execCommand(idx));
  });
}

function execCommand(idx) {
  if (STATE.safeMode) { showSafeModal(); return; }

  // Check socket connection FIRST — if not connected, stop here.
  // The executing bar only updates when a command actually gets sent.
  // When connected, the backend's action_completed/action_failed events clear it.
  if (!socket || !socket.connected) {
    addNotification('error', 'Cannot execute — not connected to backend');
    return;
  }

  const cmd   = COMMANDS[idx];
  const item  = document.getElementById(`cmd-${idx}`);
  const errEl = document.getElementById(`cmd-err-${idx}`);

  // Clear any previous error state
  item.classList.remove('error');
  errEl.textContent = '';

  const args = cmd.args.map(a =>
    parseInt(document.getElementById(`cmd-${idx}-arg-${a.name}`).value)
  );

  // Build argument summary for the notification
  const argSummary = cmd.args.length
    ? ' (' + cmd.args.map(a =>
        `${a.label}: ${document.getElementById(`cmd-${idx}-arg-${a.name}`).value}${a.unit}`
      ).join(', ') + ')'
    : '';

  // Update executing bar and log to notifications
  setExecutingCommand(cmd.name);
  addNotification('info', `Executing: ${cmd.name}${argSummary}`);

  // Send the command — backend action_completed/action_failed will clear the bar
  sendFlightCommand(cmd.name, cmd.commandId, args);
}

function setExecutingCommand(name) {
  const nameEl  = document.getElementById('exec-cmd-name');
  const spinner = document.getElementById('exec-spinner');

  if (name) {
    nameEl.textContent     = name;
    nameEl.style.color     = 'var(--accent-amber)';
    nameEl.style.fontStyle = 'normal';
    spinner.classList.add('active');
  } else {
    nameEl.textContent     = 'none';
    nameEl.style.color     = 'var(--text-dim)';
    nameEl.style.fontStyle = 'italic';
    spinner.classList.remove('active');
  }
}


/* =============================================================================
   NOTIFICATIONS
============================================================================= */
function addNotification(priority, message) {
  const queue = document.getElementById('notif-queue');
  const icons = { info: '◉', warning: '▲', error: '✕' };
  const time  = new Date().toLocaleTimeString('en-US', { hour12: false });

  const item = document.createElement('div');
  item.className = `notif-item ${priority}`;
  item.innerHTML = `
    <div class="notif-icon">${icons[priority] || '◉'}</div>
    <div class="notif-content">
      <div class="notif-msg">${message}</div>
      <div class="notif-time">${time}</div>
    </div>
  `;

  queue.insertBefore(item, queue.firstChild);
  while (queue.children.length > 50) queue.removeChild(queue.lastChild);
}

function clearNotifications() {
  document.getElementById('notif-queue').innerHTML = '';
}


/* =============================================================================
   SAFE MODE
============================================================================= */
function toggleSafeMode() {
  STATE.safeMode = !STATE.safeMode;
  const btn = document.getElementById('safe-mode-btn');
  btn.textContent = `SAFE MODE: ${STATE.safeMode ? 'ON' : 'OFF'}`;
  btn.className   = STATE.safeMode ? 'on' : 'off';
  addNotification(STATE.safeMode ? 'warning' : 'info',
    `Safe Mode ${STATE.safeMode ? 'ENABLED' : 'DISABLED'}`);
}

function showSafeModal() { document.getElementById('safe-mode-modal').classList.add('show'); }
function closeSafeModal() { document.getElementById('safe-mode-modal').classList.remove('show'); }


/* =============================================================================
   CLOCK & TIME HELPERS
============================================================================= */
function updateClock() {
  document.getElementById('clock').textContent =
    new Date().toLocaleTimeString('en-US', { hour12: false });
}

/**
 * Convert a millisecond duration into HH:MM:SS string.
 * Used for mission elapsed time and backend uptime.
 * @param {number} ms
 * @returns {string}
 */
function formatDuration(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const hours   = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds]
    .map(v => String(v).padStart(2, '0'))
    .join(':');
}


/* =============================================================================
   SIMULATION (fallback when backend is not connected)
   ─────────────────────────────────────────────────────────────────────────────
   Keeps the UI looking alive during development.
   Automatically stops when the socket connects and resumes if it drops.
============================================================================= */
let _simIntervals = [];

function startSimulation() {
  if (!STATE.simulating) {
    STATE.simulating = true;
    _simIntervals.push(setInterval(simulateSensors,  500));
    _simIntervals.push(setInterval(simulateAltitude, 800));
    addNotification('warning', 'No backend — running simulated data');
  }
}

function stopSimulation() {
  STATE.simulating = false;
  _simIntervals.forEach(clearInterval);
  _simIntervals = [];
}

function simulateSensors() {
  SENSORS.forEach(s => {
    const prev   = sensorValues[s.id].val;
    const newVal = Math.max(0, s.sim.base + (Math.random() - 0.5) * s.sim.range);
    const rate   = (newVal - prev) * 2;
    sensorValues[s.id].val = newVal;
    updateSensorReading(s.id, newVal, rate);
  });
}

function simulateAltitude() {
  const next = Math.max(0, STATE.altitude + (Math.random() - 0.48) * 3);
  const rate = next - STATE.altitude;
  updateAltitudeDisplay(next);
  const rateEl = document.getElementById('baro-rate');
  rateEl.textContent = `${rate >= 0 ? '+' : ''}${rate.toFixed(2)} m/s`;
  rateEl.style.color  = rate >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
}


/* =============================================================================
   INITIALISATION
============================================================================= */
function init() {
  updateClock();
  setInterval(updateClock, 1000);

  // Render everything that doesn't depend on external libraries first
  renderValves();
  renderServos();
  renderFcModeButtons();
  renderCommands();

  // Start simulation before sensors so data is flowing even if charts fail
  startSimulation();

  // Seed mock notifications
  setTimeout(() => addNotification('info',    'UI ready — connecting to backend...'), 100);
  setTimeout(() => addNotification('warning', 'Pressure sensor 1 calibration pending'), 400);

  // Render sensors last — depends on SmoothieCharts CDN
  // If this fails internally, everything above is already running safely
  renderSensors();

  // Start heartbeat and socket connection
  startHeartbeat();
  connectSocket();
}

init();

