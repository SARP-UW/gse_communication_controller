###################################################################################################
# Website Settings
###################################################################################################

# The rate (in Hz) at which the website update thread runs
WEBSITE_THREAD_UPDATE_RATE: float = 20.0

# The time (in seconds) after which a user is considered disconnected if no heartbeat is received
WEBSITE_HEARTBEAT_TIMEOUT: float = 3.0

###################################################################################################
# General System Settings
###################################################################################################

# If true the system will simulate hardware
MOCK_MODE: bool = False

# Timeout for waiting for CTS (clear to send) from radio (in seconds)
RADIO_CTS_TIMEOUT: float = 1.0

# Timeout for waiting for TX queue to drain on radio shutdown (in seconds)
RADIO_SHUTDOWN_TIMEOUT: float = 5.0

# If true, application prints website status messages to console.
PRINT_WEBSITE_STATUS: bool = False

# If true, application prints website error messages to console.
PRINT_WEBSITE_ERRORS: bool = True
