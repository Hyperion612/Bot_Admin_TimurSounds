"""ReleaseMate Bot — менеджер музыкального канала.

Улучшения:
- aiogram 3.x: Router, FSM (интерактивное добавление/редактирование треков)
- MarkdownV2 + fallback на HTML/обычный текст при ошибках парсинга
- Черновики с автоочисткой (GC) и безопасной публикацией
- Webhook-режим для PaaS (Render/Tranger Cloud) с healthcheck /healthz
- Fallback на long polling при проблемах с сетью
"""
import asyncio
import logging
import re
from datetime import date, datetime

from aiogram import Bot, Dispatcher, F, Router, types
from aiogram.exceptions import TelegramBadRequestError
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from jinja2 import Template

import config
import database
from utils import publish_keyboard, safe_markdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("releasemate")

router = Router()
dp = Dispatcher()
dp.include_router(router)

# Хранилище черновиков: message_id -> (текст поста, timestamp). Старше суток — GC.
drafts: dict[int, tuple[str, float]] = {}


def draft_put(msg_id: int, text: str):
    import time
    drafts[msg_id] = (text, time.time())
    cutoff = time.time() - 86400
    for k in [k for k, (_, ts) in drafts.items() if ts < cutoff]:
        drafts.pop(k, None)


def draft_get(msg_id: int):
    item = drafts.get(msg_id)
    return item[0] if item else None

# ---------- FSM-состояния ----------


class AddTrackStates(StatesGroup):
    artist = State()
    title = State()
    track_type = State()
    release_date = State()
    label = State()
    link = State()


class EditTrackStates(StatesGroup):
    waiting_id = State()
    field = State()
    value = State()


# ---------- Хелперы ----------


def is_admin(message_or_cb) -> bool:
    user = message_or_cb.from_user
    return bool(user) and user.id == config.ADMIN_ID


def prepare_mdv2(text: str) -> str:
    """Экранирует текст под MarkdownV2, не трогая содержимое `code`-спанов."""
    parts = re.split(r"(`[^`\n]*`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(p)  # внутри code ничего экранировать не нужно
        else:
            out.append(safe_markdown(p))
    return "".join(out)


def strip_code_spans(text: str) -> str:
    return text.replace("`", "")


async def send_message_safe(target, text: str, extra_kwargs: dict | None = None) -> types.Message:
    """Отправка с деградацией формата: MarkdownV2 -> обычный текст."""
    extra = extra_kwargs or {}
    try:
        return await target.send_message(
            prepare_mdv2(text), parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=True, **extra,
        )
    except TelegramBadRequestError as e:
        logger.warning("MarkdownV2 не прошёл (%s), отправляю без форматирования", e)
        extra.pop("parse_mode", None)
        return await target.send_message(
            strip_code_spans(text), disable_web_page_preview=True, **extra,
        )


async def send_channel_post(bot: Bot, text: str) -> None:
    """Публикация в канал с деградацией формата."""
    await send_message_safe(
        PartialBotSender(bot, config.CHANNEL_ID), text
    )


class PartialBotSender:
    """Обёртка: target.send_message(text,...) -> bot.send_message(chat_id, text, ...)"""
    def __init__(self, bot: Bot, chat_id):
        self.bot = bot
        self.chat_id = chat_id

    async def send_message(self, text, **kwargs):
        return await self.bot.send_message(self.chat_id, text, **kwargs)


def plural_years(years: int) -> str:
    if years % 10 == 1 and years != 11:
        return "год"
    if years % 10 in (2, 3, 4) and years % 100 not in (12, 13, 14):
        return "года"
    return "лет"


async def generate_post(text: str) -> str:
    """Рендерит пост по шаблону из БД (сырой текст). Экранирование — на этапе отправки."""
    today = date.today()
    now = datetime.now().strftime("%H:%M")
    tpl_str = await database.get_template()
    template = Template(tpl_str)

    next_track = await database.get_next_release(today)
    days_left = None
    track_ctx = None
    if next_track:
        release_date = date.fromisoformat(next_track["release_date"])
        days_left = (release_date - today).days
        track_ctx = next_track

    anniversaries = list(await database.get_anniversaries(today))

    rendered = template.render(
        today=today.strftime("%d.%m.%Y"),
        now=now,
        text=text,
        next_track=track_ctx,
        days_left=days_left,
        anniversaries=anniversaries,
        plural_years=plural_years,
    )
    return rendered


# ---------- Команды ----------


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    if not is_admin(message):
        return await message.answer("⛔ Этот бот работает только с администратором.")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎵 Список треков", callback_data="menu:tracks"),
                InlineKeyboardButton(text="➕ Добавить трек", callback_data="menu:addtrack"),
            ],
            [
                InlineKeyboardButton(text="📝 Создать черновик", callback_data="menu:announce"),
                InlineKeyboardButton(text="📋 Шаблон", callback_data="menu:template"),
            ],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
        ]
    )
    await message.answer(
        "🎵 *ReleaseMate Bot*\n\n"
        "Я помогаю вести музыкальный канал\\. Вот что я умею:\n\n"
        "📌 *Треки:* `/addtrack`, `/listtracks`, `/deltrack`, `/edittrack`\n"
        "📝 *Посты:* `/announce` \\(черновик\\), `/post` \\(сразу в канал\\)\n"
        "⚙️ *Настройки:* `/template`, `/settemplate`, `/status`, `/help`\n\n"
        "Выберите действие кнопками ниже 👇",
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )


