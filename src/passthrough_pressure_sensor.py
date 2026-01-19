import math
import random
import time
from typing import Dict, List
from . import settings

# Hardware dependent libraries
if not settings.MOCK_MODE:
    import board
    from busio import I2C
    from adafruit_ads1x15.ads1115 import ADS1115
    from adafruit_ads1x15.analog_in import AnalogIn

# Passthrough pressure sensor argument bounds
PST_PS_COUNT = 4              # Number of supported passthrough pressure sensors
PST_PS_MIN_VOLTAGE = 0.0      # Minimum possible voltage for passthrough pressure sensors
PST_PS_MAX_VOLTAGE = 5.0      # Maximum possible voltage for passthrough pressure sensors
PST_PS_MIN_PRESSURE = 0.0     # Minimum possible pressure for passthrough pressure sensors (in PSI)
PST_PS_MAX_PRESSURE = 10000.0 # Maximum possible pressure for passthrough pressure sensors (in PSI)

# Gain setting for passthrough pressure sensor ADCs
PST_PS_ADC_GAIN = 2/3

if not settings.MOCK_MODE:

    # Pins for passthrough pressure sensor ADC I2C bus
    PST_PS_I2C_SCL_PIN = board.SCL
    PST_PS_I2C_SDA_PIN = board.SDA
    
    # Global I2C bus for passthrough pressure sensor ADCs
    pst_ps_i2c: I2C = None
    
    # ADC used for to read passthrough pressure sensors
    pst_ps_adc: ADS1115 = None

# List of inputs of initialized passthrough pressure sensors
pst_ps_init_list: List[int] = []
    
