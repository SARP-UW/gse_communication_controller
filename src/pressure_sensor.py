import math
import random
import time
from typing import Dict
from . import settings

# Hardware dependent libraries
if not settings.MOCK_MODE:
    import board
    from busio import I2C
    from adafruit_ads1x15.ads1115 import ADS1115
    from adafruit_ads1x15.analog_in import AnalogIn

# Pressure sensor argument bounds
PS_COUNT = 3              # Number of supported pressure sensors
PS_MIN_VOLTAGE = 0.0      # Minimum possible voltage for pressure sensors
PS_MAX_VOLTAGE = 5.0      # Maximum possible voltage for pressure sensors
PS_MIN_PRESSURE = 0.0     # Minimum possible pressure for pressure sensors (in PSI)
PS_MAX_PRESSURE = 10000.0 # Maximum possible pressure for pressure sensors (in PSI)

if not settings.MOCK_MODE:
    
    # Global I2C bus for pressure sensor ADCs
    PS_ADC_I2C_BUS = I2C(board.SCL1, board.SDA1)
    
    # ADC used for to read pressure sensors
    PS_ADC = ADS1115(i2c = PS_ADC_I2C_BUS, address = 0x48)

class PressureSensor:
    """
    Class which represents a pressure sensor connected to the controller.
    """
    
    def __init__(self, id: int, name: str, min_voltage: float, max_voltage: float, min_pressure: float, max_pressure: float) -> None:
        """
        Initializes a PressureSensor object with the given parameters.
        
        Args:
            id: The unique ID of this pressure sensor.
            name: The name of this pressure sensor.
            min_voltage: The minimum voltage output of this pressure sensor.
            max_voltage: The maximum voltage output of this pressure sensor.
            min_pressure: The minimum pressure measurable by this pressure sensor.
            max_pressure: The maximum pressure measurable by this pressure sensor.
        """
        if id > PS_COUNT:
            raise ValueError(f"Pressure sensor has invalid ID: {id} > {PS_COUNT}")
        if id < 1:
            raise ValueError(f"Pressure sensor has invalid ID: {id} < 1")
        if min_voltage < PS_MIN_VOLTAGE:
            raise ValueError(f"Pressure sensor {id} has invalid minimum voltage: {min_voltage} < {PS_MIN_VOLTAGE}")
        if max_voltage > PS_MAX_VOLTAGE:
            raise ValueError(f"Pressure sensor {id} has invalid maximum voltage: {max_voltage} > {PS_MAX_VOLTAGE}")
        if min_voltage >= max_voltage:
            raise ValueError(f"Pressure sensor {id} has invalid voltage range: {min_voltage} >= {max_voltage}")
        if min_pressure < PS_MIN_PRESSURE:
            raise ValueError(f"Pressure sensor {id} has invalid minimum pressure: {min_pressure} < {PS_MIN_PRESSURE}")
        if max_pressure > PS_MAX_PRESSURE:
            raise ValueError(f"Pressure sensor {id} has invalid maximum pressure: {max_pressure} > {PS_MAX_PRESSURE}")
        if min_pressure >= max_pressure:
            raise ValueError(f"Pressure sensor {id} has invalid pressure range: {min_pressure} >= {max_pressure}")
        
        self._id = id
        self.name = name
        self._min_voltage = min_voltage
        self._max_voltage = max_voltage
        self._min_pressure = min_pressure
        self._max_pressure = max_pressure
        
        if settings.MOCK_MODE:
            self._base_pressure = (min_pressure + max_pressure) / 2
            self._start_time = time.time()

    @classmethod
    def from_config(cls, config: Dict) -> "PressureSensor":
        """
        Initializes a PressureSensor object from a configuration dictionary.
        
        Args:
            config: The target configuration dict.
        """
        if 'id' not in config:
            raise KeyError(f"Pressure sensor config missing key: 'id'")
        if 'name' not in config:
            raise KeyError(f"Pressure sensor config missing key: 'name'")
        if 'voltage_range' not in config:
            raise KeyError(f"Pressure sensor config missing key: 'voltage_range'")
        if 'pressure_range' not in config:
            raise KeyError(f"Pressure sensor config missing key: 'pressure_range'")
        
        if 'min' not in config['voltage_range']:
            raise KeyError(f"Pressure sensor config missing key: 'voltage_range.min'")
        if 'max' not in config['voltage_range']:
            raise KeyError(f"Pressure sensor config missing key: 'voltage_range.max'")
        if 'min' not in config['pressure_range']:
            raise KeyError(f"Pressure sensor config missing key: 'pressure_range.min'")
        if 'max' not in config['pressure_range']:
            raise KeyError(f"Pressure sensor config missing key: 'pressure_range.max'")
                
        name = config['name']
        if not isinstance(name, str):
            raise ValueError(f"Pressure sensor config 'name' must be a string, got: {type(name).__name__}")
        
        try:
            id = int(config['id'])
        except (ValueError, TypeError):
            raise ValueError(f"Pressure sensor config 'id' must be an integer, got: {type(config['id']).__name__}")
        try:
            min_voltage = float(config['voltage_range']['min'])
        except (ValueError, TypeError):
            raise ValueError(f"Pressure sensor config 'voltage_range.min' must be a number, got: {type(config['voltage_range']['min']).__name__}")
        try:
            max_voltage = float(config['voltage_range']['max'])
        except (ValueError, TypeError):
            raise ValueError(f"Pressure sensor config 'voltage_range.max' must be a number, got: {type(config['voltage_range']['max']).__name__}")
        try:
            min_pressure = float(config['pressure_range']['min'])
        except (ValueError, TypeError):
            raise ValueError(f"Pressure sensor config 'pressure_range.min' must be a number, got: {type(config['pressure_range']['min']).__name__}")
        try:
            max_pressure = float(config['pressure_range']['max'])
        except (ValueError, TypeError):
            raise ValueError(f"Pressure sensor config 'pressure_range.max' must be a number, got: {type(config['pressure_range']['max']).__name__}")
                 
        return cls(
            id = id,
            name = name,
            min_voltage = min_voltage,
            max_voltage = max_voltage,
            min_pressure = min_pressure,
            max_pressure = max_pressure
        )

    def __str__(self) -> str:
        """
        Gets string representation of PressureSensor.
        """
        return f"PressureSensor(id = {self._id}, name = {self.name}, min_voltage = {self._min_voltage}, max_voltage = {self._max_voltage}, min_pressure = {self._min_pressure}, max_pressure = {self._max_pressure})"

    @property
    def id(self) -> int:
        """
        Unique ID of this pressure sensor.
        """
        return self._id
        
    @property
    def min_voltage(self) -> float:
        """
        Minimum voltage output of this pressure sensor.
        """
        return self._min_voltage
    
    @property
    def max_voltage(self) -> float:
        """
        Maximum voltage output of this pressure sensor.
        """
        return self._max_voltage
    
    @property
    def min_pressure(self) -> float:
        """
        Minimum pressure measurable by this pressure sensor.
        """
        return self._min_pressure
    
    @property
    def max_pressure(self) -> float:
        """
        Maximum pressure measurable by this pressure sensor.
        """
        return self._max_pressure
    
    @property
    def pressure(self) -> float:
        """
        Current pressure read by sensor.
        """
        result: float = 0.0
        if settings.MOCK_MODE:
            elapsed = time.time() - self._start_time
            variation = math.sin(elapsed * 0.5) * (self._max_pressure - self._min_pressure) * 0.1
            noise_amplitude = (self._max_pressure - self._min_pressure) * 0.02
            noise = random.uniform(-noise_amplitude, noise_amplitude)
            pressure = self._base_pressure + variation + noise
            result = max(self._min_pressure, min(self._max_pressure, pressure))
        else:
            voltage = AnalogIn(PS_ADC, (self._id - 1)).voltage
            voltage_scale = self._max_voltage - self._min_voltage
            pressure_scale = self._max_pressure - self._min_pressure
            result = ((voltage - self._min_voltage) * (pressure_scale / voltage_scale)) + self._min_pressure
        return result 