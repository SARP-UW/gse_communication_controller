from . import settings
from typing import List
from threading import Thread, Lock, Condition
from time import sleep, time
import os
import re

# <TEMP>
# https://www.silabs.com/documents/public/application-notes/AN633.pdf
# https://www.silabs.com/documents/public/data-sheets/Si4468-7.pdf

# Hardware dependent libraries and initialization
if not settings.MOCK_MODE:
    import board
    from digitalio import DigitalInOut, Direction
    from spidev import SpiDev 
    import RPi.GPIO as RPIO
    
    # Radio reset pin number (digitalio pin)
    RADIO_RESET_PIN = board.D25

    # Radio interrupt (NIRQ) pin number (RPi.GPIO BCM pin number)
    RADIO_NIRQ_PIN = 24

# Radio argument bounds
RADIO_MAX_PACKET_SIZE = 64 # Maximum size of a packet for the radio transceiver (in bytes)
RADIO_MAX_CHANNEL = 255    # Maximum permissible channel number

# Command arguments for radio configuration
RADIO_CFG_POWER_UP = bytearray([0x01, 0x01, 0x01, 0xC9, 0xC3, 0x80])   # Power up command arguments (use external mems/TXCO oscillator at 30Mhz)
RADIO_CFG_GPIO = bytearray([0x00, 0x00, 0x20, 0x00, 0x00, 0x00, 0x00]) # GPIO configuration command arguments (GPIO2 = TX/RX state)
RADIO_CFG_INT_CTL_ENABLE_PROP = bytearray([0x01, 0x01, 0x00, 0b00000001])    # Interrupt control enable property arguments (enable PH interrupts)
RADIO_CFG_INT_CTL_PH_ENABLE_PROP = bytearray([0x01, 0x01, 0x01, 0b00010000]) # Packet handler interrupt enable property arguments (enable packet received interrupt)

# Radio command tags
RADIO_CMD_POWER_UP = 0x02        # Powers up radio (with given arguments)
RADIO_CMD_GPIO_PIN_CFG = 0x13    # Configures GPIO pins on radio
RADIO_CMD_READ_CMD_BUFFER = 0x44 # Reads command buffer (used for reading CTS register)
RADIO_CMD_SET_PROPERTY = 0x11    # Sets a property on the radio
RADIO_CMD_FIFO_INFO = 0x15       # Allows for clearning FIFOs and getting their information
RADIO_CMD_WRITE_TX_FIFO = 0x66   # Writes data to TX FIFO
RADIO_CMD_START_TX = 0x31        # Starts transmission of data in TX FIFO
RADIO_CMD_START_RX = 0x32        # Starts reception of data into RX FIFO
RADIO_CMD_PACKET_INFO = 0x16     # Gets information about the received packet
RADIO_CMD_READ_RX_FIFO = 0x77    # Reads data from RX FIFO

# Misc radio register constants
RADIO_CTS_READY_VALUE = 0xFF                                        # CTS (clear to send) register ready value
RADIO_FIFO_INFO_RESET_TX_FIFO_ARG = 0x01                            # Mask to send as argument to FIFO_INFO which clears TX FIFO
RADIO_START_TX_CONDITION_ARG = 0b00000011                           # Condition arg for START_TX - Ready state after transmission, enter tx mode, start immediately
RADIO_ENTER_RX_NCH_ARGS = bytearray([0x00, 0x00, 0x08, 0x08, 0x08]) # Arguments for START_RX command (ommiting channel) (no condition, variable length, keep trying to receive)

# Tracks initialization of radio transceiver
radio_init: bool = False

