"""
Логика расчёта портфеля и ребалансировки.

Правила:
- Если текущая доля актива превышает target на 3 и более процентных пунктов —
  предлагаем ПРОДАТЬ часть актива, чтобы вернуть его к target (вырученное — в USDT).
- Если текущая доля актива ниже target на 3 и более процентных пунктов —
  предлагаем ДОКУПИТЬ актив за счёт свободного USDT, чтобы вернуть его к target.
"""

SELL_THRESHOLD = 3.0   # процентных пункта превышения target
BUY_THRESHOLD = 3.0    # процентных пункта падения ниже target


def compute_portfolio(assets: list[dict], usdt_balance: float) -> dict:
    """
    assets: [{name, quantity, current_price, target_pct, buy_price}, ...]
    Возвращает полную картину портфеля с рекомендациями по каждому активу.
    """
    assets_value = sum(a["quantity"] * a["current_price"] for a in assets)
    total_value = assets_value + usdt_balance

    rows = []
    for a in assets:
        value = a["quantity"] * a["current_price"]
        current_pct = (value / total_value * 100) if total_value > 0 else 0.0
        diff = current_pct - a["target_pct"]

        action = None
        action_qty = 0.0
        action_value = 0.0

        if diff >= SELL_THRESHOLD:
            target_value = a["target_pct"] / 100 * total_value
            sell_value = value - target_value
            sell_qty = sell_value / a["current_price"] if a["current_price"] > 0 else 0
            action = "sell"
            action_qty = sell_qty
            action_value = sell_value
        elif diff <= -BUY_THRESHOLD:
            target_value = a["target_pct"] / 100 * total_value
            buy_value = target_value - value
            buy_value = min(buy_value, usdt_balance)  # не больше, чем есть свободных USDT
            buy_qty = buy_value / a["current_price"] if a["current_price"] > 0 else 0
            if buy_value > 0:
                action = "buy"
                action_qty = buy_qty
                action_value = buy_value

        rows.append({
            "name": a["name"],
            "quantity": round(a["quantity"], 6),
            "current_price": a["current_price"],
            "buy_price": a["buy_price"],
            "value": round(value, 2),
            "current_pct": round(current_pct, 2),
            "target_pct": a["target_pct"],
            "diff_pct": round(diff, 2),
            "action": action,               # "sell" / "buy" / None
            "action_qty": round(action_qty, 6),
            "action_value": round(action_value, 2),
        })

    return {
        "assets": rows,
        "usdt_balance": round(usdt_balance, 2),
        "total_value": round(total_value, 2),
    }
