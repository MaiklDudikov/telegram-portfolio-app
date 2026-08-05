import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import auth
import calc
import database as db

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# DEV_MODE=1 (или пустой BOT_TOKEN) — локальный запуск в браузере без Telegram:
# подпись initData не проверяется, все данные пишутся под одним тестовым пользователем.
DEV_MODE = os.environ.get("DEV_MODE", "1" if not BOT_TOKEN else "0") == "1"
DEV_USER_ID = 999999
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def check_user(init_data: str) -> int:
    if DEV_MODE:
        return DEV_USER_ID
    if not BOT_TOKEN:
        raise HTTPException(500, "BOT_TOKEN не задан на сервере")
    user = auth.validate_init_data(init_data, BOT_TOKEN)
    if not user:
        raise HTTPException(401, "Неверные данные Telegram (initData)")
    return user["telegram_id"]


@app.on_event("startup")
def startup():
    db.init_db()


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


# ---------- Pydantic-схемы запросов ----------

class DepositIn(BaseModel):
    init_data: str
    deposit: float


class AssetIn(BaseModel):
    init_data: str
    name: str
    price: float
    target_pct: float


class PriceIn(BaseModel):
    init_data: str
    name: str
    price: float


class ExecuteIn(BaseModel):
    init_data: str
    name: str


class DeleteAssetIn(BaseModel):
    init_data: str
    name: str
    refund_to_usdt: bool = True


class AddUsdtIn(BaseModel):
    init_data: str
    amount: float


class TargetIn(BaseModel):
    init_data: str
    name: str
    target_pct: float


class PortfolioIn(BaseModel):
    init_data: str


def full_portfolio(tg_id: int) -> dict:
    user = db.get_or_create_user(tg_id)
    assets = db.get_assets(tg_id)
    result = calc.compute_portfolio(assets, user["usdt_balance"])
    result["deposit"] = user["deposit"]
    result["updated_at"] = user["updated_at"]
    result["total_invested"] = round(user["total_invested"], 2)
    result["realized_pnl"] = round(user["realized_pnl"], 2)
    result["total_pnl"] = round(result["total_value"] - user["total_invested"], 2)
    return result


# ---------- Эндпоинты ----------

@app.post("/api/deposit")
def api_deposit(body: DepositIn):
    tg_id = check_user(body.init_data)
    db.get_or_create_user(tg_id)
    db.set_deposit(tg_id, body.deposit)
    db.touch(tg_id)
    return {"ok": True}


@app.post("/api/asset")
def api_add_asset(body: AssetIn):
    tg_id = check_user(body.init_data)
    db.get_or_create_user(tg_id)

    usdt = db.get_usdt(tg_id)
    spend = db.get_or_create_user(tg_id)["deposit"] * (body.target_pct / 100)
    spend = min(spend, usdt)  # нельзя потратить больше свободного USDT
    if body.price <= 0:
        raise HTTPException(400, "Цена должна быть больше нуля")
    quantity = spend / body.price

    db.add_asset(tg_id, body.name.strip(), body.price, body.target_pct, quantity, spend)
    db.touch(tg_id)
    return {"ok": True, "quantity": quantity, "spent": spend}


@app.post("/api/price")
def api_update_price(body: PriceIn):
    tg_id = check_user(body.init_data)
    db.update_price(tg_id, body.name.strip(), body.price)
    db.touch(tg_id)
    return full_portfolio(tg_id)


@app.post("/api/execute")
def api_execute(body: ExecuteIn):
    tg_id = check_user(body.init_data)
    assets = db.get_assets(tg_id)
    usdt = db.get_usdt(tg_id)
    portfolio = calc.compute_portfolio(assets, usdt)

    row = next((r for r in portfolio["assets"] if r["name"] == body.name), None)
    if not row or not row["action"]:
        raise HTTPException(400, "Для этого актива нет рекомендации")

    db.apply_trade(tg_id, body.name, row["action"], row["action_qty"], row["action_value"])
    db.touch(tg_id)
    return full_portfolio(tg_id)


@app.post("/api/asset/delete")
def api_delete_asset(body: DeleteAssetIn):
    tg_id = check_user(body.init_data)
    db.delete_asset(tg_id, body.name.strip(), body.refund_to_usdt)
    db.touch(tg_id)
    return full_portfolio(tg_id)


@app.post("/api/asset/target")
def api_update_target(body: TargetIn):
    tg_id = check_user(body.init_data)
    if body.target_pct <= 0:
        raise HTTPException(400, "target % должен быть больше нуля")
    db.update_target(tg_id, body.name.strip(), body.target_pct)
    db.touch(tg_id)
    return full_portfolio(tg_id)


@app.post("/api/usdt/add")
def api_add_usdt(body: AddUsdtIn):
    tg_id = check_user(body.init_data)
    if body.amount <= 0:
        raise HTTPException(400, "Сумма должна быть больше нуля")
    db.get_or_create_user(tg_id)
    db.add_usdt(tg_id, body.amount)
    db.touch(tg_id)
    return full_portfolio(tg_id)


@app.post("/api/portfolio")
def api_portfolio(body: PortfolioIn):
    tg_id = check_user(body.init_data)
    return full_portfolio(tg_id)
