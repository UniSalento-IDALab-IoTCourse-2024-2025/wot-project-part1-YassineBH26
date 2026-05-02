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

DB_FILE = "iot_data_v2.db"

# GPIO setup
TILT_GPIO = 17
DHT_PIN = board.D4

tilt_sensor = DigitalInputDevice(TILT_GPIO, pull_up=False)
dht_device = adafruit_dht.DHT11(DHT_PIN)

latest_data = {
    "temperature": None,
    "humidity": None,
    "tilt": False,
    "lat": None,
    "lon": None,
    "gps_time": None,
    "sensor_time": None,
    "alerts": [],
    "monitoring_active": True,
    "active_delivery_id": None
}

data_lock = threading.Lock()


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def update_alerts():
    alerts = []

    temperature = latest_data["temperature"]
    humidity = latest_data["humidity"]
    tilt = latest_data["tilt"]

    if temperature is not None and temperature > 30:
        alerts.append("High temperature")

    if humidity is not None and humidity > 75:
        alerts.append("High humidity")

    if tilt:
        alerts.append("Box tilted")

    latest_data["alerts"] = alerts


def get_current_active_delivery():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id
        FROM deliveries
        WHERE status = 'active'
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    if row:
        return row["id"]

    return None


def save_monitoring_record():
    delivery_id = latest_data["active_delivery_id"]

    if delivery_id is None:
        return

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO monitoring_records (
            delivery_id,
            timestamp,
            latitude,
            longitude,
            temperature,
            humidity,
            tilt,
            alerts
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        delivery_id,
        latest_data["sensor_time"],
        latest_data["lat"],
        latest_data["lon"],
        latest_data["temperature"],
        latest_data["humidity"],
        1 if latest_data["tilt"] else 0,
        json.dumps(latest_data["alerts"])
    ))

    conn.commit()
    conn.close()

def create_delivery_request_in_db(school_id, food_type, quantity, requested_delivery_time, special_notes):
    conn = get_db_connection()
    cur = conn.cursor()

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO delivery_requests (
            school_id,
            food_type,
            quantity,
            requested_delivery_time,
            special_notes,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 'requested', ?)
    """, (
        school_id,
        food_type,
        quantity,
        requested_delivery_time,
        special_notes,
        created_at
    ))

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    return request_id


def sensor_loop():
    while True:
        try:
            with data_lock:
                monitoring_active = latest_data["monitoring_active"]

            if monitoring_active:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Real sensor reads
                temperature = dht_device.temperature
                humidity = dht_device.humidity

                # If your tilt is reversed, change to:
                # tilt = not bool(tilt_sensor.value)
                tilt = bool(tilt_sensor.value)

                active_delivery_id = get_current_active_delivery()

                with data_lock:
                    latest_data["temperature"] = temperature
                    latest_data["humidity"] = humidity
                    latest_data["tilt"] = tilt
                    latest_data["sensor_time"] = now
                    latest_data["active_delivery_id"] = active_delivery_id

                    update_alerts()
                    save_monitoring_record()

                print(
                    "Time:", now,
                    "| Temp:", latest_data["temperature"],
                    "| Hum:", latest_data["humidity"],
                    "| Tilt:", latest_data["tilt"],
                    "| Active delivery:", latest_data["active_delivery_id"]
                )
            else:
                print("Monitoring paused")

        except Exception as e:
            print("Sensor error:", e)

        time.sleep(5)


@app.route("/data")
def data():
    with data_lock:
        return jsonify(latest_data)


@app.route("/location")
def location():
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with data_lock:
        latest_data["lat"] = lat
        latest_data["lon"] = lon
        latest_data["gps_time"] = now

    return "OK"


@app.route("/toggle-monitoring", methods=["POST"])
def toggle_monitoring():
    with data_lock:
        latest_data["monitoring_active"] = not latest_data["monitoring_active"]

    return jsonify({
        "monitoring_active": latest_data["monitoring_active"]
    })


@app.route("/start-monitoring", methods=["POST"])
def start_monitoring():
    with data_lock:
        latest_data["monitoring_active"] = True

    return jsonify({
        "monitoring_active": latest_data["monitoring_active"]
    })


@app.route("/stop-monitoring", methods=["POST"])
def stop_monitoring():
    with data_lock:
        latest_data["monitoring_active"] = False

    return jsonify({
        "monitoring_active": latest_data["monitoring_active"]
    })


@app.route("/active-delivery")
def active_delivery():
    active_delivery_id = get_current_active_delivery()

    with data_lock:
        latest_data["active_delivery_id"] = active_delivery_id

    return jsonify({
        "active_delivery_id": active_delivery_id
    })

@app.route("/start-delivery/<int:delivery_id>", methods=["POST"])
def start_delivery(delivery_id):
    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE deliveries
        SET status = 'active', start_time = ?
        WHERE id = ?
    """, (now, delivery_id))

    conn.commit()
    conn.close()

    with data_lock:
        latest_data["active_delivery_id"] = delivery_id

    return jsonify({
        "message": "Delivery started",
        "delivery_id": delivery_id
    })


