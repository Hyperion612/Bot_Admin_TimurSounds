# ReleaseMate Bot 🎵

Telegram-бот для ведения музыкального канала: база релизов, шаблоны постов, годовщины, публикация в канал с подтверждением.

## Возможности

- **Треки** — `/addtrack` (пошаговый мастер или одной строкой), `/listtracks`, `/edittrack ID поле значение`, `/deltrack ID`
- **Посты** — `/announce текст` (черновик с кнопками ✅ Опубликовать / ✏️ / ❌), `/post текст` (сразу в канал)
- **Шаблоны Jinja2** — `/template`, `/settemplate` (с валидацией перед сохранением). Переменные: `{{ today }}`, `{{ now }}`, `{{ text }}`, `{{ next_track.artist }}`, `{{ days_left }}`, `{{ anniversaries }}`, `{{ plural_years(years) }}`
- **Умная публикация** — MarkdownV2 с автоэкранированием; если Telegram отверг разметку, пост уходит обычным текстом (никогда не теряется)
- **Миграция БД** — старая схема `tracks(name, …)` автоматически конвертируется в новую (`artist, title, type, label`)
- `/status` — сводка по базе, `/help`, `/cancel`, меню с inline-кнопками, регистрация команд в BotFather

## Локальный запуск

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # заполните BOT_TOKEN, ADMIN_ID, CHANNEL_ID
python bot.py
```

## Деплой на Render / Tranger Cloud

1. Создайте **Web Service** из этого репозитория:
   - Build command: `pip install -r requirements.txt`
   - Start command: `python bot.py`
   - Runtime: Python 3.12 (`runtime.txt` уже настроен; для Heroku-подобных платформ есть `Procfile`)
2. Задайте переменные окружения в панели хостинга:
   - `BOT_TOKEN`, `ADMIN_ID`, `CHANNEL_ID`
   - `WEBHOOK_MODE=true`
   - `PUBLIC_URL=https://<ваш-сервис>.onrender.com` (или домен Tranger Cloud)
   - `WEBHOOK_SECRET=<случайная длинная строка>`
   - `PORT` платформа задаёт сама
3. Health-check: `GET /healthz` → `ok` (используйте в настройках мониторинга).
4. Вебхуки регистрируются автоматически при старте (`drop_pending_updates=True`).

### Polling vs Webhook

| Режим | Когда выбирать |
|---|---|
| `WEBHOOK_MODE=false` (polling) | Хостинг не даёт публичный HTTPS-домен |
| `WEBHOOK_MODE=true` (webhook) | Рекомендуется для PaaS: переживает рестарты, не держит долгие соединения |

⚠️ **Персистентность**: файловая SQLite (`releases.db`) живёт только внутри контейнера и стирается при redeploy. Для сохранения базы подключите диск (Render Disks / volume в Tranger) и укажите `DB_NAME=/data/releases.db`, либо перенесите данные на PostgreSQL.

## Структура

```
bot.py          # хендлеры aiogram 3.x (Router + FSM), запуск polling/webhook
config.py       # переменные окружения
database.py     # aiosqlite + миграция схемы
utils.py        # экранирование MarkdownV2, клавиатуры
.env.example    # шаблон конфигурации
requirements.txt, runtime.txt, Procfile
```
