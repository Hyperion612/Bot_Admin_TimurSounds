"""Вспомогательные функции бота: безопасный Markdown, клавиатуры."""
import re


def safe_markdown(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2 в свободном тексте (названия треков, лейблы и т.п.).

    Переменные шаблонов ({{ text }} и пр.) подставляются уже экранированными,
    поэтому публикация не падает из-за случайных скобок/точки/дефиса в названии.
    """
    escape_chars = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


def sanitize_post_html(html: str) -> str:
    """Убирает неразрешённые HTML-теги, оставляя разрешённый Telegram-набор."""
    allowed = {"b", "i", "u", "s", "a", "code", "pre", "blockquote", "br"}
    def repl(m):
        tag = m.group(1).lower().lstrip("/")
        return m.group(0) if tag in allowed else ""
    return re.sub(r"<(/?[a-zA-Z]+)[^>]*>", repl, html)


def main_menu_keyboard() -> "object":
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎵 Треки", callback_data="menu:tracks"),
            InlineKeyboardButton(text="📝 Посты", callback_data="menu:posts"),
        ],
        [
            InlineKeyboardButton(text="⚙️ Шаблон", callback_data="menu:template"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
        ],
    ])


def publish_keyboard():
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data="publish"),
            InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])
