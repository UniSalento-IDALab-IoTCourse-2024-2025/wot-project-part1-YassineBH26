import adafruit_dht
import board
import time

dht_device = adafruit_dht.DHT11(board.D4)

while True:
 try:
    temperature_c = dht_device.temperature
    humidity = dht_device.humidity
    print(f"Temp: {temperature_c}°C, Humidity: {humidity}%")
 except RuntimeError as e:
    print(f"Error reading sensor: {e}")

 time.sleep(3)
