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

last_saved_state = {
    "delivery_id": None,
    "temperature": None,
    "humidity": None,
    "tilt": None,
    "alerts": []
}

data_lock = threading.Lock()


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_request_id_column():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(deliveries)")
    columns = [col["name"] for col in cur.fetchall()]

    if "request_id" not in columns:
        cur.execute("ALTER TABLE deliveries ADD COLUMN request_id INTEGER")

    conn.commit()
    conn.close()

def update_alerts():
    alerts = []

    if latest_data["temperature"] is not None and latest_data["temperature"] > 26:
        alerts.append("High temperature")

    if latest_data["humidity"] is not None and latest_data["humidity"] > 60:
        alerts.append("High humidity")

    if latest_data["tilt"]:
        alerts.append("Box tilted")

    latest_data["alerts"] = alerts


def get_current_active_delivery():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id
        FROM deliveries
        WHERE status = 'in_progress'
        ORDER BY id DESC
        LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    return row["id"] if row else None


def save_monitoring_record():
    global last_saved_state

    delivery_id = latest_data["active_delivery_id"]

    if delivery_id is None:
        return

    current_temp = latest_data["temperature"]
    current_humidity = latest_data["humidity"]
    current_tilt = latest_data["tilt"]

    if current_temp is None or current_humidity is None:
        return

    event_alerts = []

    new_delivery = last_saved_state["delivery_id"] != delivery_id

    if new_delivery:
        event_alerts.append("Monitoring started")

    if last_saved_state["temperature"] is not None:
        temp_diff = current_temp - last_saved_state["temperature"]

        if abs(temp_diff) >= 1:
            if temp_diff > 0:
                event_alerts.append(f"Temperature increased by {temp_diff:.1f} C")
            else:
                event_alerts.append(f"Temperature decreased by {abs(temp_diff):.1f} C")

    if last_saved_state["humidity"] is not None:
        humidity_diff = current_humidity - last_saved_state["humidity"]

        if abs(humidity_diff) >= 5:
            if humidity_diff > 0:
                event_alerts.append(f"Humidity increased by {humidity_diff:.1f}%")
            else:
                event_alerts.append(f"Humidity decreased by {abs(humidity_diff):.1f}%")

    if last_saved_state["tilt"] is not None and current_tilt != last_saved_state["tilt"]:
        if current_tilt:
            event_alerts.append("Box tilted")
        else:
            event_alerts.append("Box returned to normal position")

    if new_delivery and current_tilt:
        event_alerts.append("Box tilted")

    event_alerts = list(dict.fromkeys(event_alerts))

    if not event_alerts:
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
        current_temp,
        current_humidity,
        1 if current_tilt else 0,
        json.dumps(event_alerts)
    ))

    conn.commit()
    conn.close()

    last_saved_state = {
        "delivery_id": delivery_id,
        "temperature": current_temp,
        "humidity": current_humidity,
        "tilt": current_tilt,
        "alerts": latest_data["alerts"].copy()
    }

    print("Monitoring event saved:", event_alerts)


def sensor_loop():
    while True:
        try:
            with data_lock:
                monitoring_active = latest_data["monitoring_active"]

            if monitoring_active:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                temperature = dht_device.temperature
                humidity = dht_device.humidity
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
                    "| Temp:", temperature,
                    "| Hum:", humidity,
                    "| Tilt:", tilt,
                    "| Active delivery:", active_delivery_id
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

    print("GPS:", lat, lon)
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
        return jsonify({"error": "Missing required fields"}), 400

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

    return jsonify({
        "message": "Delivery request created successfully",
        "request_id": request_id
    }), 201


@app.route("/requests")
def get_requests():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            dr.id,
            dr.school_id,
            dr.food_type,
            dr.quantity,
            dr.requested_delivery_time,
            dr.special_notes,
            dr.status,
            dr.created_at,
            d.id AS delivery_id,
            d.driver_id
        FROM delivery_requests dr
        LEFT JOIN deliveries d
            ON d.request_id = dr.id
        ORDER BY dr.id DESC
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
            "created_at": row["created_at"],
            "delivery_id": row["delivery_id"],
            "driver_id": row["driver_id"]
        })

    return jsonify(result)

