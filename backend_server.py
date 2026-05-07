from flask import Flask, request, jsonify
from flask_cors import CORS
from gpiozero import DigitalInputDevice
from datetime import datetime
import threading
import time
import adafruit_dht
import board

app = Flask(__name__)
CORS(app)

# Configuration
TILT_GPIO = 17
DHT_PIN = board.D4

# Sensors setup
tilt_sensor = DigitalInputDevice(TILT_GPIO, pull_up=False)
dht_device = adafruit_dht.DHT11(DHT_PIN)

# Shared data
latest_data = {
    "lat": None,
    "lon": None,
    "gps_time": None,
    "temperature": None,
    "humidity": None,
    "tilt": None,
    "sensor_time": None,
    "alerts": []
}

data_lock = threading.Lock()

def update_alerts():
    alerts = []

    temp = latest_data["temperature"]
    humidity = latest_data["humidity"]
    tilt = latest_data["tilt"]

    if temp is not None and temp > 30:
        alerts.append("High temperature")
    if humidity is not None and humidity > 75:
        alerts.append("High humidity")
    if tilt is True:
        alerts.append("Box tilted")

    latest_data["alerts"] = alerts

def sensor_loop():
    while True:
        try:
            temperature = dht_device.temperature
            humidity = dht_device.humidity

            # If tilt logic is reversed, change this line to:
            # tilt = not bool(tilt_sensor.value)
            tilt = bool(tilt_sensor.value)

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            with data_lock:
                latest_data["temperature"] = temperature
                latest_data["humidity"] = humidity
                latest_data["tilt"] = tilt
                latest_data["sensor_time"] = now
                update_alerts()

            print(f"[{now}] Temp: {temperature}C | Humidity: {humidity}% | Tilt: {tilt}")

        except Exception as e:
            print(f"Sensor read error: {e}")

        time.sleep(2)

@app.route("/location")
def location():
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with data_lock:
        latest_data["lat"] = lat
        latest_data["lon"] = lon
        latest_data["gps_time"] = now

    print(f"[{now}] GPS received -> Latitude: {lat}, Longitude: {lon}")
    return "OK"

@app.route("/data")
def get_data():
    with data_lock:
        return jsonify(latest_data)

if __name__ == "__main__":
    sensor_thread = threading.Thread(target=sensor_loop, daemon=True)
    sensor_thread.start()

    app.run(host="0.0.0.0", port=5000)
