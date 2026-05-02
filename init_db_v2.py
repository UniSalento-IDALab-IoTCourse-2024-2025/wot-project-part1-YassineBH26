import sqlite3
from datetime import datetime

DB_FILE = "iot_data_v2.db"


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    return conn


def create_tables():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS drivers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE,
        phone TEXT,
        status TEXT DEFAULT 'available',
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schools (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE,
        phone TEXT,
        address TEXT,
        created_at TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        driver_id INTEGER NOT NULL,
        school_id INTEGER NOT NULL,
        food_type TEXT NOT NULL,
        quantity INTEGER,
        status TEXT DEFAULT 'pending',
        start_time TEXT,
        end_time TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (driver_id) REFERENCES drivers(id),
        FOREIGN KEY (school_id) REFERENCES schools(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS monitoring_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        delivery_id INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        latitude TEXT,
        longitude TEXT,
        temperature REAL,
        humidity REAL,
        tilt INTEGER,
        alerts TEXT,
        FOREIGN KEY (delivery_id) REFERENCES deliveries(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS delivery_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        school_id INTEGER NOT NULL,
        food_type TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        requested_delivery_time TEXT NOT NULL,
        special_notes TEXT,
        status TEXT DEFAULT 'requested',
        created_at TEXT NOT NULL,
        FOREIGN KEY (school_id) REFERENCES schools(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        delivery_id INTEGER NOT NULL,
        school_id INTEGER NOT NULL,
        overall_score INTEGER NOT NULL,
        food_quality_score INTEGER,
        packaging_score INTEGER,
        comment TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (delivery_id) REFERENCES deliveries(id),
        FOREIGN KEY (school_id) REFERENCES schools(id)
    )
    """)

    conn.commit()
    conn.close()


def insert_sample_drivers():
    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sample_drivers = [
        ("Mario Rossi", "mario.rossi@example.com", "1111111111", "available", now),
        ("Luca Bianchi", "luca.bianchi@example.com", "2222222222", "available", now)
    ]

    for driver in sample_drivers:
        cur.execute("""
        INSERT OR IGNORE INTO drivers (full_name, email, phone, status, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, driver)

    conn.commit()
    conn.close()


def insert_sample_schools():
    conn = get_db_connection()
    cur = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sample_schools = [
        ("Scuola Primaria Lecce Centro", "lecce.centro@example.com", "3333333333", "Via Roma 10, Lecce", now),
        ("Scuola Primaria Sant'Oronzo", "santoronzo@example.com", "4444444444", "Via Napoli 25, Lecce", now)
    ]

    for school in sample_schools:
        cur.execute("""
        INSERT OR IGNORE INTO schools (name, email, phone, address, created_at)
        VALUES (?, ?, ?, ?, ?)
        """, school)

    conn.commit()
    conn.close()


def show_table_counts():
    conn = get_db_connection()
    cur = conn.cursor()

    tables = [
        "drivers",
        "schools",
        "deliveries",
        "monitoring_records",
        "delivery_requests",
        "ratings"
    ]

    for table in tables:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        count = cur.fetchone()[0]
        print(f"{table}: {count} rows")

    conn.close()


if __name__ == "__main__":
    create_tables()
    insert_sample_drivers()
    insert_sample_schools()
    show_table_counts()
    print("Database V2 setup completed successfully.")
