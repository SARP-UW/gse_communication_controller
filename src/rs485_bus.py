from . import settings
from threading import Thread, Lock, Condition
from select import select

# Hardware dependent libraries and initialization
if not settings.MOCK_MODE:
    from serial import Serial
    import board
    from digitalio import DigitalInOut, Direction
    
    # UART port for RS485 bus
    RS485_PORT = '/dev/ttyS0'

    # GPIO pin for RE control of RS485 transceiver
    RS485_DE_PIN = board.D5
    
    # GPIO pin for DE control of RS485 transceiver
    RS485_RE_PIN = board.D6

# RS485 bus argument bounds
RS485_MAX_BAUDRATE = 2000000 # Maximum supported baudrate for RS485 bus
RS485_MIN_BAUDRATE = 1200    # Minimum supported baudrate for RS485 bus
RS485_MAX_DATA_BITS = 9      # Maximum supported data bits for RS485 bus
RS485_MIN_DATA_BITS = 5      # Minimum supported data bits for RS485 bus
RS485_MAX_STOP_BITS = 2      # Maximum supported stop bits for RS485 bus
RS485_MIN_STOP_BITS = 1      # Minimum supported stop bits for RS485 bus

class RS485Bus:
    
    def _tx_thread(self) -> None:
        """
        Internal thread which transmits messages on the RS485 bus.
        """
        while not self._shutdown_flag:
            
            # Await data to send before next iteration (or shutdown)
            with self._tx_thread_condition:
                self._tx_thread_condition.wait_for(
                    lambda: (len(self._tx_queue) > 0) or self._shutdown_flag
                )

            # Check shutdown flag again to catch shutdown during wait_for
            if not self._shutdown_flag:
                if not settings.MOCK_MODE:
                    
                    # Extract data to send (prevent blocking with serial.write)
                    queue_data = bytearray()
                    with self._tx_queue_lock:
                        queue_data = self._tx_queue.copy()
                        self._tx_queue.clear()

                    # Enable DE (driver enable) then transmit data
                    if len(queue_data) > 0:
                        with self._tx_uart_lock:
                            self._de_io.value = True
                            self._serial.write(queue_data)
                            self._de_io.value = False
                
                # Simulate "sending" data by clearing TX queue
                else:
                    with self._tx_queue_lock:
                        self._tx_queue.clear()

    def _rx_thread(self) -> None:
        """
        Internal thread which receives messages from the RS485 bus using select().
        NOTE: "select" sleeps until data is available or timeout occurs
        """
        while not self._shutdown_flag:
            if not settings.MOCK_MODE:
                ready, _, _ = select([self._serial], [], [], 0.1)
                if ready:
                    data = self._serial.read(self._serial.in_waiting or 1)
                    if data:
                        with self._rx_queue_lock:
                            self._rx_queue.extend(data)
    
    def __init__(self, baudrate: int, data_bits: int, stop_bits: int, parity: str) -> None:
        """
        Initializes an RS485Bus object with the given parameters.
        
        Args:
            baudrate: The baudrate of the RS485 bus.
            data_bits: The number of data bits for the RS485 bus.
            stop_bits: The number of stop bits for the RS485 bus.
            parity: The parity for the RS485 bus. One of ['N', 'E', 'O', 'M', 'S'] (see pySerial documentation).
        """
        if baudrate < RS485_MIN_BAUDRATE:
            raise ValueError(f"RS485 bus has invalid baudrate: {baudrate} < {RS485_MIN_BAUDRATE}")
        if baudrate > RS485_MAX_BAUDRATE:
            raise ValueError(f"RS485 bus has invalid baudrate: {baudrate} > {RS485_MAX_BAUDRATE}")
        if data_bits < RS485_MIN_DATA_BITS:
            raise ValueError(f"RS485 bus has invalid data bits: {data_bits} < {RS485_MIN_DATA_BITS}")
        if data_bits > RS485_MAX_DATA_BITS:
            raise ValueError(f"RS485 bus has invalid data bits: {data_bits} > {RS485_MAX_DATA_BITS}")
        if stop_bits < RS485_MIN_STOP_BITS:
            raise ValueError(f"RS485 bus has invalid stop bits: {stop_bits} < {RS485_MIN_STOP_BITS}")
        if stop_bits > RS485_MAX_STOP_BITS:
            raise ValueError(f"RS485 bus has invalid stop bits: {stop_bits} > {RS485_MAX_STOP_BITS}")
        if parity not in ['N', 'E', 'O', 'M', 'S']:
            raise ValueError(f"RS485 bus has invalid parity: {parity} not in ['N', 'E', 'O', 'M', 'S']")
        
        self._baudrate = baudrate
        self._data_bits = data_bits
        self._stop_bits = stop_bits
        self._parity = parity
        self._shutdown_flag = False
        self._tx_queue_lock = Lock()
        self._tx_uart_lock = Lock()
        self._rx_queue_lock = Lock()
        self._tx_thread_condition = Condition(self._tx_queue_lock)
        self._tx_queue = bytearray()
        self._rx_queue = bytearray()
        
        if not settings.MOCK_MODE:
            self._serial = Serial(
                port = RS485_PORT,
                baudrate = baudrate,
                bytesize = data_bits,
                stopbits = stop_bits,
                parity = parity,
                timeout = 1
            )
            
            # DE pin enables transmitter when HIGH
            self._de_io = DigitalInOut(RS485_DE_PIN)
            self._de_io.direction = Direction.OUTPUT
            self._de_io.value = False
            
            # RE pin enables receiver when LOW
            self._re_io = DigitalInOut(RS485_RE_PIN)
            self._re_io.direction = Direction.OUTPUT
            self._re_io.value = False
        
        self._tx_thread = Thread(target = self._tx_thread)
        self._rx_thread = Thread(target = self._rx_thread)
        self._tx_thread.start()
        self._rx_thread.start()

    @classmethod
    def from_config(cls, config: dict) -> "RS485Bus":
        """
        Initializes an RS485Bus object from a configuration dictionary.
        
        Args:
            config: A dictionary containing the configuration parameters for the RS485 bus.
        """
        if 'baudrate' not in config:
            raise KeyError(f"RS485 bus config missing key: 'baudrate'")
        if 'data_bits' not in config:
            raise KeyError(f"RS485 bus config missing key: 'data_bits'")
        if 'stop_bits' not in config:
            raise KeyError(f"RS485 bus config missing key: 'stop_bits'")
        if 'parity' not in config:
            raise KeyError(f"RS485 bus config missing key: 'parity'")
        
        try:
            baudrate = int(config['baudrate'])
        except Exception as e:
            raise ValueError(f"RS485 bus has invalid baudrate: {config['baudrate']}") from e
        try:
            data_bits = int(config['data_bits'])
        except Exception as e:
            raise ValueError(f"RS485 bus has invalid data bits: {config['data_bits']}") from e
        try:
            stop_bits = int(config['stop_bits'])
        except Exception as e:
            raise ValueError(f"RS485 bus has invalid stop bits: {config['stop_bits']}") from e
        
        parity = str(config['parity'])
        return cls(baudrate, data_bits, stop_bits, parity)

    def __del__(self) -> None:
        self.shutdown()
     
    @property
    def baudrate(self) -> int:
        """
        Baudrate of RS485 bus.
        """
        if self._shutdown_flag:
            raise RuntimeError("RS485 bus has been shutdown")
        return self._baudrate
        
    @property
    def data_bits(self) -> int:
        """
        Number of data bits for RS485 bus.
        """
        if self._shutdown_flag:
            raise RuntimeError("RS485 bus has been shutdown")
        return self._data_bits
        
    @property
    def stop_bits(self) -> int:
        """
        Number of stop bits for RS485 bus.
        """
        return self._stop_bits
        
    @property
    def parity(self) -> str:
        """
        Parity for RS485 bus.
        """
        return self._parity

    @property
    def is_shutdown(self) -> bool:
        """
        True if RS485 bus has been shutdown, false otherwise.
        """
        return self._shutdown_flag

    def write(self, data: bytearray) -> None:
        """
        Writes data to the RS485 bus (non-blocking). Cannot be invoked after shutdown.

        Args:
            data: The data to write as a bytearray.
        """
        if self._shutdown_flag:
            raise RuntimeError("RS485 bus has been shutdown")
        with self._tx_thread_condition:
            self._tx_queue.extend(data)

            # Inform TX thread that data is available to send
            self._tx_thread_condition.notify_all()

    def read(self) -> bytearray:
        """
        Returns all data received from the RS485 bus since last read request (non-blocking).
        
        Returns:
            A bytearray containing all received data.
        """
        data = bytearray()
        with self._rx_queue_lock:
            data = self._rx_queue.copy()
            self._rx_queue.clear()
        return data

    def shutdown(self) -> None:
        """
        Shuts down the RS485 bus, stopping all communication and internal threads. Cannot be invoked after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("RS485 bus has already been shutdown")
        self._shutdown_flag = True
        
        # Inform TX thread that _shutdown_flag has been updated
        with self._tx_thread_condition:
            self._tx_thread_condition.notify_all()
        
        # Only cleanup UART/IO once not in use by tx thread (avoid corrupt transfers)
        if not settings.MOCK_MODE:
            with self._tx_uart_lock:
                self._serial.close()
                self._de_io.deinit()
                self._re_io.deinit()
        
