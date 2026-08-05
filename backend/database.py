import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

# Локально — обычный файл рядом с кодом. На Render (платный тариф) сюда
# передаётся путь на подключённый персистентный диск, например /var/data/portfolio.db.
DB_PATH = os.environ.get("DB_PATH", "portfolio.db")


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                deposit REAL NOT NULL DEFAULT 0,
                usdt_balance REAL NOT NULL DEFAULT 0,
                updated_at TEXT,
                total_invested REAL NOT NULL DEFAULT 0,
                realized_pnl REAL NOT NULL DEFAULT 0
            )
        """)
        # миграция для баз, созданных до появления новых колонок
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN updated_at TEXT")
        if "total_invested" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN total_invested REAL NOT NULL DEFAULT 0")
            # для уже существующих пользователей считаем, что всё вложенное — это текущий deposit
            conn.execute("UPDATE users SET total_invested = deposit WHERE total_invested = 0")
        if "realized_pnl" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN realized_pnl REAL NOT NULL DEFAULT 0")
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
            conn.execute(
                "INSERT INTO users (telegram_id, deposit, usdt_balance, total_invested, realized_pnl) "
                "VALUES (?,0,0,0,0)",
                (telegram_id,),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        return row


def set_deposit(telegram_id: int, deposit: float):
    """Задать стартовый депозит. Считается вложенным капиталом только при первом
    запуске (когда депозит ещё не был задан) — так повторное открытие шага 1
    не портит учёт прибыли."""
    with get_conn() as conn:
        row = conn.execute("SELECT deposit, total_invested FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        is_first_time = row is None or row["deposit"] == 0
        new_total_invested = deposit if is_first_time else row["total_invested"]
        conn.execute(
            "UPDATE users SET deposit=?, usdt_balance=?, total_invested=? WHERE telegram_id=?",
            (deposit, deposit, new_total_invested, telegram_id),
        )
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
    """Добавить новый актив или увеличить существующий (на этапе первичной настройки).
    Себестоимость (buy_price) пересчитывается как средневзвешенная."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT * FROM assets WHERE telegram_id=? AND name=?", (telegram_id, name)
        ).fetchone()
        if existing is None:
            conn.execute("""
                INSERT INTO assets (telegram_id, name, target_pct, quantity, buy_price, current_price)
                VALUES (?,?,?,?,?,?)
            """, (telegram_id, name, target_pct, quantity, price, price))
        else:
            new_qty = existing["quantity"] + quantity
            new_avg_price = (
                (existing["quantity"] * existing["buy_price"] + quantity * price) / new_qty
                if new_qty > 0 else price
            )
            conn.execute("""
                UPDATE assets SET quantity=?, buy_price=?, current_price=?, target_pct=?
                WHERE telegram_id=? AND name=?
            """, (new_qty, new_avg_price, price, target_pct, telegram_id, name))
        usdt = get_usdt(telegram_id)
        conn.execute("UPDATE users SET usdt_balance=? WHERE telegram_id=?", (usdt - spent, telegram_id))
        conn.commit()


def get_assets(telegram_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM assets WHERE telegram_id=?", (telegram_id,)).fetchall()
        return [dict(r) for r in rows]


def delete_asset(telegram_id: int, name: str, refund_to_usdt: bool):
    """Удалить актив. Если refund_to_usdt=True, текущая стоимость актива
    зачисляется в USDT-баланс, а разница со средней ценой покупки фиксируется
    как реализованная прибыль/убыток (как будто продали в рынок)."""
    with get_conn() as conn:
        asset = conn.execute(
            "SELECT * FROM assets WHERE telegram_id=? AND name=?", (telegram_id, name)
        ).fetchone()
        if asset is None:
            return
        if refund_to_usdt:
            value = asset["quantity"] * asset["current_price"]
            pnl = asset["quantity"] * (asset["current_price"] - asset["buy_price"])
            usdt = get_usdt(telegram_id)
            row = conn.execute("SELECT realized_pnl FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            conn.execute(
                "UPDATE users SET usdt_balance=?, realized_pnl=? WHERE telegram_id=?",
                (usdt + value, row["realized_pnl"] + pnl, telegram_id),
            )
        conn.execute("DELETE FROM assets WHERE telegram_id=? AND name=?", (telegram_id, name))
        conn.commit()


def add_usdt(telegram_id: int, amount: float):
    """Пополнить свободный USDT-баланс (довнесение денег для ликвидности/ребаланса).
    Это внешний капитал — учитывается в total_invested, а не в прибыли."""
    with get_conn() as conn:
        row = conn.execute("SELECT usdt_balance, total_invested FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
        conn.execute(
            "UPDATE users SET usdt_balance=?, total_invested=? WHERE telegram_id=?",
            (row["usdt_balance"] + amount, row["total_invested"] + amount, telegram_id),
        )
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
    """Выполнить рекомендацию:
    sell — уменьшить кол-во актива, пополнить USDT, зафиксировать реализованную прибыль
           (себестоимость проданной части не меняется у оставшегося количества);
    buy  — увеличить кол-во актива, списать USDT, пересчитать среднюю себестоимость."""
    with get_conn() as conn:
        asset = conn.execute(
            "SELECT * FROM assets WHERE telegram_id=? AND name=?", (telegram_id, name)
        ).fetchone()
        if asset is None:
            return
        usdt = get_usdt(telegram_id)
        new_buy_price = asset["buy_price"]

        if action == "sell":
            new_qty = max(asset["quantity"] - qty, 0)
            new_usdt = usdt + value
            pnl = qty * (asset["current_price"] - asset["buy_price"])
            row = conn.execute("SELECT realized_pnl FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
            conn.execute("UPDATE users SET realized_pnl=? WHERE telegram_id=?", (row["realized_pnl"] + pnl, telegram_id))
        elif action == "buy":
            new_qty = asset["quantity"] + qty
            new_usdt = max(usdt - value, 0)
            new_buy_price = (
                (asset["quantity"] * asset["buy_price"] + qty * asset["current_price"]) / new_qty
                if new_qty > 0 else asset["current_price"]
            )
        else:
            return

        conn.execute(
            "UPDATE assets SET quantity=?, buy_price=? WHERE telegram_id=? AND name=?",
            (new_qty, new_buy_price, telegram_id, name),
        )
        conn.execute("UPDATE users SET usdt_balance=? WHERE telegram_id=?", (new_usdt, telegram_id))
        conn.commit()
