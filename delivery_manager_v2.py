import sqlite3
from datetime import datetime

DB_FILE = "iot_data_v2.db"


def get_db_connection():
    return sqlite3.connect(DB_FILE)


def create_delivery(driver_id, school_id, food_type, quantity, notes=""):
    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur.execute("""
    INSERT INTO deliveries (
        driver_id, school_id, food_type, quantity, status, notes, created_at
    ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
    """, (driver_id, school_id, food_type, quantity, notes, now))

    delivery_id = cur.lastrowid

    conn.commit()
    conn.close()

    print(f"Delivery created with id {delivery_id}")
    return delivery_id


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

    print(f"Delivery {delivery_id} started")


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

    print(f"Delivery {delivery_id} completed")


def get_active_delivery():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, driver_id, school_id, food_type, quantity, status, start_time, end_time, notes, created_at
    FROM deliveries
    WHERE status = 'active'
    ORDER BY id DESC
    LIMIT 1
    """)

    row = cur.fetchone()
    conn.close()

    if row is None:
        print("No active delivery")
        return None

    delivery = {
        "id": row[0],
        "driver_id": row[1],
        "school_id": row[2],
        "food_type": row[3],
        "quantity": row[4],
        "status": row[5],
        "start_time": row[6],
        "end_time": row[7],
        "notes": row[8],
        "created_at": row[9]
    }

    print("Active delivery:", delivery)
    return delivery


def show_all_deliveries():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    SELECT id, driver_id, school_id, food_type, quantity, status, start_time, end_time
    FROM deliveries
    ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No deliveries found")
        return

    for row in rows:
        print(row)


if __name__ == "__main__":
    print("1. Create sample delivery")
    print("2. Start delivery id 1")
    print("3. Stop delivery id 1")
    print("4. Show active delivery")
    print("5. Show all deliveries")

    choice = input("Choose an option: ").strip()

    if choice == "1":
        create_delivery(driver_id=1, school_id=1, food_type="Pasta", quantity=30, notes="Lunch delivery")
    elif choice == "2":
        start_delivery(1)
    elif choice == "3":
        stop_delivery(1)
    elif choice == "4":
        get_active_delivery()
    elif choice == "5":
        show_all_deliveries()
    else:
        print("Invalid option")
