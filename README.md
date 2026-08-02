# Telegram Mini App — Portfolio Ledger

Приложение открывается прямо внутри Telegram (Mini App). Логика:

1. Вводите депозит.
2. Добавляете 5–10 активов (название, цена, target % в портфеле) — приложение
   само считает, сколько купить каждого, остаток от депозита лежит в USDT.
3. Позже обновляете цену любого актива — приложение пересчитывает доли и:
   - если доля актива выросла на **5+ процентных пунктов** выше target →
     предлагает **продать** излишек (вырученное уходит в USDT);
   - если доля упала на **10+ процентных пунктов** ниже target →
     предлагает **докупить** актив за счёт свободного USDT.

## 0. Локальный запуск для теста (на своём компьютере, в Chrome)

Домен, SSL и Telegram-бот для этого не нужны — есть встроенный тестовый режим
(`DEV_MODE`), который отключает проверку подписи Telegram и пишет данные под
одним тестовым пользователем.

```bash
cd telegram-portfolio-app/backend
python3 -m venv venv

# Windows: venv\Scripts\activate
source venv/bin/activate

pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Откройте в Chrome: **http://127.0.0.1:8000**

Вверху появится жёлтый баннер «ЛОКАЛЬНЫЙ ТЕСТОВЫЙ РЕЖИМ» — это нормально,
значит вы не внутри Telegram, но всё остальное (депозит, добавление активов,
пересчёт при изменении цены, кнопки «Продать»/«Купить») работает точно так же,
как будет работать в реальном Mini App.

Данные хранятся в `backend/portfolio.db`. Если хотите начать тест заново —
просто удалите этот файл и перезапустите сервер.

Когда протестируете и всё устроит — переходите к разделам ниже, чтобы
выложить на сервер и подключить к реальному боту. `DEV_MODE` там сам
выключится, как только вы впишете `BOT_TOKEN` в `.env` (или явно поставите
`DEV_MODE=0`).

## 1. Что нужно перед стартом (боевой деплой)

- Свой сервер (VPS/выделенный) с Ubuntu/Debian, доступный из интернета.
- **Домен** (поддомена достаточно, например `portfolio.вашдомен.ru`), с A-записью,
  указывающей на IP сервера. Telegram Mini App **требует HTTPS** — без домена
  и сертификата открыть его в Telegram не получится.
- Python 3.10+.

## 2. Разворачиваем backend на сервере

```bash
sudo mkdir -p /opt/telegram-portfolio-app
sudo chown $USER /opt/telegram-portfolio-app
# скопируйте на сервер содержимое этого архива в /opt/telegram-portfolio-app
cd /opt/telegram-portfolio-app/backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env   # впишите BOT_TOKEN (получите его в шаге 4)
```

Проверка вручную:
```bash
uvicorn main:app --host 127.0.0.1 --port 8000
```
Откройте `http://127.0.0.1:8000` на сервере (curl) — должен вернуться HTML.

## 3. Автозапуск через systemd (чтобы работало всегда, даже после перезагрузки)

```bash
sudo cp /opt/telegram-portfolio-app/portfolio-app.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable portfolio-app
sudo systemctl start portfolio-app
sudo systemctl status portfolio-app   # убедитесь, что active (running)
```

## 4. Домен + HTTPS через nginx и Let's Encrypt

```bash
sudo apt install nginx certbot python3-certbot-nginx -y

sudo cp /opt/telegram-portfolio-app/nginx.conf.example /etc/nginx/sites-available/portfolio-app
sudo nano /etc/nginx/sites-available/portfolio-app   # замените your-domain.com на ваш домен
sudo ln -s /etc/nginx/sites-available/portfolio-app /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

sudo certbot --nginx -d your-domain.com   # выпустит SSL и сам допишет конфиг nginx
```

После этого `https://your-domain.com` должен открывать приложение в браузере.

## 5. Создаём бота и подключаем Mini App

1. В Telegram напишите **@BotFather** → `/newbot`, задайте имя — получите **токен**,
   впишите его в `.env` (шаг 2) и перезапустите сервис:
   `sudo systemctl restart portfolio-app`.
2. В @BotFather: `/mybots` → выберите бота → **Bot Settings** → **Menu Button** →
   **Configure Menu Button** → отправьте `https://your-domain.com` и название кнопки,
   например `Портфель`.
3. Откройте вашего бота в Telegram — рядом с полем ввода сообщения появится кнопка
   меню, которая открывает приложение.

Готово — бот работает 24/7 как системный сервис, обновляет цены и считает
ребалансировку при каждом изменении.

## 6. Данные

Хранятся в SQLite-файле `backend/portfolio.db`, создаётся автоматически.
Каждый пользователь Telegram видит только свой портфель (проверяется подписью
`initData`, которую Telegram передаёт при открытии приложения).

## Структура проекта

```
backend/
  main.py        — FastAPI-сервер и все /api/* эндпоинты
  calc.py         — логика ребалансировки (пороги 5% / 10%)
  auth.py         — проверка подлинности данных Telegram
  database.py     — SQLite-хранилище
  requirements.txt
frontend/
  index.html      — весь интерфейс Mini App (кольцо распределения + карточки активов)
portfolio-app.service   — systemd unit
nginx.conf.example      — конфиг nginx
```

## Что можно улучшить дальше (по желанию)

- Возможность удалять/редактировать target % без пересоздания портфеля.
- История сделок (сейчас хранится только текущее состояние).
- Уведомления от самого бота ("актив X отклонился от target") — потребует
  отдельного процесса-бота с long polling или webhook в дополнение к Mini App.
