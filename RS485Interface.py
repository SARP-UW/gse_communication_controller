
"""
RS485 UART interface with:
UART configuration using pyserial
GPIO control of DE and RE for TX and RX
Framed messages with CRC16
Background receive thread
"""

import threading
import queue
import time
import struct
import sys

import serial
try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None
    print("WARNING: RPi.GPIO not available; GPIO control will not work.", file=sys.stderr)


def crc16_modbus(data: bytes) -> int:
    """
    Compute CRC16 Modbus
    Polynomial 0xA001, initial 0xFFFF
    Returns 16 bit integer
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class RS485Interface:
    """
    UART RS485 interface with GPIO DE and RE direction control

    Frame format
    0x7E start byte
    Length byte
    Payload
    CRC16 little endian
    """

    START_BYTE = 0x7E

    def __init__(
        self,
        port="/dev/ttyAMA0",
        baudrate=115200,
        de_pin=18,
        re_pin=None,
        gpio_mode=None,
        serial_timeout=0.05
    ):
        """
        Initialize UART and GPIO
        """
        self.port_name = port
        self.baudrate = baudrate
        self.de_pin = de_pin
        self.re_pin = re_pin if re_pin is not None else de_pin
        self.serial_timeout = serial_timeout

        if GPIO is None:
            raise RuntimeError("RPi.GPIO is required for DE and RE control")

        if gpio_mode is None:
            gpio_mode = GPIO.BCM
        GPIO.setmode(gpio_mode)
        GPIO.setwarnings(False)
        GPIO.setup(self.de_pin, GPIO.OUT)
        GPIO.setup(self.re_pin, GPIO.OUT)

        self._set_receive_mode()

        self.ser = serial.Serial(
            port=self.port_name,
            baudrate=self.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.serial_timeout
        )

        self._rx_thread = None
        self._running = threading.Event()
        self._rx_queue = queue.Queue()
        self._lock = threading.Lock()

        self._running.set()
        self._rx_thread = threading.Thread(
            target=self._receiver_loop,
            daemon=True
        )
        self._rx_thread.start()

    def _set_transmit_mode(self):
        GPIO.output(self.de_pin, GPIO.HIGH)
        GPIO.output(self.re_pin, GPIO.HIGH)
        time.sleep(0.001)

    def _set_receive_mode(self):
        GPIO.output(self.de_pin, GPIO.LOW)
        GPIO.output(self.re_pin, GPIO.LOW)
        time.sleep(0.001)

    def _build_frame(self, payload: bytes) -> bytes:
        if len(payload) > 255:
            raise ValueError("Payload too long")

        length_byte = len(payload).to_bytes(1, "big")
        body = length_byte + payload
        crc_value = crc16_modbus(body)
        crc_bytes = struct.pack("<H", crc_value)
        return bytes([self.START_BYTE]) + body + crc_bytes

    def _parse_frame(self, raw: bytes) -> bytes | None:
        if len(raw) < 3:
            return None

        length = raw[0]
        expected = 1 + length + 2
        if len(raw) != expected:
            return None

        body = raw[: 1 + length]
        crc_recv = struct.unpack("<H", raw[-2:])[0]
        crc_calc = crc16_modbus(body)

        if crc_recv != crc_calc:
            return None

        return body[1:]

    def send(self, payload: bytes) -> None:
        frame = self._build_frame(payload)
        with self._lock:
            self._set_transmit_mode()
            self.ser.write(frame)
            self.ser.flush()
            time.sleep(len(frame) * 10 / self.baudrate)
            self._set_receive_mode()

    def read_frame(self, timeout=None):
        try:
            return self._rx_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _receiver_loop(self):
        buffer = bytearray()
        while self._running.is_set():
            try:
                data = self.ser.read(64)
                if not data:
                    continue

                buffer.extend(data)

                while True:
                    idx = buffer.find(bytes([self.START_BYTE]))
                    if idx == -1:
                        buffer.clear()
                        break

                    if idx > 0:
                        del buffer[:idx]

                    if len(buffer) < 1 + 1 + 2:
                        break

                    length = buffer[1]
                    needed = 1 + 1 + length + 2

                    if len(buffer) < needed:
                        break

                    raw = bytes(buffer[1:needed])
                    payload = self._parse_frame(raw)
                    del buffer[:needed]

                    if payload is not None:
                        self._rx_queue.put(payload)
                    else:
                        continue

            except Exception as e:
                print("RS485 RX thread error", e)
                time.sleep(0.1)

    def close(self):
        self._running.clear()
        if self._rx_thread:
            self._rx_thread.join(1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()
        if GPIO is not None:
            GPIO.cleanup((self.de_pin, self.re_pin))


def main():
        rs = RS485Interface(
            port="/dev/ttyAMA0",
            baudrate=115200,
            de_pin=18,
            re_pin=23
        )

        try:
            i = 0
            while True:
                payload = f"Hello {i}".encode()
                print("TX", payload)
                rs.send(payload)

                rx = rs.read_frame(timeout=1.0)
                if rx is not None:
                    print("RX", rx)

                i += 1
                time.sleep(2)

        except KeyboardInterrupt:
            print("Exiting")
        finally:
            rs.close()


if __name__ == "__main__":
    main()
