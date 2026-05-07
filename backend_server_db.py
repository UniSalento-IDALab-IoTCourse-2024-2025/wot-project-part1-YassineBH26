from flask import Flask, request, jsonify
from flask_cors import CORS
from gpiozero import DigitalInputDevice
from datetime import datetime
import threading
import time
import sqlite3
import json
import adafruit_dht
import board

app = Flask(__name__)
CORS(app)

# Configuration
TILT_GPIO = 17
DHT_PIN = board.D4
DRIVER_ID = "driver_1"
DB_FILE = "iot_data.db"

# Sensors
tilt_sensor = DigitalInputDevice(TILT_GPIO, pull_up=False)
dht_device = adafruit_dht.DHT11(DHT_PIN)

# Shared data
latest_data = {
    "driver_id": DRIVER_ID,
    "lat": None,
    "lon": None,
    "gps_time": None,
    "temperature": None,
    "humidity": None,
    "tilt": None,
    "sensor_time": None,
    "alerts": []
}

monitoring_active = True
data_lock = threading.Lock()


def get_db_connection():
    return sqlite3.connect(DB_FILE)
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        driver_id TEXT,
        latitude TEXT,
        longitude TEXT,
        temperature REAL,
        humidity REAL,
        tilt INTEGER,
        alerts TEXT
    )
    """)

    conn.commit()
    conn.close()


def update_alerts():
    alerts = []

    if latest_data["temperature"] is not None and latest_data["temperature"] > 30:
        alerts.append("High temperature")

    if latest_data["humidity"] is not None and latest_data["humidity"] > 75:
        alerts.append("High humidity")

    if latest_data["tilt"] is True:
        alerts.append("Box tilted")

    latest_data["alerts"] = alerts


def save_to_db():
    conn = get_db_connection()
    cur = conn.cursor()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
    INSERT INTO readings (
        timestamp, driver_id, latitude, longitude,
        temperature, humidity, tilt, alerts
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp,
        latest_data["driver_id"],
        latest_data["lat"],
        latest_data["lon"],
        latest_data["temperature"],
        latest_data["humidity"],
        1 if latest_data["tilt"] else 0,
        json.dumps(latest_data["alerts"])
    ))

    conn.commit()
    conn.close()


def sensor_loop():
    global monitoring_active

    while True:
        try:
            with data_lock:
                active = monitoring_active

            if active:
                temperature = dht_device.temperature
                humidity = dht_device.humidity
                tilt = bool(tilt_sensor.value)

                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                with data_lock:
                    latest_data["temperature"] = temperature
                    latest_data["humidity"] = humidity
                    latest_data["tilt"] = tilt
                    latest_data["sensor_time"] = now

                    update_alerts()
                    save_to_db()

                print("Time:", now,
                      "| Temp:", temperature,
                      "| Hum:", humidity,
                      "| Tilt:", tilt)
            else:
                print("Monitoring paused")

        except Exception as e:
            print("Sensor error:", e)

        time.sleep(5)

@app.route("/location")
def location():
    lat = request.args.get("lat")
    lon = request.args.get("lon")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with data_lock:
        latest_data["lat"] = lat
        latest_data["lon"] = lon
        latest_data["gps_time"] = now

    print("GPS:", lat, lon)

    return "OK"


@app.route("/data")
def data():
    with data_lock:
        response = latest_data.copy()
        response["monitoring_active"] = monitoring_active
        return jsonify(response)

@app.route("/history")
def history():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM readings ORDER BY id DESC LIMIT 20")

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        result.append({
            "id": row[0],
            "timestamp": row[1],
            "driver_id": row[2],
            "lat": row[3],
            "lon": row[4],
            "temperature": row[5],
            "humidity": row[6],
            "tilt": bool(row[7]),
            "alerts": json.loads(row[8]) if row[8] else []
        })

    return jsonify(result)


@app.route("/start-monitoring", methods=["POST"])
def start_monitoring():
    global monitoring_active
    with data_lock:
        monitoring_active = True
    return jsonify({
        "message": "Monitoring started",
        "monitoring_active": monitoring_active
    })


@app.route("/stop-monitoring", methods=["POST"])
def stop_monitoring():
    global monitoring_active
    with data_lock:
        monitoring_active = False
    return jsonify({
        "message": "Monitoring stopped",
        "monitoring_active": monitoring_active
    })


@app.route("/toggle-monitoring", methods=["POST"])
def toggle_monitoring():
    global monitoring_active
    with data_lock:
        monitoring_active = not monitoring_active
    return jsonify({
        "message": "Monitoring toggled",
        "monitoring_active": monitoring_active
    })

if __name__ == "__main__":
    init_db()

    thread = threading.Thread(target=sensor_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5000)