class Radio:
    
    def _wait_cts(self) -> bool:
        """
        Internal helper function which waits for CTS (clear to send) signal from radio
        
        Returns:
            True if CTS was received before timeout, False otherwise.
        """
        start_time = time()
        while (time() - start_time) < settings.RADIO_CTS_TIMEOUT:
            data = self._spi_bus.xfer2(bytearray([RADIO_CMD_READ_CMD_BUFFER, 0x00]))
            if data[1] == RADIO_CTS_READY_VALUE:
                return True
        return False
    
    def _tx_thread(self) -> None:
        """
        Internal thread which transmits queued packets
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
                    
                    # Extract queued packets to send (prevent blocking with SPI transfers)
                    tx_packets: List[bytearray] = []
                    with self._tx_queue_lock:
                        tx_packets = self._tx_queue.copy()
                        self._tx_queue.clear()
                    
                    with self._spi_bus_lock:
                        for packet in tx_packets:
                            
                            # Clear TX FIFO
                            self._spi_bus.xfer2(bytearray([RADIO_CMD_FIFO_INFO, RADIO_FIFO_INFO_RESET_TX_FIFO_ARG]))
                            self._wait_cts()
                            
                            # Write packet to TX FIFO
                            self._spi_bus.xfer2(bytearray([RADIO_CMD_WRITE_TX_FIFO]) + packet)
                            self._wait_cts()
                            
                            # Start packet transmission
                            self._spi_bus.xfer2(bytearray([RADIO_CMD_START_TX, self._channel, RADIO_START_TX_CONDITION_ARG, len(packet), 0x00, 0x00]))
                            self._wait_cts()
                        
                        # Enter RX mode again if we are in TX mode (packets were sent) (this allows us to receive packets again)
                        if len(tx_packets) > 0:
                            self._spi_bus.xfer2(bytearray([RADIO_CMD_START_RX, self._channel]) + RADIO_ENTER_RX_NCH_ARGS)
                            self._wait_cts()
                
                # Simulate "sending" data by clearing the TX queue
                else:
                    with self._tx_queue_lock:
                        self._tx_queue.clear()
    
    def _rx_interrupt(self) -> None:
        """
        Internal interrupt handler that receives packets (called when NIRQ goes low).
        """
        if not self._shutdown_flag:
            with self._spi_bus_lock:
                
                # Request packet info from radio
                self._spi_bus.xfer2(bytearray([RADIO_CMD_PACKET_INFO]))
                
                # Wait until packet info return values are ready (cts is high)
                start_time = time()
                packet_info_data = bytearray()
                while (time() - start_time) < settings.RADIO_CTS_TIMEOUT:
                    packet_info_data = self._spi_bus.xfer2(bytearray([RADIO_CMD_READ_CMD_BUFFER, 0x00, 0x00, 0x00]))
                    if packet_info_data[1] == RADIO_CTS_READY_VALUE:
                        break
                else: 
                    return

                # Parse packet length from packet info (bytes 2 and 3)
                packet_length = (packet_info_data[2] << 8) | packet_info_data[3]
                
                # Request packet data from RX FIFO
                self._spi_bus.xfer2(bytearray([RADIO_CMD_READ_RX_FIFO]))
                
                # Wait until packet data is ready (cts is high)
                start_time = time()
                read_rx_fifo_data = bytearray()
                while (time() - start_time) < settings.RADIO_CTS_TIMEOUT:
                    read_rx_fifo_data = self._spi_bus.xfer2(bytearray([RADIO_CMD_READ_CMD_BUFFER] + [0x00] * packet_length))
                    if read_rx_fifo_data[1] == RADIO_CTS_READY_VALUE:
                        break
                else: 
                    return
                    
                packet_data = read_rx_fifo_data[2:(2 + packet_length)]
                with self._rx_queue_lock:
                    self._rx_queue.append(packet_data)      
    
    def __init__(self, radio_config_path: str, channel: int) -> None:
        """
        Initializes a Radio object with the given parameters.
        
        Args:
            radio_config_path: The path to the radio configuration file (C file generated using Silicon Labs WDS).
            channel: The channel number to use for transmission/reception.
        """
        if not os.path.exists(radio_config_path):
            raise FileNotFoundError(f"Radio configuration file not found: {radio_config_path}")
        if channel < 0:
            raise ValueError(f"Invalid channel number: {channel} < 0")
        if channel > RADIO_MAX_CHANNEL:
            raise ValueError(f"Invalid channel number: {channel} > {RADIO_MAX_CHANNEL}")
        
        # Ensure only one Radio is ever initialized (due to shared state in component)
        if radio_init:
            raise RuntimeError("Radio has already been initialized")
        radio_init = True
        
        self._radio_config_path: str = radio_config_path
        self._channel: int = channel
        self._shutdown_flag: bool = False
        self._tx_queue_lock: Lock = Lock()
        self._rx_queue_lock: Lock = Lock()
        self._spi_bus_lock: Lock = Lock()
        self._tx_thread_condition: Condition = Condition(self._tx_queue_lock)
        self._tx_queue: List[bytearray] = []
        self._rx_queue: List[bytearray] = []
        
        if not settings.MOCK_MODE:
            self._reset_io: DigitalInOut = DigitalInOut(RADIO_RESET_PIN)
            self._reset_io.direction = Direction.OUTPUT
            self._reset_io.value = False
            
            RPIO.setmode(RPIO.BCM)
            RPIO.setup(RADIO_NIRQ_PIN, RPIO.IN)
            
            self._spi_bus: SpiDev = SpiDev(
                bus = 0,
                device = 0,
            )
            
            # Reset the radio transceiver
            self._reset_io.value = True
            sleep(0.02)
            self._reset_io.value = False
            sleep(0.02)
            
            # Power up command takes core system config arguments (use external mems/TXCO oscillator at 30Mhz)
            self._spi_bus.xfer2(bytearray([RADIO_CMD_POWER_UP]) + RADIO_CFG_POWER_UP)
            if not self._wait_cts():
                raise TimeoutError("Timeout while waiting for CTS after power up command")
            
            # Configure GPIO so that GPIO2 indicates TX/RX state
            self._spi_bus.xfer2(bytearray([RADIO_CMD_GPIO_PIN_CFG]) + RADIO_CFG_GPIO)
            if not self._wait_cts():
                raise TimeoutError("Timeout while waiting for CTS after GPIO configuration command")
        
        # Parsing logic for radio configuration file
        with open(radio_config_path, 'r') as f:
            content = f.read()
        
        # Pattern to match the comment block + #define
        # Captures: property name, number of properties, group ID, start ID, and the byte array
        pattern = r'// Set properties:\s+(RF_\w+)\s+// Number of properties:\s+(\d+)\s+// Group ID:\s+(0x[0-9A-Fa-f]+)\s+// Start ID:\s+(0x[0-9A-Fa-f]+)\s+.*?#define\s+\1\s+((?:0x[0-9A-Fa-f]{2}(?:,\s*)?)+)'
        matches = re.finditer(pattern, content, re.DOTALL | re.MULTILINE)
        
        radio_properties = []
        self._radio_property_str: str = ""
        for match in matches:
            property_name = match.group(1)
            num_properties = int(match.group(2))
            group_id = int(match.group(3), 16)
            start_id = int(match.group(4), 16)
            bytes_str = match.group(5)
            
            # Append property to string for use in __str__ method
            self._radio_property_str += f"({property_name}: {bytes_str}), "
            
            # Parse the byte values from list in the #define (property args) and create a bytearray from it
            bytes_list = [int(b.strip(), 16) for b in bytes_str.split(',')]
            radio_properties.append(bytearray([group_id, num_properties, start_id] + bytes_list))
        
        # Get rid of trailing comma and space (added after each property - dont want it at end)
        self._radio_property_str = self._radio_property_str.rstrip(', ')
        
        if len(radio_properties) != 31:
            raise ValueError(f"Invalid number of radio properties: {len(radio_properties)} != 31 (config file is likely incorrect)")
            
        if not settings.MOCK_MODE:
            
            # Set all properties in the radio transceiver using set_property command
            for prop in radio_properties:
                self._spi_bus.xfer2(bytearray([RADIO_CMD_SET_PROPERTY]) + prop)
                if not self._wait_cts():
                    raise TimeoutError("Timeout while waiting for CTS after set property command (user properties)")

            # Override IRQ properties so that NIRQ is pulled low when we receive a packet
            self._spi_bus.xfer2(bytearray([RADIO_CMD_SET_PROPERTY]) + RADIO_CFG_INT_CTL_ENABLE_PROP)
            if not self._wait_cts():
                raise TimeoutError("Timeout while waiting for CTS after set property command (interrupt property override)")

            # Configure interrupt on NIRQ pin so _rx_interrupt is called when we receive a packet
            RPIO.add_event_detect(
                channel = RADIO_NIRQ_PIN,
                edge = RPIO.FALLING,
                callback = lambda _: self._rx_interrupt()
            )

            # Enter RX mode (so that we can receive packets)            
            self._spi_bus.xfer2(bytearray([RADIO_CMD_START_RX, self._channel]) + RADIO_ENTER_RX_NCH_ARGS)
            self._wait_cts()

        self._tx_thread: Thread = Thread(target=self._tx_thread)
        self._tx_thread.start()
              
    @classmethod
    def from_config(cls, config: dict) -> "Radio":
        """
        Initializes a Radio object from a configuration dictionary.
        
        Args:
            config: The target configuration dictionary.
        """
        if 'radio_config_path' not in config:
            raise KeyError(f"Radio config missing key: 'radio_config_path'")
        if 'channel' not in config:
            raise KeyError(f"Radio config missing key: 'channel'")
        
        radio_config_path = config['radio_config_path']
        if not isinstance(radio_config_path, str):
            raise ValueError(f"Radio config 'radio_config_path' must be a string, got: {type(radio_config_path).__name__}")
        
        try:
            channel = int(config['channel'])
        except (ValueError, TypeError):
            raise ValueError(f"Radio config 'channel' must be an integer, got: {type(config['channel']).__name__}")
        
        return cls(
            radio_config_path = radio_config_path,
            channel = channel
        )

    def __str__(self) -> str:
        """
        Gets a string representation of the Radio (ommits current state info).
        """
        return f"Radio(radio_config_path = {self._radio_config_path}, channel = {self._channel}, radio_properties = {self._radio_property_str})"

    def __del__(self) -> None:
        """
        Destructor for Radio - shuts down the radio transceiver.
        """
        self.shutdown()

    @property
    def is_shutdown(self) -> bool:
        """
        True if the radio transceiver has been shutdown, false otherwise.
        """
        return self._shutdown_flag

    @property
    def radio_config_path(self) -> str:
        """
        Gets the path to the radio configuration file.
        """
        return self._radio_config_path

    @property
    def channel(self) -> int:
        """
        Gets the channel used by the radio transceiver.
        """
        return self._channel

    @property
    def is_shutdown(self) -> bool:
        """
        True if Radio has been shutdown, false otherwise.
        """
        return self._shutdown_flag

    def transmit(self, packets: List[bytearray]) -> None:
        """
        Transmits the given list of packets using the radio transceiver. Note that while transmitting, 
        the radio cannot receive packets. Cannot be called after shutdown.
        
        Args:
            packets: The list of packets to transmit (bytearray of data).
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot transmit data: Radio is shutdown")
        for packet in packets:
            if len(packet) == 0:
                raise ValueError("Cannot transmit packet with no data")
            if len(packet) > RADIO_MAX_PACKET_SIZE:
                raise ValueError(f"Cannot transmit packet: size {len(packet)} > RADIO_MAX_PACKET_SIZE {RADIO_MAX_PACKET_SIZE}")

        with self._tx_thread_condition:
            for packet in packets:
                self._tx_queue.append(packet)
                
            # Inform TX thread that data is available to send
            self._tx_thread_condition.notify_all()

    def receive(self) -> List[bytearray]:
        """
        Gets all packets received by radio transceiver since last call to receive().
        
        Returns:
            A list of the received packets (bytearray of data).
        """
        packets: List[bytearray] = []
        with self._rx_queue_lock:
            packets = self._rx_queue.copy()
            self._rx_queue.clear()
        return packets 
    
    def shutdown(self) -> None:
        """
        Shuts down the radio transceiver and stops all internal threads (blocks until all packets sent).
        """
        if self._shutdown_flag:
            raise RuntimeError("Radio is already shutdown")
        
        # Wait until all queued packets have been sent or timeout
        start_time = time()
        while (time() - start_time) < settings.RADIO_SHUTDOWN_TIMEOUT:
            with self._tx_queue_lock:
                if len(self._tx_queue) == 0:
                    break
            sleep(0.01)
        
        radio_init = False
        self._shutdown_flag = True

        # Inform TX thread that _shutdown_flag has been updated
        with self._tx_thread_condition:
            self._tx_thread_condition.notify_all()
        
        # Cleanup IO/SPI only once SPI bus not in use by thread/interrupt (avoid corrupt transfers)
        if not settings.MOCK_MODE:
            with self._spi_bus_lock: 
                RPIO.remove_event_detect(RADIO_NIRQ_PIN)
                RPIO.cleanup(RADIO_NIRQ_PIN)
                self._reset_io.deinit()
                self._spi_bus.close()
                
            