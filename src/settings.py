# If true the system will simulate hardware
MOCK_MODE: bool = False

# Rate at which to send queued messages on RS485 bus (in Hz)
RS485_TX_UPDATE_RATE: int = 100

# Rate at which to receive messages on RS485 bus (in Hz)
RS485_RX_UPDATE_RATE: int = 100

# Rate at which to send data and query for received data on the radio (in Hz)
RADIO_UPDATE_RATE: int = 100