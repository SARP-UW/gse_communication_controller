import time
import board
# import busio  # another method to get I2C. test both
from adafruit_ads1x15 import ADS1115, AnalogIn, ads1x15

# i2c = busio.I2C(board.SCL, board.SDA)
i2c = board.I2C()

ads = ads.ADS1115(i2c)
ads.gain = 1  # TODO: Change depending on pressure sensor sensitivity

chan0 = AnalogIn(ads, ads1x15.Pin.A0)
chan1 = AnalogIn(ads, ads1x15.Pin.A1)
chan2 = AnalogIn(ads, ads1x15.Pin.A2)
chan3 = AnalogIn(ads, ads1x15.Pin.A3)

# Continuously print values from each pin
print("ADC Pressure Sensor Voltages")
while True:
    print(f"0: {chan0.voltage}V; 1: {chan1.voltage}V; 2: {chan2.voltage}V; 3: {chan3.voltage}V")
    time.sleep(1)