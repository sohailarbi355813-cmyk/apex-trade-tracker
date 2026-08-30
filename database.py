import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'trades.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pair TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            tp_price REAL NOT NULL,
            sl_price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'WAITING',
            message_id INTEGER,
            channel_id INTEGER,
            public_message_id INTEGER,
            public_channel_id INTEGER,
            author_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN public_message_id INTEGER")
        cursor.execute("ALTER TABLE trades ADD COLUMN public_channel_id INTEGER")
    except sqlite3.OperationalError:
        pass # Columns already exist
        
    try:
        cursor.execute("ALTER TABLE trades ADD COLUMN active_log_message_id INTEGER")
        cursor.execute("ALTER TABLE trades ADD COLUMN active_log_channel_id INTEGER")
    except sqlite3.OperationalError:
        pass # Columns already exist
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    ''', (key, str(value)))
    conn.commit()
    conn.close()

def insert_trade(pair, direction, entry, tp, sl, author_name, status='WAITING'):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (pair, direction, entry_price, tp_price, sl_price, author_name, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (pair.upper(), direction.upper(), float(entry), float(tp), float(sl), author_name, status.upper()))
    trade_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return trade_id

def update_message_ids(trade_id, message_id, channel_id, pub_msg_id=None, pub_ch_id=None, active_msg_id=None, active_ch_id=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trades
        SET message_id = ?, channel_id = ?, public_message_id = ?, public_channel_id = ?, active_log_message_id = ?, active_log_channel_id = ?
        WHERE id = ?
    ''', (message_id, channel_id, pub_msg_id, pub_ch_id, active_msg_id, active_ch_id, trade_id))
    conn.commit()
    conn.close()

def update_trade_status(trade_id, status):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trades
        SET status = ?
        WHERE id = ?
    ''', (status.upper(), trade_id))
    conn.commit()
    conn.close()

def update_trade_sl(trade_id, new_sl):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trades
        SET sl_price = ?
        WHERE id = ?
    ''', (float(new_sl), trade_id))
    conn.commit()
    conn.close()

def update_trade_tp(trade_id, new_tp):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE trades
        SET tp_price = ?
        WHERE id = ?
    ''', (float(new_tp), trade_id))
    conn.commit()
    conn.close()

def get_open_trades():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM trades WHERE status IN ('ACTIVE', 'BE', 'WAITING', 'CANCELLED')
    ''')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
    
def get_trade(trade_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM trades WHERE id = ?
    ''', (trade_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