@app.route("/assign-request", methods=["POST"])
def assign_request():
    data = request.get_json()

    request_id = data.get("request_id")
    driver_id = data.get("driver_id")

    if not request_id or not driver_id:
        return jsonify({"error": "request_id and driver_id are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM delivery_requests
        WHERE id = ?
    """, (request_id,))

    delivery_request = cur.fetchone()

    if delivery_request is None:
        conn.close()
        return jsonify({"error": "Delivery request not found"}), 404

    if delivery_request["status"] != "requested":
        conn.close()
        return jsonify({"error": "Only requested deliveries can be assigned"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        INSERT INTO deliveries (
            request_id,
            driver_id,
            school_id,
            food_type,
            quantity,
            status,
            start_time,
            end_time,
            notes,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, 'assigned', NULL, NULL, ?, ?)
    """, (
        request_id,
        driver_id,
        delivery_request["school_id"],
        delivery_request["food_type"],
        delivery_request["quantity"],
        delivery_request["special_notes"],
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


@app.route("/driver-deliveries/<int:driver_id>")
def get_driver_deliveries(driver_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, request_id, driver_id, school_id, food_type, quantity,
               status, start_time, end_time, notes, created_at
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
            "request_id": row["request_id"],
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
def start_delivery():
    data = request.get_json()

    if not data or "delivery_id" not in data:
        return jsonify({"error": "Missing delivery_id"}), 400

    delivery_id = data["delivery_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM deliveries
        WHERE id = ?
    """, (delivery_id,))

    delivery = cur.fetchone()

    if delivery is None:
        conn.close()
        return jsonify({"error": "Delivery not found"}), 404

    if delivery["status"] != "assigned":
        conn.close()
        return jsonify({"error": "Only assigned deliveries can be started"}), 400

    cur.execute("""
        SELECT id
        FROM deliveries
        WHERE driver_id = ?
        AND status = 'in_progress'
        LIMIT 1
    """, (delivery["driver_id"],))

    active_driver_delivery = cur.fetchone()

    if active_driver_delivery is not None:
        conn.close()
        return jsonify({
            "error": "Impossible: another delivery is already in progress"
        }), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE deliveries
        SET status = 'in_progress',
            start_time = ?
        WHERE id = ?
    """, (now, delivery_id))

    if delivery["request_id"] is not None:
        cur.execute("""
            UPDATE delivery_requests
            SET status = 'in_progress'
            WHERE id = ?
        """, (delivery["request_id"],))

    conn.commit()
    conn.close()

    with data_lock:
        latest_data["active_delivery_id"] = delivery_id
        latest_data["monitoring_active"] = True

    return jsonify({
        "message": "Delivery started successfully",
        "delivery_id": delivery_id
    })


@app.route("/stop-delivery", methods=["POST"])
def stop_delivery():
    data = request.get_json()

    if not data or "delivery_id" not in data:
        return jsonify({"error": "Missing delivery_id"}), 400

    delivery_id = data["delivery_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM deliveries
        WHERE id = ?
    """, (delivery_id,))

    delivery = cur.fetchone()

    if delivery is None:
        conn.close()
        return jsonify({"error": "Delivery not found"}), 404

    if delivery["status"] != "in_progress":
        conn.close()
        return jsonify({"error": "Only in-progress deliveries can be completed"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
        UPDATE deliveries
        SET status = 'completed',
            end_time = ?
        WHERE id = ?
    """, (now, delivery_id))

    if delivery["request_id"] is not None:
        cur.execute("""
            UPDATE delivery_requests
            SET status = 'completed'
            WHERE id = ?
        """, (delivery["request_id"],))

    conn.commit()
    conn.close()

    with data_lock:
        if latest_data["active_delivery_id"] == delivery_id:
            latest_data["active_delivery_id"] = None

    return jsonify({
        "message": "Delivery completed successfully",
        "delivery_id": delivery_id
    })

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


if __name__ == "__main__":
    ensure_request_id_column()

    thread = threading.Thread(target=sensor_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5000)
