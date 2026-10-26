import asyncio
from datetime import date, datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from jinja2 import Template
import config
import database

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher()

def is_admin(message: types.Message) -> bool:
    return message.from_user.id == config.ADMIN_ID

def publish_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Опубликовать", callback_data="publish"),
            InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")
        ]
    ])

drafts = {}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_admin(message):
        return
    await message.answer(
        "🎵 *ReleaseMate Bot*\n\n"
        "Я помогаю вести музыкальный канал. Вот что я умею:\n\n"
        "📌 *Треки:*\n"
        "/addtrack — добавить новый трек\n"
        "/listtracks — список всех треков\n"
        "/deltrack ID — удалить трек\n"
        "/edittrack ID — изменить трек\n\n"
        "📝 *Посты:*\n"
        "/announce текст — создать черновик\n"
        "/post текст — сразу в канал\n\n"
        "⚙️ *Настройки:*\n"
        "/template — показать шаблон\n"
        "/settemplate — изменить шаблон\n"
        "/help — все команды",
        parse_mode="Markdown"
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if not is_admin(message):
        return
    await message.answer(
        "📋 *Все команды:*\n\n"
        "*Добавление трека:*\n"
        "`/addtrack` — интерактивное добавление\n"
        "Или одной строкой:\n"
        "`/addtrack Артист - Название (тип) | ГГГГ-ММ-ДД | Лейбл | ссылка`\n\n"
        "Пример:\n"
        "`/addtrack Timur - ./Hack (EP) | 2026-07-09 | TimurSounds | https://band.link/hackworld`\n\n"
        "*Управление треками:*\n"
        "/listtracks — показать все\n"
        "/deltrack ID — удалить\n"
        "/edittrack ID — изменить\n\n"
        "*Постинг:*\n"
        "/announce текст — черновик с подтверждением\n"
        "/post текст — сразу в канал\n\n"
        "*Шаблоны:*\n"
        "/template — текущий шаблон\n"
        "/settemplate — обновить\n\n"
        "В шаблоне можно использовать:\n"
        "`{{ today }}`, `{{ now }}`, `{{ text }}`\n"
        "`{{ next_track.artist }}`, `{{ next_track.title }}`\n"
        "`{{ next_track.type }}`, `{{ next_track.release_date }}`\n"
        "`{{ next_track.label }}`, `{{ next_track.link }}`\n"
        "`{{ days_left }}`, `{{ anniversaries }}`",
        parse_mode="Markdown"
    )

@dp.message(Command("addtrack"))
async def cmd_addtrack(message: types.Message):
    if not is_admin(message):
        return
    
    # Получаем весь текст после команды
    try:
        full_text = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.answer(
            "❌ Укажи данные трека.\n\n"
            "Формат:\n"
            "`/addtrack Артист - Название (тип) | ГГГГ-ММ-ДД | Лейбл | ссылка`\n\n"
            "Пример:\n"
            "`/addtrack Timur - ./Hack (EP) | 2026-07-09 | TimurSounds | https://band.link/hackworld`\n\n"
            "• Тип в скобках опционален: (EP), (Album), (Single), (LP)\n"
            "• Лейбл опционален\n"
            "• Ссылка опциональна",
            parse_mode="Markdown"
        )
        return
    
    try:
        parts = full_text.split("|")
        
        # Первая часть: Артист - Название (тип)
        artist_title = parts[0].strip()
        
        # Парсим артиста и название
        if " - " in artist_title:
            artist, title_and_type = artist_title.split(" - ", 1)
        else:
            await message.answer("❌ Укажи формат: Артист - Название")
            return
        
        # Извлекаем тип из скобок, если есть
        track_type = "single"  # по умолчанию
        if "(" in title_and_type and ")" in title_and_type:
            start = title_and_type.index("(")
            end = title_and_type.index(")")
            track_type = title_and_type[start+1:end].strip()
            title = (title_and_type[:start] + title_and_type[end+1:]).strip()
        else:
            title = title_and_type.strip()
        
        # Дата релиза (обязательно)
        if len(parts) < 2:
            await message.answer("❌ Укажи дату релиза после |")
            return
        
        release_date_str = parts[1].strip()
        # Проверяем формат даты
        date.fromisoformat(release_date_str)
        
        # Лейбл (опционально)
        label = parts[2].strip() if len(parts) > 2 else None
        
        # Ссылка (опционально)
        link = parts[3].strip() if len(parts) > 3 else None
        
        await database.add_track(
            artist=artist.strip(),
            title=title.strip(),
            track_type=track_type,
            release_date=release_date_str,
            label=label,
            link=link
        )
        
        # Подтверждение
        response = f"✅ Трек добавлен:\n\n"
        response += f"🎵 *{artist.strip()} - {title.strip()}*"
        if track_type != "single":
            response += f" ({track_type})"
        response += f"\n🗓 {release_date_str}"
        if label:
            response += f"\n🎧 {label}"
        if link:
            response += f"\n🔗 {link}"
        
        await message.answer(response, parse_mode="Markdown", disable_web_page_preview=True)
        
    except ValueError as e:
        await message.answer(f"❌ Ошибка в дате. Используй формат ГГГГ-ММ-ДД\nНапример: 2026-07-09")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\nПроверь формат команды.")

@dp.message(Command("listtracks"))
async def cmd_listtracks(message: types.Message):
    if not is_admin(message):
        return
    tracks = await database.get_all_tracks()
    if not tracks:
        await message.answer("📭 База треков пуста.")
        return
    
    response = "📋 *Треки в базе:*\n\n"
    for t in tracks:
        response += f"*{t['id']}.* {t['artist']} - {t['title']}"
        if t['type'] != 'single':
            response += f" ({t['type']})"
        response += f"\n   🗓 {t['release_date']}"
        if t['label']:
            response += f" | 🎧 {t['label']}"
        response += "\n"
        if t['link']:
            response += f"   🔗 {t['link']}\n"
        response += "\n"
    
    await message.answer(response, parse_mode="Markdown", disable_web_page_preview=True)

@dp.message(Command("deltrack"))
async def cmd_deltrack(message: types.Message):
    if not is_admin(message):
        return
    try:
        track_id = int(message.text.split()[1])
        await database.delete_track(track_id)
        await message.answer(f"🗑 Трек #{track_id} удалён.")
    except (IndexError, ValueError):
        await message.answer("Используй: /deltrack ID\nID можно посмотреть в /listtracks")

@dp.message(Command("edittrack"))
async def cmd_edittrack(message: types.Message):
    if not is_admin(message):
        return
    await message.answer(
        "✏️ Для редактирования трека:\n"
        "1. Удали старый трек: /deltrack ID\n"
        "2. Добавь новый: /addtrack ...\n\n"
        "ID трека можно найти в /listtracks"
    )

@dp.message(Command("template"))
async def cmd_show_template(message: types.Message):
    if not is_admin(message):
        return
    tpl = await database.get_template()
    # Экранируем для HTML
    escaped = tpl.replace("<", "&lt;").replace(">", "&gt;")
    await message.answer(
        f"📝 *Текущий шаблон:*\n\n<pre>{escaped}</pre>\n\n"
        f"*Доступные переменные:*\n"
        f"`{{{{ today }}}}` — сегодняшняя дата\n"
        f"`{{{{ now }}}}` — текущее время\n"
        f"`{{{{ text }}}}` — твой текст новости\n"
        f"`{{{{ next_track.artist }}}}` — артист ближайшего релиза\n"
        f"`{{{{ next_track.title }}}}` — название\n"
        f"`{{{{ next_track.type }}}}` — тип (EP/Single/Album)\n"
        f"`{{{{ next_track.release_date }}}}` — дата релиза\n"
        f"`{{{{ next_track.label }}}}` — лейбл\n"
        f"`{{{{ next_track.link }}}}` — ссылка\n"
        f"`{{{{ days_left }}}}` — дней до релиза\n"
        f"`{{{{ anniversaries }}}}` — список годовщин",
        parse_mode="HTML"
    )

@dp.message(Command("settemplate"))
async def cmd_set_template(message: types.Message):
    if not is_admin(message):
        return
    try:
        new_tpl = message.text.split(maxsplit=1)[1]
        await database.set_template(new_tpl)
        await message.answer("✅ Шаблон обновлён. Проверь: /template")
    except IndexError:
        await message.answer(
            "Используй: /settemplate <новый шаблон>\n\n"
            "Или с новой строки:\n"
            "/settemplate\n"
            "Твой шаблон...",
            parse_mode="Markdown"
        )

async def generate_post(text: str) -> str:
    """Генерирует текст поста по шаблону"""
    today = date.today()
    now = datetime.now().strftime("%H:%M")
    tpl_str = await database.get_template()
    template = Template(tpl_str)

    next_track = await database.get_next_release(today)
    days_left = None
    if next_track:
        release_date = date.fromisoformat(next_track['release_date'])
        days_left = (release_date - today).days

    anniversaries = await database.get_anniversaries(today)

    rendered = template.render(
        today=today.strftime("%d.%m.%Y"),
        now=now,
        text=text,
        next_track=next_track,
        days_left=days_left,
        anniversaries=anniversaries
    )
    return rendered

@dp.message(Command("announce"))
async def cmd_announce(message: types.Message):
    if not is_admin(message):
        return
    try:
        text = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.answer("Добавь текст после команды: /announce Текст новости")
        return

    post_text = await generate_post(text)
    msg = await message.answer(post_text, reply_markup=publish_keyboard(), 
                               parse_mode="Markdown", disable_web_page_preview=True)
    drafts[msg.message_id] = post_text

@dp.message(Command("post"))
async def cmd_post(message: types.Message):
    if not is_admin(message):
        return
    try:
        text = message.text.split(maxsplit=1)[1]
    except IndexError:
        await message.answer("Добавь текст после команды: /post Текст новости")
        return

    post_text = await generate_post(text)
    try:
        await bot.send_message(config.CHANNEL_ID, post_text, 
                              parse_mode="Markdown", disable_web_page_preview=True)
        await message.answer("✅ Опубликовано в канал.")
    except Exception as e:
        await message.answer(f"❌ Ошибка публикации: {e}")

@dp.callback_query(F.data == "publish")
async def callback_publish(callback: types.CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    post_text = drafts.pop(callback.message.message_id, None)
    if not post_text:
        await callback.answer("Черновик устарел.", show_alert=True)
        return
    try:
        await bot.send_message(config.CHANNEL_ID, post_text, 
                              parse_mode="Markdown", disable_web_page_preview=True)
        await callback.message.edit_reply_markup()
        await callback.answer("✅ Опубликовано!")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(F.data == "edit")
async def callback_edit(callback: types.CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer(
        "Чтобы изменить текст, отмени этот черновик (/cancel) и создай новый.",
        show_alert=True
    )

@dp.callback_query(F.data == "cancel")
async def callback_cancel(callback: types.CallbackQuery):
    if callback.from_user.id != config.ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    drafts.pop(callback.message.message_id, None)
    await callback.message.edit_reply_markup()
    await callback.message.edit_text(callback.message.text + "\n\n❌ _Публикация отменена_", 
                                     parse_mode="Markdown")
    await callback.answer("Отменено.")

async def main():
    await database.init_db()
    print("Бот запущен! Нажми Ctrl+C для остановки.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())