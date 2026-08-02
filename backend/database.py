import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = "portfolio.db"


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                deposit REAL NOT NULL DEFAULT 0,
                usdt_balance REAL NOT NULL DEFAULT 0,
                updated_at TEXT
            )
        """)
        # миграция для баз, созданных до появления updated_at
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                target_pct REAL NOT NULL,
                quantity REAL NOT NULL,
                buy_price REAL NOT NULL,
                current_price REAL NOT NULL,
                UNIQUE(telegram_id, name)
            )
        """)
        conn.commit()


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def touch(telegram_id: int):
    """Обновить метку времени последнего изменения портфеля."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET updated_at=? WHERE telegram_id=?",
            (datetime.now(timezone.utc).isoformat(), telegram_id),
        )
        conn.commit()


def get_or_create_user(telegram_id: int) -> sqlite3.Row:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO users (telegram_id, deposit, usdt_balance) VALUES (?,0,0)", (telegram_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return row


def set_deposit(telegram_id: int, deposit: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET deposit=?, usdt_balance=? WHERE telegram_id=?",
            (deposit, deposit, telegram_id),
        )
        # деньги, ещё не разложенные по активам, лежат в usdt_balance
        conn.commit()


def get_usdt(telegram_id: int) -> float:
    with get_conn() as conn:
        row = conn.execute("SELECT usdt_balance FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return row["usdt_balance"] if row else 0.0


def set_usdt(telegram_id: int, usdt_balance: float):
    with get_conn() as conn:
        conn.execute("UPDATE users SET usdt_balance=? WHERE telegram_id=?", (usdt_balance, telegram_id))
        conn.commit()


def add_asset(telegram_id: int, name: str, price: float, target_pct: float, quantity: float, spent: float):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO assets (telegram_id, name, target_pct, quantity, buy_price, current_price)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(telegram_id, name) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                current_price = excluded.current_price
        """, (telegram_id, name, target_pct, quantity, price, price))
        usdt = get_usdt(telegram_id)
        conn.execute("UPDATE users SET usdt_balance=? WHERE telegram_id=?", (usdt - spent, telegram_id))
        conn.commit()


def get_assets(telegram_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM assets WHERE telegram_id=?", (telegram_id,)).fetchall()
        return [dict(r) for r in rows]


def delete_asset(telegram_id: int, name: str, refund_to_usdt: bool):
    """Удалить актив. Если refund_to_usdt=True, текущая стоимость актива
    (кол-во * текущая цена) зачисляется в USDT-баланс (как будто продали в рынок)."""
    with get_conn() as conn:
        asset = conn.execute(
            "SELECT * FROM assets WHERE telegram_id=? AND name=?", (telegram_id, name)
        ).fetchone()
        if asset is None:
            return
        if refund_to_usdt:
            value = asset["quantity"] * asset["current_price"]
            usdt = get_usdt(telegram_id)
            conn.execute("UPDATE users SET usdt_balance=? WHERE telegram_id=?", (usdt + value, telegram_id))
        conn.execute("DELETE FROM assets WHERE telegram_id=? AND name=?", (telegram_id, name))
        conn.commit()


def add_usdt(telegram_id: int, amount: float):
    """Пополнить свободный USDT-баланс (например, довнесение денег для ликвидности)."""
    with get_conn() as conn:
        usdt = get_usdt(telegram_id)
        conn.execute("UPDATE users SET usdt_balance=? WHERE telegram_id=?", (usdt + amount, telegram_id))
        conn.commit()


def update_target(telegram_id: int, name: str, target_pct: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE assets SET target_pct=? WHERE telegram_id=? AND name=?",
            (target_pct, telegram_id, name),
        )
        conn.commit()


def update_price(telegram_id: int, name: str, price: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE assets SET current_price=? WHERE telegram_id=? AND name=?",
            (price, telegram_id, name),
        )
        conn.commit()


def apply_trade(telegram_id: int, name: str, action: str, qty: float, value: float):
    """Выполнить рекомендацию: sell — уменьшить кол-во актива и пополнить USDT;
    buy — увеличить кол-во актива и списать USDT."""
    with get_conn() as conn:
        asset = conn.execute(
            "SELECT * FROM assets WHERE telegram_id=? AND name=?", (telegram_id, name)
        ).fetchone()
        if asset is None:
            return
        usdt = get_usdt(telegram_id)
        if action == "sell":
            new_qty = max(asset["quantity"] - qty, 0)
            new_usdt = usdt + value
        elif action == "buy":
            new_qty = asset["quantity"] + qty
            new_usdt = max(usdt - value, 0)
        else:
            return
        conn.execute("UPDATE assets SET quantity=? WHERE telegram_id=? AND name=?", (new_qty, telegram_id, name))
        conn.execute("UPDATE users SET usdt_balance=? WHERE telegram_id=?", (new_usdt, telegram_id))
        conn.commit()
