import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Переменная окружения {name} не задана. "
            "Скопируйте .env.example в .env и заполните значения."
        )
    return value


BOT_TOKEN = _require("BOT_TOKEN")
ADMIN_ID = int(_require("ADMIN_ID"))

# Канал: числовой ID (например -1004412818716) или @username
_raw_channel = _require("CHANNEL_ID")
try:
    CHANNEL_ID = int(_raw_channel)
except ValueError:
    CHANNEL_ID = _raw_channel  # строка вида "@my_channel"

# --- Деплой / режим запуска ---
# webhook | polling (для Render/Tranger удобнее webhook + healthcheck)
WEBHOOK_MODE = os.getenv("WEBHOOK_MODE", "false").lower() in ("1", "true", "yes")
# Публичный URL приложения (Render выдаёт его автоматически)
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
PORT = int(os.getenv("PORT", "10000"))  # Render сам задаёт PORT
DB_NAME = os.getenv("DB_NAME", "releases.db")
