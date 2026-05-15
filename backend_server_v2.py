from flask import Flask, request, jsonify, session
from flask_cors import CORS
from gpiozero import DigitalInputDevice
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import threading
import time
import sqlite3
import json
import adafruit_dht
import board
import urllib.parse
import urllib.request
import math

app = Flask(__name__)

app.secret_key = "iot_exam_project_secret_key_change_later"

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = False

CORS(app, supports_credentials=True)

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
    "active_delivery_id": None,
}

last_saved_state = {
    "delivery_id": None,
    "temperature": None,
    "humidity": None,
    "tilt": None,
    "alerts": [],
}

data_lock = threading.Lock()


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def get_current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, username, role, linked_entity_id
        FROM users
        WHERE id = ?
        """,
        (user_id,),
    )

    user = cur.fetchone()
    conn.close()

    if user is None:
        return None

    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "linked_entity_id": user["linked_entity_id"],
    }


def login_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        user = get_current_user()

        if user is None:
            return jsonify({"error": "Authentication required"}), 401

        return route_function(*args, **kwargs)

    return wrapper
def role_required(*allowed_roles):
    def decorator(route_function):
        @wraps(route_function)
        def wrapper(*args, **kwargs):
            user = get_current_user()

            if user is None:
                return jsonify({"error": "Authentication required"}), 401

            if user["role"] not in allowed_roles:
                return jsonify({"error": "Forbidden"}), 403

            return route_function(*args, **kwargs)

        return wrapper

    return decorator


@app.route("/auth/me", methods=["GET"])
def auth_me():
    user = get_current_user()
    return jsonify({"user": user})


@app.route("/auth/check-username", methods=["POST"])
def auth_check_username():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    username = data.get("username")

    if not username:
        return jsonify({"error": "Username is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id
        FROM users
        WHERE username = ?
        """,
        (username,),
    )

    user = cur.fetchone()
    conn.close()

    if user is None:
        return jsonify({"exists": False}), 404

    return jsonify({"exists": True})


@app.route("/auth/login", methods=["POST"])
def auth_login():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, username, password_hash, role, linked_entity_id
        FROM users
        WHERE username = ?
        """,
        (username,),
    )

    user = cur.fetchone()
    conn.close()

    if user is None:
        return jsonify({"error": "Invalid username or password"}), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["user_id"] = user["id"]

    return jsonify(
        {
            "message": "Login successful",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "role": user["role"],
                "linked_entity_id": user["linked_entity_id"],
            },
        }
    )
    
@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    return jsonify({"message": "Logout successful"})


@app.route("/auth/signup", methods=["POST"])
@login_required
@role_required("admin")
def auth_signup():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    username = data.get("username")
    password = data.get("password")
    role = data.get("role")
    name = data.get("name")
    email = data.get("email", "")
    phone = data.get("phone", "")
    address = data.get("address", "")
    latitude = data.get("latitude")
    longitude = data.get("longitude")

    if not username or not password or not role or not name:
        return (
            jsonify({"error": "username, password, role, and name are required"}),
            400,
        )

    if role not in ["driver", "school"]:
        return jsonify({"error": "Only driver and school signup are allowed"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        if role == "driver":
            cur.execute(
                """
                INSERT INTO drivers (
                    full_name,
                    email,
                    phone,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, 'available', ?)
                """,
                (name, email, phone, now),
            )

            linked_entity_id = cur.lastrowid

        else:
            cur.execute(
                """
                INSERT INTO schools (
                    name,
                    email,
                    phone,
                    address,
                    latitude,
                    longitude,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, email, phone, address, latitude, longitude, now),
            )

            linked_entity_id = cur.lastrowid

        cur.execute(
            """
            INSERT INTO users (
                username,
                password_hash,
                role,
                linked_entity_id,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, generate_password_hash(password), role, linked_entity_id, now),
        )

        conn.commit()

    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return jsonify({"error": "Username or email already exists"}), 409

    conn.close()

    return (
        jsonify(
            {
                "message": "Signup successful",
                "role": role,
                "linked_entity_id": linked_entity_id,
            }
        ),
        201,
    )

@app.route("/admin/users")
@login_required
@role_required("admin")
def admin_users():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            u.id,
            u.username,
            u.role,
            u.linked_entity_id,
            u.created_at,

            CASE
                WHEN u.role = 'driver' THEN d.full_name
                WHEN u.role = 'school' THEN s.name
                ELSE u.username
            END AS display_name,

            CASE
                WHEN u.role = 'driver' THEN d.email
                WHEN u.role = 'school' THEN s.email
                ELSE ''
            END AS email,

            CASE
                WHEN u.role = 'driver' THEN d.phone
                WHEN u.role = 'school' THEN s.phone
                ELSE ''
            END AS phone,

            CASE
                WHEN u.role = 'school' THEN s.address
                ELSE ''
            END AS address,

            CASE
                WHEN u.role = 'school' THEN s.latitude
                ELSE NULL
            END AS latitude,

            CASE
                WHEN u.role = 'school' THEN s.longitude
                ELSE NULL
            END AS longitude

        FROM users u
        LEFT JOIN drivers d
            ON u.role = 'driver'
           AND u.linked_entity_id = d.id
        LEFT JOIN schools s
            ON u.role = 'school'
           AND u.linked_entity_id = s.id
        ORDER BY u.id ASC
        """
    )

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        result.append(
            {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "linked_entity_id": row["linked_entity_id"],
                "created_at": row["created_at"],
                "display_name": row["display_name"],
                "email": row["email"],
                "phone": row["phone"],
                "address": row["address"],
                "latitude": row["latitude"],
                "longitude": row["longitude"],
            }
        )

    return jsonify(result)