@app.route("/stop-delivery/<int:delivery_id>", methods=["POST"])
def stop_delivery(delivery_id):
    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE deliveries
        SET status = 'completed', end_time = ?
        WHERE id = ?
    """, (now, delivery_id))

    conn.commit()
    conn.close()

    with data_lock:
        if latest_data["active_delivery_id"] == delivery_id:
            latest_data["active_delivery_id"] = None

    return jsonify({
        "message": "Delivery completed",
        "delivery_id": delivery_id
    })


@app.route("/create-request", methods=["POST"])
def create_request():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    school_id = data.get("school_id")
    food_type = data.get("food_type")
    quantity = data.get("quantity")
    requested_delivery_time = data.get("requested_delivery_time")
    special_notes = data.get("special_notes", "")

    if not school_id or not food_type or not quantity or not requested_delivery_time:
        return jsonify({
            "error": "Missing required fields: school_id, food_type, quantity, requested_delivery_time"
        }), 400

    try:
        request_id = create_delivery_request_in_db(
            school_id=school_id,
            food_type=food_type,
            quantity=quantity,
            requested_delivery_time=requested_delivery_time,
            special_notes=special_notes
        )

        return jsonify({
            "message": "Delivery request created successfully",
            "request_id": request_id
        }), 201

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/requests")
def get_requests():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, school_id, food_type, quantity, requested_delivery_time, special_notes, status, created_at
        FROM delivery_requests
        ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        result.append({
            "id": row["id"],
            "school_id": row["school_id"],
            "food_type": row["food_type"],
            "quantity": row["quantity"],
            "requested_delivery_time": row["requested_delivery_time"],
            "special_notes": row["special_notes"],
            "status": row["status"],
            "created_at": row["created_at"]
        })

    return jsonify(result)

@app.route("/assign-request", methods=["POST"])
def assign_request():
    data = request.get_json()

    request_id = data.get("request_id")
    driver_id = data.get("driver_id")

    if not request_id or not driver_id:
        return jsonify({"error": "Missing request_id or driver_id"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT school_id, food_type, quantity, special_notes
        FROM delivery_requests
        WHERE id = ?
    """, (request_id,))

    request_data = cur.fetchone()

    if not request_data:
        conn.close()
        return jsonify({"error": "Request not found"}), 404

    school_id = request_data["school_id"]
    food_type = request_data["food_type"]
    quantity = request_data["quantity"]
    notes = request_data["special_notes"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO deliveries (
            driver_id,
            school_id,
            food_type,
            quantity,
            status,
            notes,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        driver_id,
        school_id,
        food_type,
        quantity,
        "pending",
        notes,
        now
    ))

    delivery_id = cur.lastrowid

    cur.execute("""
        UPDATE delivery_requests
        SET status = 'assigned'
        WHERE id = ?
    """, (request_id,))

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Request assigned successfully",
        "delivery_id": delivery_id
    }), 201


@app.route("/history-v2")
def history_v2():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM monitoring_records
        ORDER BY id DESC
        LIMIT 20
    """)

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        alerts_raw = row["alerts"]

        if alerts_raw:
            try:
                alerts = json.loads(alerts_raw)
            except Exception:
                alerts = [alerts_raw]
        else:
            alerts = []

        result.append({
            "id": row["id"],
            "delivery_id": row["delivery_id"],
            "timestamp": row["timestamp"],
            "lat": row["latitude"],
            "lon": row["longitude"],
            "temperature": row["temperature"],
            "humidity": row["humidity"],
            "tilt": bool(row["tilt"]),
            "alerts": alerts
        })

    return jsonify(result)

@app.route("/driver-deliveries/<int:driver_id>")
def get_driver_deliveries(driver_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, driver_id, school_id, food_type, quantity, status, start_time, end_time, notes, created_at
        FROM deliveries
        WHERE driver_id = ?
        ORDER BY id DESC
    """, (driver_id,))

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        result.append({
            "id": row["id"],
            "driver_id": row["driver_id"],
            "school_id": row["school_id"],
            "food_type": row["food_type"],
            "quantity": row["quantity"],
            "status": row["status"],
            "start_time": row["start_time"],
            "end_time": row["end_time"],
            "notes": row["notes"],
            "created_at": row["created_at"]
        })

    return jsonify(result)

@app.route("/start-delivery", methods=["POST"])
def start_delivery_post():
    data = request.get_json()

    if not data or "delivery_id" not in data:
        return jsonify({"error": "Missing delivery_id"}), 400

    delivery_id = data["delivery_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE deliveries
        SET status = 'active', start_time = ?
        WHERE id = ?
    """, (now, delivery_id))

    conn.commit()
    conn.close()

    with data_lock:
        latest_data["active_delivery_id"] = delivery_id

    return jsonify({
        "message": "Delivery started",
        "delivery_id": delivery_id
    })



@app.route("/stop-delivery", methods=["POST"])
def stop_delivery_post():
    data = request.get_json()

    if not data or "delivery_id" not in data:
        return jsonify({"error": "Missing delivery_id"}), 400

    delivery_id = data["delivery_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE deliveries
        SET status = 'completed', end_time = ?
        WHERE id = ?
    """, (now, delivery_id))

    conn.commit()
    conn.close()

    with data_lock:
        if latest_data["active_delivery_id"] == delivery_id:
            latest_data["active_delivery_id"] = None

    return jsonify({
        "message": "Delivery completed",
        "delivery_id": delivery_id
    })



if __name__ == "__main__":
    thread = threading.Thread(target=sensor_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5000)