@router.callback_query(F.data.startswith("menu:"))
async def cb_menu(callback: types.CallbackQuery):
    if not is_admin(callback):
        return await callback.answer("Нет доступа.", show_alert=True)
    action = callback.data.split(":", 1)[1]
    hints = {
        "tracks": "Используйте /listtracks",
        "addtrack": "Используйте /addtrack (интерактивно) или /addtrack Артист - Название | дата | лейбл | ссылка",
        "announce": "Используйте /announce Текст новости",
        "template": "Используйте /template или /settemplate <шаблон>",
        "help": "Используйте /help",
    }
    await callback.answer(hints.get(action, "Готово"), show_alert=True)


@router.message(Command("help"))
async def cmd_help(message: types.Message):
    if not is_admin(message):
        return
    await message.answer(
        "📋 *Все команды:*\n\n"
        "*Треки:*\n"
        "`/addtrack` — интерактивный мастер добавления\n"
        "`/addtrack Артист \\- Название \\(тип\\) | ГГГГ\\-ММ\\-ДД | Лейбл | ссылка` — одной строкой\n"
        "`/listtracks` — список всех треков\n"
        "`/deltrack ID` — удалить\n"
        "`/edittrack ID` — изменить поле\n\n"
        "*Посты:*\n"
        "`/announce текст` — черновик с кнопками ✅✏️❌\n"
        "`/post текст` — сразу в канал\n\n"
        "*Прочее:*\n"
        "`/template` — текущий шаблон\n"
        "`/settemplate` — обновить шаблон\n"
        "`/status` — состояние бота и базы\n\n"
        "Переменные шаблона: `{{ '{{' }} today {{ '}}' }}`, `{{ '{{' }} now {{ '}}' }}`, "
        "`{{ '{{' }} text {{ '}}' }}`, `{{ '{{' }} next_track.artist {{ '}}' }}`, "
        "`{{ '{{' }} days_left {{ '}}' }}`, `{{ '{{' }} anniversaries {{ '}}' }}`",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


@router.message(Command("status"))
async def cmd_status(message: types.Message):
    if not is_admin(message):
        return
    tracks = await database.get_all_tracks()
    today = date.today()
    nxt = await database.get_next_release(today)
    ann = await database.get_anniversaries(today)
    lines = [
        "📊 *Статус:*\n",
        f"• Треков в базе: {len(tracks)}",
        f"• Ближайший релиз: "
        + (f"{nxt['artist']} - {nxt['title']} ({nxt['release_date']})" if nxt else "—"),
        f"• Годовщин сегодня: {len(ann)}",
        f"• Режим: {'webhook' if config.WEBHOOK_MODE else 'polling'}",
    ]
    await message.answer("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ---------- Добавление трека: строкой или FSM-мастер ----------


def _parse_inline_track(full_text: str) -> dict | None:
    parts = full_text.split("|")
    artist_title = parts[0].strip()
    if " - " not in artist_title or len(parts) < 2:
        return None
    artist, title_and_type = artist_title.split(" - ", 1)
    track_type = "single"
    if "(" in title_and_type and ")" in title_and_type:
        start, end = title_and_type.index("("), title_and_type.index(")")
        track_type = title_and_type[start + 1 : end].strip()
        title = (title_and_type[:start] + title_and_type[end + 1 :]).strip()
    else:
        title = title_and_type.strip()
    release_date_str = parts[1].strip()
    date.fromisoformat(release_date_str)  # ValueError при неверном формате
    return {
        "artist": artist.strip(),
        "title": title.strip(),
        "track_type": track_type,
        "release_date": release_date_str,
        "label": parts[2].strip() if len(parts) > 2 and parts[2].strip() else None,
        "link": parts[3].strip() if len(parts) > 3 and parts[3].strip() else None,
    }


@router.message(Command("addtrack"))
async def cmd_addtrack(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    try:
        full_text = message.text.split(maxsplit=1)[1]
    except IndexError:
        full_text = ""

    if full_text:  # режим «одной строкой»
        try:
            data = _parse_inline_track(full_text)
            if data is None:
                raise ValueError("нет разделителя ' - ' или даты")
            await database.add_track(**data)
            resp = (
                f"✅ Трек добавлен:\n\n🎵 {data['artist']} - {data['title']}"
                + (f" ({data['track_type']})" if data["track_type"] != "single" else "")
                + f"\n🗓 {data['release_date']}"
            )
            if data["label"]:
                resp += f"\n🎧 {data['label']}"
            if data["link"]:
                resp += f"\n🔗 {data['link']}"
            return await message.answer(resp, disable_web_page_preview=True)
        except ValueError:
            return await message.answer(
                "❌ Неверный формат.\n"
                "/addtrack Артист - Название (тип) | ГГГГ-ММ-ДД | Лейбл | ссылка\n"
                "или просто /addtrack — для пошагового мастера."
            )

    # пошаговый мастер
    await state.set_state(AddTrackStates.artist)
    await message.answer("➕ Добавляем трек шаг за шагом.\n\n🎤 Введите исполнителя:")


@router.message(AddTrackStates.artist)
async def fsm_artist(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    await state.update_data(artist=message.text.strip())
    await state.set_state(AddTrackStates.title)
    await message.answer("🎼 Введите название релиза:")


@router.message(AddTrackStates.title)
async def fsm_title(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    await state.update_data(title=message.text.strip())
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Single", callback_data="ftype:Single"),
                InlineKeyboardButton(text="EP", callback_data="ftype:EP"),
            ],
            [
                InlineKeyboardButton(text="Album", callback_data="ftype:Album"),
                InlineKeyboardButton(text="LP", callback_data="ftype:LP"),
            ],
        ]
    )
    await state.set_state(AddTrackStates.track_type)
    await message.answer("💿 Тип релиза:", reply_markup=kb)


@router.callback_query(AddTrackStates.track_type, F.data.startswith("ftype:"))
async def fsm_type(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback):
        return await callback.answer("Нет доступа.", show_alert=True)
    await state.update_data(track_type=callback.data.split(":", 1)[1])
    await state.set_state(AddTrackStates.release_date)
    await callback.message.delete_reply_markup()
    await callback.answer()
    await callback.message.answer("🗓 Дата релиза (ГГГГ-ММ-ДД):")


@router.message(AddTrackStates.release_date)
async def fsm_date(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    try:
        d = date.fromisoformat(message.text.strip())
    except ValueError:
        return await message.answer("❌ Неверная дата. Пример: 2026-12-24")
    await state.update_data(release_date=d.isoformat())
    await state.set_state(AddTrackStates.label)
    await message.answer("🎧 Лейбл (или «-» если нет):")


@router.message(AddTrackStates.label)
async def fsm_label(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    val = message.text.strip()
    await state.update_data(label=None if val in ("-", "") else val)
    await state.set_state(AddTrackStates.link)
    await message.answer("🔗 Ссылка (или «-» если нет):")


@router.message(AddTrackStates.link)
async def fsm_link(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    val = message.text.strip()
    await state.update_data(link=None if val in ("-", "") else val)
    data = await state.get_data()
    await state.clear()
    await database.add_track(
        artist=data["artist"],
        title=data["title"],
        track_type=data.get("track_type", "Single"),
        release_date=data["release_date"],
        label=data.get("label"),
        link=data.get("link"),
    )
    await message.answer(
        f"✅ Трек добавлен:\n\n🎵 {data['artist']} - {data['title']} ({data.get('track_type', 'Single')})\n"
        f"🗓 {data['release_date']}"
        + (f"\n🎧 {data['label']}" if data.get("label") else "")
        + (f"\n🔗 {data['link']}" if data.get("link") else "")
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    if await state.get_state() is None:
        return await message.answer("Нет активного действия.")
    await state.clear()
    await message.answer("❌ Действие отменено.")


# ---------- Список / удаление / редактирование ----------


@router.message(Command("listtracks"))
async def cmd_listtracks(message: types.Message):
    if not is_admin(message):
        return
    tracks = await database.get_all_tracks()
    if not tracks:
        return await message.answer("📭 База треков пуста. Добавьте: /addtrack")
    parts = ["📋 *Треки в базе:*\n"]
    for t in tracks:
        row = f"*{t['id']}.* {t['artist']} - {t['title']}"
        if t["type"] and t["type"].lower() != "single":
            row += f" ({t['type']})"
        row += f"\n   🗓 {t['release_date']}"
        if t["label"]:
            row += f" | 🎧 {t['label']}"
        if t["link"]:
            row += f"\n   🔗 {t['link']}"
        parts.append(row)
    text = "\n\n".join(parts)
    # Telegram лимит 4096 символов — разбиваем длинный ответ
    for i in range(0, len(text), 4000):
        await message.answer(text[i : i + 4000], parse_mode=ParseMode.MARKDOWN)


@router.message(Command("deltrack"))
async def cmd_deltrack(message: types.Message):
    if not is_admin(message):
        return
    try:
        track_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        return await message.answer("Используй: /deltrack ID\nID см. в /listtracks")
    track = await database.get_track(track_id)
    if not track:
        return await message.answer(f"⚠️ Трек #{track_id} не найден.")
    await database.delete_track(track_id)
    await message.answer(f"🗑 Удалён трек #{track_id}: {track['artist']} - {track['title']}")


@router.message(Command("edittrack"))
async def cmd_edittrack(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    args = message.text.split()
    if len(args) >= 2:
        try:
            track_id = int(args[1])
        except ValueError:
            return await message.answer("ID должен быть числом. Пример: /edittrack 3")
    else:
        return await message.answer("Используй: /edittrack ID [поле] [значение]\nПоля: artist, title, type, date, label, link")

    track = await database.get_track(track_id)
    if not track:
        return await message.answer(f"⚠️ Трек #{track_id} не найден.")

    # /edittrack ID поле значение — мгновенное изменение
    if len(args) >= 4:
        field = args[2].lower()
        value = " ".join(args[3:])
        mapping = {"artist": "artist", "title": "title", "type": "type",
                   "date": "release_date", "release_date": "release_date",
                   "label": "label", "link": "link"}
        col = mapping.get(field)
        if not col:
            return await message.answer("Неизвестное поле. Доступно: artist, title, type, date, label, link")
        if col == "release_date":
            try:
                date.fromisoformat(value)
            except ValueError:
                return await message.answer("❌ Дата в формате ГГГГ-ММ-ДД")
        await database.update_track(track_id, **{col: value})
        updated = await database.get_track(track_id)
        return await message.answer(
            f"✅ Обновлено #{track_id}: {updated['artist']} - {updated['title']} "
            f"({updated['type']}) 🗓 {updated['release_date']}"
        )

    # Интерактивный режим
    await state.set_state(EditTrackStates.waiting_id)
    await state.update_data(track_id=track_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Артист", callback_data=f"fedit:{track_id}:artist"),
                InlineKeyboardButton(text="Название", callback_data=f"fedit:{track_id}:title"),
            ],
            [
                InlineKeyboardButton(text="Тип", callback_data=f"fedit:{track_id}:type"),
                InlineKeyboardButton(text="Дата", callback_data=f"fedit:{track_id}:release_date"),
            ],
            [
                InlineKeyboardButton(text="Лейбл", callback_data=f"fedit:{track_id}:label"),
                InlineKeyboardButton(text="Ссылка", callback_data=f"fedit:{track_id}:link"),
            ],
        ]
    )
    await message.answer(
        f"✏️ Трек #{track_id}: {track['artist']} - {track['title']} ({track['type']}) 🗓 {track['release_date']}\n"
        "Какое поле изменить?",
        reply_markup=kb,
    )


@router.callback_query(EditTrackStates.waiting_id, F.data.startswith("fedit:"))
async def cb_edit_field(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback):
        return await callback.answer("Нет доступа.", show_alert=True)
    _, tid, field = callback.data.split(":")
    if int(tid) != (await state.get_data()).get("track_id"):
        return await callback.answer("Черновик устарел.", show_alert=True)
    await state.set_state(EditTrackStates.value)
    await state.update_data(field=field)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await callback.message.answer(f"Введите новое значение поля «{field}» (или «-» чтобы очистить):")


@router.message(EditTrackStates.value)
async def fsm_edit_value(message: types.Message, state: FSMContext):
    if not is_admin(message):
        return
    data = await state.get_data()
    field, tid = data["field"], data["track_id"]
    value = message.text.strip() or None
    if value == "-":
        value = None
    if field == "release_date" and value:
        try:
            date.fromisoformat(value)
        except ValueError:
            return await message.answer("❌ Дата в формате ГГГГ-ММ-ДД. Попробуйте ещё раз:")
    if value is not None:
        await database.update_track(tid, **{field: value})
    else:
        await database.clear_track_field(tid, field)
    await state.clear()
    track = await database.get_track(tid)
    await message.answer(
        f"✅ Трек #{tid} обновлён: {track['artist']} - {track['title']} "
        f"({track['type']}) 🗓 {track['release_date']}"
    )


# ---------- Шаблоны ----------


@router.message(Command("template"))
async def cmd_show_template(message: types.Message):
    if not is_admin(message):
        return
    tpl = await database.get_template()
    await message.answer(f"📝 Текущий шаблон:\n\n{tpl}", reply_markup=None)
    await message.answer(
        "Доступные переменные:\n"
        "{{ today }} — сегодняшняя дата\n"
        "{{ now }} — текущее время\n"
        "{{ text }} — текст новости\n"
        "{{ next_track.artist }} / .title / .type / .release_date / .label / .link\n"
        "{{ days_left }} — дней до релиза\n"
        "{{ anniversaries }} — список годовщин (track, years)",
    )


@router.message(Command("settemplate"))
async def cmd_set_template(message: types.Message):
    if not is_admin(message):
        return
    try:
        new_tpl = message.text.split(maxsplit=1)[1]
    except IndexError:
        return await message.answer(
            "Используй: /settemplate <новый шаблон>\n\n"
            "Или с новой строки:\n/settemplate\nТвой шаблон..."
        )
    # Валидация Jinja перед сохранением
    try:
        Template(new_tpl).render(today="", now="", text="", next_track=None,
                                 days_left=None, anniversaries=[], plural_years=lambda y: "")
    except Exception as e:
        return await message.answer(f"❌ Шаблон не сохранён, ошибка Jinja: {e}")
    await database.set_template(new_tpl)
    await message.answer("✅ Шаблон обновлён. Проверь: /template")


# ---------- Посты: announce / post ----------


@router.message(Command("announce"))
async def cmd_announce(message: types.Message, bot: Bot):
    if not is_admin(message):
        return
    try:
        text = message.text.split(maxsplit=1)[1]
    except IndexError:
        return await message.answer("Добавь текст после команды: /announce Текст новости")

    post_text = await generate_post(text)
    preview = await send_message_safe(
        message, post_text, extra_kwargs={"reply_markup": publish_keyboard()},
    )
    # Сохраняем сырой текст черновика (экранирование — при публикации)
    draft_put(preview.message_id, post_text)


@router.message(Command("post"))
async def cmd_post(message: types.Message, bot: Bot):
    if not is_admin(message):
        return
    try:
        text = message.text.split(maxsplit=1)[1]
    except IndexError:
        return await message.answer("Добавь текст после команды: /post Текст новости")
    post_text = await generate_post(text)
    try:
        await send_channel_post(bot, post_text)
        await message.answer("✅ Опубликовано в канал.")
    except Exception as e:
        logger.exception("Ошибка публикации /post")
        await message.answer(f"❌ Ошибка публикации: {e}")


@router.callback_query(F.data == "publish")
async def callback_publish(callback: types.CallbackQuery, bot: Bot):
    if not is_admin(callback):
        return await callback.answer("Нет доступа.", show_alert=True)
    post_text = draft_get(callback.message.message_id)
    if not post_text:
        return await callback.answer("Черновик устарел.", show_alert=True)
    try:
        await send_channel_post(bot, post_text)
        drafts.pop(callback.message.message_id, None)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Опубликовано!")
    except Exception as e:
        logger.exception("Ошибка публикации из черновика")
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(F.data == "edit")
async def callback_edit(callback: types.CallbackQuery):
    if not is_admin(callback):
        return await callback.answer("Нет доступа.", show_alert=True)
    await callback.answer(
        "Скопируйте текст, отмените этот черновик (❌) и создайте новый через /announce.",
        show_alert=True,
    )


@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: types.CallbackQuery):
    if not is_admin(callback):
        return await callback.answer("Нет доступа.", show_alert=True)
    drafts.pop(callback.message.message_id, None)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequestError:
        pass  # "message is not modified" и т.п.
    await callback.answer("Отменено.")


# ---------- Error handler ----------


@router.errors()
async def on_error(event, exception):
    logger.exception("Необработанная ошибка: %s", exception)


# ---------- Запуск ----------


async def setup_commands(bot: Bot):
    from aiogram.types import BotCommand
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="addtrack", description="Добавить трек"),
        BotCommand(command="listtracks", description="Список треков"),
        BotCommand(command="edittrack", description="Изменить трек"),
        BotCommand(command="deltrack", description="Удалить трек"),
        BotCommand(command="announce", description="Черновик поста"),
        BotCommand(command="post", description="Пост сразу в канал"),
        BotCommand(command="template", description="Показать шаблон"),
        BotCommand(command="settemplate", description="Задать шаблон"),
        BotCommand(command="status", description="Статус бота"),
        BotCommand(command="help", description="Справка"),
        BotCommand(command="cancel", description="Отменить действие"),
    ]
    await bot.set_my_commands(commands)


async def run_polling(bot: Bot):
    logger.info("Запуск в режиме long polling…")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except OSError as e:
        # На некоторых PaaS прямой доступ к Telegram API может быть ограничен
        logger.error("Polling недоступен (%s). Если хостинг блокирует исходящие соединения — включите WEBHOOK_MODE=true.", e)
        raise


async def run_webhook(bot: Bot):
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    if not config.PUBLIC_URL:
        raise RuntimeError("WEBHOOK_MODE=true требует PUBLIC_URL (публичный HTTPS-адрес сервиса)")
    url_path = "/webhook"
    await bot.set_webhook(
        url=f"{config.PUBLIC_URL}{url_path}",
        secret_token=config.WEBHOOK_SECRET or None,
        drop_pending_updates=True,
        allowed_updates=dp.resolve_used_update_types(),
    )
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=config.WEBHOOK_SECRET or None).register(app, path=url_path)
    setup_application(app, dp, bot=bot)

    async def healthz(request):
        return web.Response(text="ok")

    app.router.add_get("/healthz", healthz)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.PORT)
    await site.start()
    logger.info("Webhook запущен на порту %d, healthcheck: /healthz", config.PORT)
    # Жём бесконечно
    await asyncio.Event().wait()


async def main():
    await database.init_db()
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2),
    )
    await setup_commands(bot)
    if config.WEBHOOK_MODE:
        await run_webhook(bot)
    else:
        await run_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен.")