@app.route("/admin/geocode-address", methods=["POST"])
@login_required
@role_required("admin")
def geocode_address():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    address = data.get("address", "").strip()

    if not address:
        return jsonify({"error": "Address is required"}), 400

    query = urllib.parse.urlencode(
        {
            "q": address,
            "format": "json",
            "addressdetails": 1,
            "limit": 5,
        }
    )

    url = f"https://nominatim.openstreetmap.org/search?{query}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "RaqebFood-IoT-Exam-Project/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            raw_data = response.read().decode("utf-8")
            results = json.loads(raw_data)

    except Exception as error:
        return jsonify({"error": f"Geocoding failed: {str(error)}"}), 500

    candidates = []

    for item in results:
        candidates.append(
            {
                "display_name": item.get("display_name"),
                "latitude": float(item.get("lat")),
                "longitude": float(item.get("lon")),
            }
        )

    return jsonify({"address": address, "candidates": candidates})


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

    cur.execute(
        """
        SELECT id
        FROM deliveries
        WHERE status = 'in_progress'
        ORDER BY id DESC
        LIMIT 1
        """
    )

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

    if (
        last_saved_state["tilt"] is not None
        and current_tilt != last_saved_state["tilt"]
    ):
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

    cur.execute(
        """
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
        """,
        (
            delivery_id,
            latest_data["sensor_time"],
            latest_data["lat"],
            latest_data["lon"],
            current_temp,
            current_humidity,
            1 if current_tilt else 0,
            json.dumps(event_alerts),
        ),
    )

    conn.commit()
    conn.close()

    last_saved_state = {
        "delivery_id": delivery_id,
        "temperature": current_temp,
        "humidity": current_humidity,
        "tilt": current_tilt,
        "alerts": latest_data["alerts"].copy(),
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
                    "Time:",
                    now,
                    "| Temp:",
                    temperature,
                    "| Hum:",
                    humidity,
                    "| Tilt:",
                    tilt,
                    "| Active delivery:",
                    active_delivery_id,
                )
            else:
                print("Monitoring paused")

        except Exception as e:
            print("Sensor error:", e)

        time.sleep(5)


@app.route("/data")
@login_required
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
@login_required
@role_required("admin")
def toggle_monitoring():
    with data_lock:
        latest_data["monitoring_active"] = not latest_data["monitoring_active"]

    return jsonify({"monitoring_active": latest_data["monitoring_active"]})


@app.route("/start-monitoring", methods=["POST"])
@login_required
@role_required("admin")
def start_monitoring():
    with data_lock:
        latest_data["monitoring_active"] = True

    return jsonify({"monitoring_active": latest_data["monitoring_active"]})


@app.route("/stop-monitoring", methods=["POST"])
@login_required
@role_required("admin")
def stop_monitoring():
    with data_lock:
        latest_data["monitoring_active"] = False

    return jsonify({"monitoring_active": latest_data["monitoring_active"]})


@app.route("/active-delivery")
@login_required
def active_delivery():
    active_delivery_id = get_current_active_delivery()

    with data_lock:
        latest_data["active_delivery_id"] = active_delivery_id

    return jsonify({"active_delivery_id": active_delivery_id})


