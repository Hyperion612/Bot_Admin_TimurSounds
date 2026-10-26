import aiosqlite
from datetime import date

import config

DB_NAME = config.DB_NAME

TRACKS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        artist TEXT NOT NULL,
        title TEXT NOT NULL,
        type TEXT DEFAULT 'single',
        release_date TEXT NOT NULL,
        label TEXT,
        link TEXT
    )
"""


async def _migrate_tracks(db):
    """Создаёт таблицу tracks и мигрирует старую схему (name/link) в новую."""
    cursor = await db.execute("PRAGMA table_info(tracks)")
    cols = {r[1] for r in await cursor.fetchall()}

    if not cols:  # таблицы нет — создаём
        await db.execute(TRACKS_SCHEMA)
    elif "artist" not in cols:  # старая схема: id, name, release_date, link
        rows = await db.execute_fetchall("SELECT id, name, release_date, link FROM tracks")
        await db.execute("DROP TABLE tracks")
        await db.execute(TRACKS_SCHEMA)
        for _id, name, release_date, link in rows:
            name = name or ""
            if " - " in name:
                artist, title = (s.strip() for s in name.split(" - ", 1))
            else:
                artist, title = name.strip(), "—"
            await db.execute(
                "INSERT INTO tracks (id, artist, title, type, release_date, label, link) "
                "VALUES (?, ?, ?, 'single', ?, NULL, ?)",
                (_id, artist, title, release_date, link),
            )
    else:
        # Новая схема, но возможны отсутствующие колонки (например, type)
        for col, decl in (("type", "TEXT DEFAULT 'single'"), ("label", "TEXT")):
            if col not in cols:
                await db.execute(f"ALTER TABLE tracks ADD COLUMN {col} {decl}")
    await db.commit()


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await _migrate_tracks(db)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Дефолтный шаблон (MarkdownV2-безопасный: свободные поля — в code-спанах)
        default_template = (
            "📅 *{{ today }}* | {{ now }}\n\n"
            "{{ text }}\n\n"
            "{% if next_track %}"
            "──────────────\n"
            "🚀 *Ближайший релиз:*\n"
            "🎵 `{{ next_track.artist }} - {{ next_track.title }}"
            "{% if next_track.type %} ({{ next_track.type }}){% endif %}`\n"
            "🗓 `{{ next_track.release_date }}`"
            "{% if next_track.label %}\n🎧 `{{ next_track.label }}`{% endif %}"
            "{% if next_track.link %}\n🔗 `{{ next_track.link }}`{% endif %}\n"
            "⏳ Через {{ days_left }} дн.\n"
            "{% endif %}"
            "{% if anniversaries %}"
            "──────────────\n"
            "🎂 *Сегодня годовщины:*\n"
            "{% for tr, years in anniversaries %}"
            "• `{{ tr.artist }} - {{ tr.title }}"
            "{% if tr.type %} ({{ tr.type }}){% endif %}` — {{ years }} {{ plural_years(years) }}\n"
            "{% endfor %}"
            "{% endif %}"
        )
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("template", default_template)
        )
        await db.commit()

async def add_track(artist: str, title: str, release_date: str, 
                    track_type: str = "single", label: str = None, link: str = None):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO tracks (artist, title, type, release_date, label, link) VALUES (?, ?, ?, ?, ?, ?)",
            (artist, title, track_type, release_date, label, link)
        )
        await db.commit()

async def delete_track(track_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        await db.commit()

async def get_all_tracks():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, artist, title, type, release_date, label, link FROM tracks ORDER BY release_date"
        )
        rows = await cursor.fetchall()
        return [{
            "id": r[0], "artist": r[1], "title": r[2], "type": r[3],
            "release_date": r[4], "label": r[5], "link": r[6]
        } for r in rows]

async def get_next_release(today: date):
    """Ближайший будущий релиз"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, artist, title, type, release_date, label, link FROM tracks "
            "WHERE release_date >= ? ORDER BY release_date LIMIT 1",
            (today.isoformat(),)
        )
        row = await cursor.fetchone()
        if row:
            return {
                "id": row[0], "artist": row[1], "title": row[2], "type": row[3],
                "release_date": row[4], "label": row[5], "link": row[6]
            }
        return None

async def get_anniversaries(today: date):
    """Треки с годовщиной сегодня"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, artist, title, type, release_date, label, link FROM tracks"
        )
        rows = await cursor.fetchall()
    result = []
    for r in rows:
        r_date = date.fromisoformat(r[4])
        if r_date.month == today.month and r_date.day == today.day and r_date.year < today.year:
            years = today.year - r_date.year
            track = {
                "id": r[0], "artist": r[1], "title": r[2], "type": r[3],
                "release_date": r[4], "label": r[5], "link": r[6]
            }
            result.append((track, years))
    return result

async def get_template():
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = 'template'")
        row = await cursor.fetchone()
        return row[0] if row else ""

async def set_template(new_template: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE settings SET value = ? WHERE key = 'template'", (new_template,))
        await db.commit()

async def update_track(track_id: int, **fields):
    """Частичное обновление трека. Разрешённые поля: artist, title, type, release_date, label, link."""
    allowed = {"artist", "title", "type", "release_date", "label", "link"}
    cols = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not cols:
        return False
    sets = ", ".join(f"{k} = ?" for k in cols)
    params = list(cols.values()) + [track_id]
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(f"UPDATE tracks SET {sets} WHERE id = ?", params)
        await db.commit()
        return cursor.rowcount > 0

async def get_track(track_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, artist, title, type, release_date, label, link FROM tracks WHERE id = ?",
            (track_id,),
        )
        row = await cursor.fetchone()
        if row:
            return {
                "id": row[0], "artist": row[1], "title": row[2], "type": row[3],
                "release_date": row[4], "label": row[5], "link": row[6],
            }
        return None
async def clear_track_field(track_id: int, field: str):
    """Очистка поля трека (NULL)."""
    allowed = {"artist", "title", "type", "release_date", "label", "link"}
    if field not in allowed:
        return False
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(f"UPDATE tracks SET {field} = NULL WHERE id = ?", (track_id,))
        await db.commit()
        return cursor.rowcount > 0