class PassthroughPressureSensor:
    """
    Class which represents a passthrough pressure sensor connected to the controller.
    """
    
    def __init__(self, input: int, name: str, min_voltage: float, max_voltage: float, min_pressure: float, max_pressure: float) -> None:
        """
        Initializes a PassthroughPressureSensor object with the given parameters.
        
        Args:
            input: The input number of this passthrough pressure sensor.
            name: The name of this passthrough pressure sensor.
            min_voltage: The minimum voltage output of this passthrough pressure sensor.
            max_voltage: The maximum voltage output of this passthrough pressure sensor.
            min_pressure: The minimum pressure measurable by this passthrough pressure sensor.
            max_pressure: The maximum pressure measurable by this passthrough pressure sensor.
        """
        if input > PST_PS_COUNT:
            raise ValueError(f"Passthrough pressure sensor has invalid input number: {input} > {PST_PS_COUNT}")
        if input < 1:
            raise ValueError(f"Passthrough pressure sensor has invalid input number: {input} < 1")
        if min_voltage < PST_PS_MIN_VOLTAGE:
            raise ValueError(f"Passthrough pressure sensor {input} has invalid minimum voltage: {min_voltage} < {PST_PS_MIN_VOLTAGE}")
        if max_voltage > PST_PS_MAX_VOLTAGE:
            raise ValueError(f"Passthrough pressure sensor {input} has invalid maximum voltage: {max_voltage} > {PST_PS_MAX_VOLTAGE}")
        if min_voltage >= max_voltage:
            raise ValueError(f"Passthrough pressure sensor {input} has invalid voltage range: {min_voltage} >= {max_voltage}")
        if min_pressure < PST_PS_MIN_PRESSURE:
            raise ValueError(f"Passthrough pressure sensor {input} has invalid minimum pressure: {min_pressure} < {PST_PS_MIN_PRESSURE}")
        if max_pressure > PST_PS_MAX_PRESSURE:
            raise ValueError(f"Passthrough pressure sensor {input} has invalid maximum pressure: {max_pressure} > {PST_PS_MAX_PRESSURE}")
        if min_pressure >= max_pressure:
            raise ValueError(f"Passthrough pressure sensor {input} has invalid pressure range: {min_pressure} >= {max_pressure}")
        
        # Initialize I2C bus and ADC (used by all pressure sensors) if not already done
        if not settings.MOCK_MODE and pst_ps_i2c is None:
            pst_ps_i2c = I2C(PST_PS_I2C_SCL_PIN, PST_PS_I2C_SDA_PIN)
            pst_ps_adc = ADS1115(i2c = pst_ps_i2c, gain = PST_PS_ADC_GAIN, address = 0x48)
        
        # Keep track of initialized pressure sensor inputs to prevent duplicates and for deinitialization of shared objects
        if input in pst_ps_init_list:
            raise RuntimeError(f"Passthrough pressure sensor with input {input} has already been initialized")
        pst_ps_init_list.append(input)
        
        self._input: int = input
        self.name: str = name
        self._min_voltage: float = min_voltage
        self._max_voltage: float = max_voltage
        self._min_pressure: float = min_pressure
        self._max_pressure: float = max_pressure
        self._shutdown_flag: bool = False
        
        # Variables for simulating pressure readings if in mock mode
        if settings.MOCK_MODE:
            self._base_pressure: float = (min_pressure + max_pressure) / 2
            self._start_time: float = time.time()

    @classmethod
    def from_config(cls, config: Dict) -> "PassthroughPressureSensor":
        """
        Initializes a PassthroughPressureSensor object from a configuration dictionary.
        
        Args:
            config: The target configuration dict.
        """
        if 'input' not in config:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'input'")
        if 'name' not in config:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'name'")
        if 'voltage_range' not in config:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'voltage_range'")
        if 'pressure_range' not in config:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'pressure_range'")
        
        if 'min' not in config['voltage_range']:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'voltage_range.min'")
        if 'max' not in config['voltage_range']:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'voltage_range.max'")
        if 'min' not in config['pressure_range']:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'pressure_range.min'")
        if 'max' not in config['pressure_range']:
            raise KeyError(f"Passthrough pressure sensor config missing key: 'pressure_range.max'")
                
        name = config['name']
        if not isinstance(name, str):
            raise ValueError(f"Passthrough pressure sensor config 'name' must be a string, got: {type(name).__name__}")
        
        try:
            input = int(config['input'])
        except (ValueError, TypeError):
            raise ValueError(f"Passthrough pressure sensor config 'input' must be an integer, got: {type(config['input']).__name__}")
        try:
            min_voltage = float(config['voltage_range']['min'])
        except (ValueError, TypeError):
            raise ValueError(f"Passthrough pressure sensor config 'voltage_range.min' must be a number, got: {type(config['voltage_range']['min']).__name__}")
        try:
            max_voltage = float(config['voltage_range']['max'])
        except (ValueError, TypeError):
            raise ValueError(f"Passthrough pressure sensor config 'voltage_range.max' must be a number, got: {type(config['voltage_range']['max']).__name__}")
        try:
            min_pressure = float(config['pressure_range']['min'])
        except (ValueError, TypeError):
            raise ValueError(f"Passthrough pressure sensor config 'pressure_range.min' must be a number, got: {type(config['pressure_range']['min']).__name__}")
        try:
            max_pressure = float(config['pressure_range']['max'])
        except (ValueError, TypeError):
            raise ValueError(f"Passthrough pressure sensor config 'pressure_range.max' must be a number, got: {type(config['pressure_range']['max']).__name__}")
                 
        return cls(
            input = input,
            name = name,
            min_voltage = min_voltage,
            max_voltage = max_voltage,
            min_pressure = min_pressure,
            max_pressure = max_pressure
        )

    def __del__(self) -> None:
        """
        Destructor for PassthroughPressureSensor - shuts down the sensor.
        """
        self.shutdown()

    def __str__(self) -> str:
        """
        Gets string representation of this passthrough pressure sensor (ommits current state info)
        """
        return f"PassthroughPressureSensor(input = {self._input}, name = {self.name}, min_voltage = {self._min_voltage}, max_voltage = {self._max_voltage}, min_pressure = {self._min_pressure}, max_pressure = {self._max_pressure})"

    @property
    def is_shutdown(self) -> bool:
        """
        Whether this passthrough pressure sensor has been shutdown.
        """
        return self._shutdown_flag

    @property
    def input(self) -> int:
        """
        Input number of this passthrough pressure sensor.
        """
        return self._input
        
    @property
    def min_voltage(self) -> float:
        """
        Minimum voltage output of this passthrough pressure sensor.
        """
        return self._min_voltage
    
    @property
    def max_voltage(self) -> float:
        """
        Maximum voltage output of this passthrough pressure sensor.
        """
        return self._max_voltage
    
    @property
    def min_pressure(self) -> float:
        """
        Minimum pressure measurable by this passthrough pressure sensor.
        """
        return self._min_pressure
    
    @property
    def max_pressure(self) -> float:
        """
        Maximum pressure measurable by this passthrough pressure sensor.
        """
        return self._max_pressure
        
    @property
    def pressure(self) -> float:
        """
        Current pressure read by this passthrough pressure sensor. Cannot be called after shutdown.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot read passthrough pressure sensor after shutdown")
        result: float = 0.0
        
        # If in mock mode generate simulated pressure reading using sinusoidal variation + random noise
        if settings.MOCK_MODE:
            elapsed = time.time() - self._start_time
            variation = math.sin(elapsed * 0.5) * (self._max_pressure - self._min_pressure) * 0.1
            noise_amplitude = (self._max_pressure - self._min_pressure) * 0.02
            noise = random.uniform(-noise_amplitude, noise_amplitude)
            pressure = self._base_pressure + variation + noise
            result = max(self._min_pressure, min(self._max_pressure, pressure))
            
        # Otherwise read voltage from ADC then map to voltage range / pressure range
        else:
            voltage = AnalogIn(pst_ps_adc, (self._input - 1)).voltage
            voltage_scale = self._max_voltage - self._min_voltage
            pressure_scale = self._max_pressure - self._min_pressure
            result = ((voltage - self._min_voltage) * (pressure_scale / voltage_scale)) + self._min_pressure
        return result
    
    def shutdown(self) -> None:
        """
        Shuts down this passthrough pressure sensor. Cannot be called more than once.
        """
        if self._shutdown_flag:
            raise RuntimeError("Cannot shutdown passthrough pressure sensor more than once")
        self._shutdown_flag = True
        pst_ps_init_list.remove(self._input)
        if not settings.MOCK_MODE and len(pst_ps_init_list) == 0:
            pst_ps_i2c.deinit()
            pst_ps_i2c = None
            pst_ps_adc = None
            
            