@app.route("/create-request", methods=["POST"])
@login_required
@role_required("school")
def create_request():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No JSON body provided"}), 400

    user = get_current_user()
    school_id = user["linked_entity_id"]
    food_type = data.get("food_type")
    quantity = data.get("quantity")
    requested_delivery_time = data.get("requested_delivery_time")
    special_notes = data.get("special_notes", "")

    if not food_type or not quantity or not requested_delivery_time:
        return jsonify({"error": "Missing required fields"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
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
        """,
        (
            school_id,
            food_type,
            quantity,
            requested_delivery_time,
            special_notes,
            created_at,
        ),
    )

    request_id = cur.lastrowid

    conn.commit()
    conn.close()

    return (
        jsonify(
            {
                "message": "Delivery request created successfully",
                "request_id": request_id,
            }
        ),
        201,
    )
    
    
@app.route("/requests")
@login_required
@role_required("admin")
def get_requests():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 
            dr.id,
            dr.school_id,
            s.name AS school_name,
            dr.food_type,
            dr.quantity,
            dr.requested_delivery_time,
            dr.special_notes,
            dr.status,
            dr.created_at,
            d.id AS delivery_id,
            d.driver_id
        FROM delivery_requests dr
        LEFT JOIN schools s
            ON s.id = dr.school_id
        LEFT JOIN deliveries d
            ON d.request_id = dr.id
        ORDER BY dr.id DESC
        """
    )

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        result.append(
            {
                "id": row["id"],
                "school_id": row["school_id"],
                "school_name": row["school_name"],
                "food_type": row["food_type"],
                "quantity": row["quantity"],
                "requested_delivery_time": row["requested_delivery_time"],
                "special_notes": row["special_notes"],
                "status": row["status"],
                "created_at": row["created_at"],
                "delivery_id": row["delivery_id"],
                "driver_id": row["driver_id"],
            }
        )

    return jsonify(result)


@app.route("/school-requests")
@login_required
@role_required("school")
def get_school_requests():
    user = get_current_user()
    school_id = user["linked_entity_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
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
        WHERE dr.school_id = ?
        ORDER BY dr.id DESC
        """,
        (school_id,),
    )

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        result.append(
            {
                "id": row["id"],
                "school_id": row["school_id"],
                "food_type": row["food_type"],
                "quantity": row["quantity"],
                "requested_delivery_time": row["requested_delivery_time"],
                "special_notes": row["special_notes"],
                "status": row["status"],
                "created_at": row["created_at"],
                "delivery_id": row["delivery_id"],
                "driver_id": row["driver_id"],
            }
        )

    return jsonify(result)


@app.route("/drivers")
@login_required
@role_required("admin")
def get_drivers():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            d.id,
            d.full_name,
            d.email,
            d.phone,
            d.status,
            d.created_at,
            u.username
        FROM drivers d
        INNER JOIN users u
            ON u.role = 'driver'
           AND u.linked_entity_id = d.id
        ORDER BY d.full_name ASC
        """
    )

    drivers = cur.fetchall()
    conn.close()

    return jsonify([dict(driver) for driver in drivers])


@app.route("/assign-request", methods=["POST"])
@login_required
@role_required("admin")
def assign_request():
    data = request.get_json()

    request_id = data.get("request_id")
    driver_id = data.get("driver_id")

    if not request_id or not driver_id:
        return jsonify({"error": "request_id and driver_id are required"}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM delivery_requests
        WHERE id = ?
        """,
        (request_id,),
    )

    delivery_request = cur.fetchone()

    if delivery_request is None:
        conn.close()
        return jsonify({"error": "Delivery request not found"}), 404

    if delivery_request["status"] != "requested":
        conn.close()
        return jsonify({"error": "Only requested deliveries can be assigned"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
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
        """,
        (
            request_id,
            driver_id,
            delivery_request["school_id"],
            delivery_request["food_type"],
            delivery_request["quantity"],
            delivery_request["special_notes"],
            now,
        ),
    )

    delivery_id = cur.lastrowid

    cur.execute(
        """
        UPDATE delivery_requests
        SET status = 'assigned'
        WHERE id = ?
        """,
        (request_id,),
    )

    conn.commit()
    conn.close()

    return (
        jsonify(
            {
                "message": "Request assigned successfully",
                "delivery_id": delivery_id,
            }
        ),
        201,
    )
    
@app.route("/driver-deliveries")
@login_required
@role_required("driver")
def get_driver_deliveries():
    user = get_current_user()
    driver_id = user["linked_entity_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, request_id, driver_id, school_id, food_type, quantity,
               status, start_time, end_time, notes, created_at
        FROM deliveries
        WHERE driver_id = ?
        ORDER BY id DESC
        """,
        (driver_id,),
    )

    rows = cur.fetchall()
    conn.close()

    result = []

    for row in rows:
        result.append(
            {
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
                "created_at": row["created_at"],
            }
        )

    return jsonify(result)


@app.route("/start-delivery", methods=["POST"])
@login_required
@role_required("driver")
def start_delivery():
    data = request.get_json()

    if not data or "delivery_id" not in data:
        return jsonify({"error": "Missing delivery_id"}), 400

    delivery_id = data["delivery_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM deliveries
        WHERE id = ?
        """,
        (delivery_id,),
    )

    delivery = cur.fetchone()

    user = get_current_user()
    driver_id = user["linked_entity_id"]

    if delivery is not None and delivery["driver_id"] != driver_id:
        conn.close()
        return (
            jsonify({"error": "Forbidden: this delivery is not assigned to you"}),
            403,
        )

    if delivery is None:
        conn.close()
        return jsonify({"error": "Delivery not found"}), 404

    if delivery["status"] != "assigned":
        conn.close()
        return jsonify({"error": "Only assigned deliveries can be started"}), 400

    cur.execute(
        """
        SELECT id
        FROM deliveries
        WHERE driver_id = ?
        AND status = 'in_progress'
        LIMIT 1
        """,
        (delivery["driver_id"],),
    )

    active_driver_delivery = cur.fetchone()

    if active_driver_delivery is not None:
        conn.close()
        return (
            jsonify({"error": "Impossible: another delivery is already in progress"}),
            400,
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        UPDATE deliveries
        SET status = 'in_progress',
            start_time = ?
        WHERE id = ?
        """,
        (now, delivery_id),
    )

    if delivery["request_id"] is not None:
        cur.execute(
            """
            UPDATE delivery_requests
            SET status = 'in_progress'
            WHERE id = ?
            """,
            (delivery["request_id"],),
        )

    conn.commit()
    conn.close()

    with data_lock:
        latest_data["active_delivery_id"] = delivery_id
        latest_data["monitoring_active"] = True

    return jsonify(
        {
            "message": "Delivery started successfully",
            "delivery_id": delivery_id,
        }
    )
    
@app.route("/stop-delivery", methods=["POST"])
@login_required
@role_required("driver")
def stop_delivery():
    data = request.get_json()

    if not data or "delivery_id" not in data:
        return jsonify({"error": "Missing delivery_id"}), 400

    delivery_id = data["delivery_id"]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM deliveries
        WHERE id = ?
        """,
        (delivery_id,),
    )

    delivery = cur.fetchone()

    user = get_current_user()
    driver_id = user["linked_entity_id"]

    if delivery is not None and delivery["driver_id"] != driver_id:
        conn.close()
        return (
            jsonify({"error": "Forbidden: this delivery is not assigned to you"}),
            403,
        )

    if delivery is None:
        conn.close()
        return jsonify({"error": "Delivery not found"}), 404

    if delivery["status"] != "in_progress":
        conn.close()
        return jsonify({"error": "Only in-progress deliveries can be completed"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(
        """
        UPDATE deliveries
        SET status = 'completed',
            end_time = ?
        WHERE id = ?
        """,
        (now, delivery_id),
    )

    if delivery["request_id"] is not None:
        cur.execute(
            """
            UPDATE delivery_requests
            SET status = 'completed'
            WHERE id = ?
            """,
            (delivery["request_id"],),
        )

    conn.commit()
    conn.close()

    with data_lock:
        if latest_data["active_delivery_id"] == delivery_id:
            latest_data["active_delivery_id"] = None
            latest_data["monitoring_active"] = False

    return jsonify(
        {
            "message": "Delivery completed successfully",
            "delivery_id": delivery_id,
        }
    )


@app.route("/history-v2")
@login_required
def history_v2():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM monitoring_records
        ORDER BY id DESC
        LIMIT 20
        """
    )

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

        result.append(
            {
                "id": row["id"],
                "delivery_id": row["delivery_id"],
                "timestamp": row["timestamp"],
                "lat": row["latitude"],
                "lon": row["longitude"],
                "temperature": row["temperature"],
                "humidity": row["humidity"],
                "tilt": bool(row["tilt"]),
                "alerts": alerts,
            }
        )

    return jsonify(result)
def calculate_haversine_km(lat1, lon1, lat2, lon2):
    earth_radius_km = 6371.0

    lat1_rad = math.radians(float(lat1))
    lon1_rad = math.radians(float(lon1))
    lat2_rad = math.radians(float(lat2))
    lon2_rad = math.radians(float(lon2))

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(delta_lon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius_km * c


def get_osrm_driving_distance(start_lat, start_lon, end_lat, end_lon):
    coordinates = f"{start_lon},{start_lat};{end_lon},{end_lat}"

    query = urllib.parse.urlencode(
        {
            "overview": "false",
            "steps": "false",
        }
    )

    url = f"https://router.project-osrm.org/route/v1/driving/{coordinates}?{query}"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "RaqebFood-IoT-Exam-Project/1.0"},
    )

    with urllib.request.urlopen(req, timeout=8) as response:
        raw_data = response.read().decode("utf-8")
        data = json.loads(raw_data)

    if data.get("code") != "Ok" or not data.get("routes"):
        raise Exception("No driving route found")

    route = data["routes"][0]

    distance_km = round(route["distance"] / 1000, 2)
    duration_minutes = round(route["duration"] / 60, 1)

    return distance_km, duration_minutes

@app.route("/delivery-report/<int:delivery_id>")
@login_required
@role_required("admin")
def delivery_report(delivery_id):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT 
            d.id,
            d.request_id,
            d.driver_id,
            d.school_id,
            d.food_type,
            d.quantity,
            d.status,
            d.start_time,
            d.end_time,
            d.notes,
            d.created_at,
            dr.full_name AS driver_name,
            s.name AS school_name,
            s.address AS school_address,
            s.latitude AS school_latitude,
            s.longitude AS school_longitude
        FROM deliveries d
        LEFT JOIN drivers dr
            ON dr.id = d.driver_id
        LEFT JOIN schools s
            ON s.id = d.school_id
        WHERE d.id = ?
        """,
        (delivery_id,),
    )

    delivery = cur.fetchone()

    if delivery is None:
        conn.close()
        return jsonify({"error": "Delivery not found"}), 404

    cur.execute(
        """
        SELECT *
        FROM monitoring_records
        WHERE delivery_id = ?
        ORDER BY timestamp ASC
        """,
        (delivery_id,),
    )

    records = cur.fetchall()
    conn.close()

    def parse_time(value):
        if not value:
            return None

        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def seconds_to_minutes(seconds):
        return round(seconds / 60, 1)

    start_dt = parse_time(delivery["start_time"])
    end_dt = parse_time(delivery["end_time"])

    duration_minutes = None
    duration_label = "Not available"

    if start_dt and end_dt:
        duration_seconds = int((end_dt - start_dt).total_seconds())
        duration_minutes = round(duration_seconds / 60, 1)

        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        seconds = duration_seconds % 60

        if hours > 0:
            duration_label = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            duration_label = f"{minutes}m {seconds}s"
        else:
            duration_label = f"{seconds}s"

    total_events = len(records)
    alert_count = 0
    temperature_alerts = 0
    humidity_alerts = 0
    tilt_alerts = 0

    max_temperature = None
    min_temperature = None
    max_humidity = None
    min_humidity = None

    temperature_risk_seconds = 0
    humidity_risk_seconds = 0
    tilt_risk_seconds = 0

    delivery_distance_km = None
    delivery_distance_type = "not_available"
    delivery_distance_note = "GPS data or school coordinates are not available."
    estimated_driving_duration_minutes = None

    event_rows = []
    for index, record in enumerate(records):
        temperature = record["temperature"]
        humidity = record["humidity"]
        tilt = bool(record["tilt"])

        if temperature is not None:
            max_temperature = (
                temperature
                if max_temperature is None
                else max(max_temperature, temperature)
            )
            min_temperature = (
                temperature
                if min_temperature is None
                else min(min_temperature, temperature)
            )

        if humidity is not None:
            max_humidity = (
                humidity if max_humidity is None else max(max_humidity, humidity)
            )
            min_humidity = (
                humidity if min_humidity is None else min(min_humidity, humidity)
            )

        alerts_raw = record["alerts"]

        if alerts_raw:
            try:
                alerts = json.loads(alerts_raw)
            except Exception:
                alerts = [alerts_raw]
        else:
            alerts = []

        alert_count += len(alerts)

        for alert in alerts:
            alert_lower = alert.lower()

            if "temperature" in alert_lower:
                temperature_alerts += 1

            if "humidity" in alert_lower:
                humidity_alerts += 1

            if "tilt" in alert_lower:
                tilt_alerts += 1

        current_time = parse_time(record["timestamp"])

        if current_time is not None:
            if index + 1 < len(records):
                next_time = parse_time(records[index + 1]["timestamp"])
            else:
                next_time = end_dt

            if next_time is not None:
                interval_seconds = int((next_time - current_time).total_seconds())

                if interval_seconds > 0:
                    if temperature is not None and temperature > 26:
                        temperature_risk_seconds += interval_seconds

                    if humidity is not None and humidity > 60:
                        humidity_risk_seconds += interval_seconds

                    if tilt:
                        tilt_risk_seconds += interval_seconds

        event_rows.append(
            {
                "id": record["id"],
                "timestamp": record["timestamp"],
                "temperature": temperature,
                "humidity": humidity,
                "tilt": tilt,
                "lat": record["latitude"],
                "lon": record["longitude"],
                "alerts": alerts,
            }
        )
    first_gps_record = None

    for record in records:
        if record["latitude"] is not None and record["longitude"] is not None:
            first_gps_record = record
            break

    school_latitude = delivery["school_latitude"]
    school_longitude = delivery["school_longitude"]

    if (
        first_gps_record is not None
        and school_latitude is not None
        and school_longitude is not None
    ):
        start_lat = first_gps_record["latitude"]
        start_lon = first_gps_record["longitude"]

        try:
            (
                delivery_distance_km,
                estimated_driving_duration_minutes,
            ) = get_osrm_driving_distance(
                start_lat,
                start_lon,
                school_latitude,
                school_longitude,
            )

            delivery_distance_type = "driving"
            delivery_distance_note = (
                "Estimated road distance from the first recorded driver GPS position "
                "to the geocoded school location."
            )

        except Exception:
            delivery_distance_km = round(
                calculate_haversine_km(
                    start_lat,
                    start_lon,
                    school_latitude,
                    school_longitude,
                ),
                2,
            )

            estimated_driving_duration_minutes = None
            delivery_distance_type = "straight_line_fallback"
            delivery_distance_note = (
                "Driving route was not available, so straight-line distance was used."
            )

    temperature_risk_minutes = seconds_to_minutes(temperature_risk_seconds)
    humidity_risk_minutes = seconds_to_minutes(humidity_risk_seconds)
    tilt_risk_minutes = seconds_to_minutes(tilt_risk_seconds)

    return jsonify(
        {
            "delivery": {
                "id": delivery["id"],
                "request_id": delivery["request_id"],
                "driver_id": delivery["driver_id"],
                "driver_name": delivery["driver_name"],
                "school_id": delivery["school_id"],
                "school_name": delivery["school_name"],
                "school_address": delivery["school_address"],
                "school_latitude": delivery["school_latitude"],
                "school_longitude": delivery["school_longitude"],
                "food_type": delivery["food_type"],
                "quantity": delivery["quantity"],
                "status": delivery["status"],
                "start_time": delivery["start_time"],
                "end_time": delivery["end_time"],
                "notes": delivery["notes"],
                "created_at": delivery["created_at"],
            },
            
            "summary": {
                "duration_minutes": duration_minutes,
                "duration_label": duration_label,
                "total_events": total_events,
                "alert_count": alert_count,
                "temperature_alerts": temperature_alerts,
                "humidity_alerts": humidity_alerts,
                "tilt_alerts": tilt_alerts,
                "temperature_risk_minutes": temperature_risk_minutes,
                "humidity_risk_minutes": humidity_risk_minutes,
                "tilt_risk_minutes": tilt_risk_minutes,
                "delivery_distance_km": delivery_distance_km,
                "delivery_distance_type": delivery_distance_type,
                "delivery_distance_note": delivery_distance_note,
                "estimated_driving_duration_minutes": estimated_driving_duration_minutes,
                "max_temperature": max_temperature,
                "min_temperature": min_temperature,
                "max_humidity": max_humidity,
                "min_humidity": min_humidity,
            },
            "events": event_rows,
        }
    )


if __name__ == "__main__":
    ensure_request_id_column()

    thread = threading.Thread(target=sensor_loop, daemon=True)
    thread.start()

    app.run(host="0.0.0.0", port=5000)


