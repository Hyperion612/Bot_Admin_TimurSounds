import aiosqlite
from datetime import date

DB_NAME = "releases.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                type TEXT DEFAULT 'single',
                release_date TEXT NOT NULL,
                label TEXT,
                link TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Дефолтный шаблон с новыми полями
        default_template = (
            "📅 *{{ today }}* | {{ now }}\n\n"
            "{{ text }}\n\n"
            "{% if next_track %}"
            "──────────────\n"
            "🚀 *Ближайший релиз:*\n"
            "🎵 {{ next_track.artist }} - {{ next_track.title }}"
            "{% if next_track.type %} ({{ next_track.type }}){% endif %}\n"
            "🗓 {{ next_track.release_date }}"
            "{% if next_track.label %}\n🎧 {{ next_track.label }}{% endif %}"
            "{% if next_track.link %}\n🔗 {{ next_track.link }}{% endif %}\n"
            "⏳ Через {{ days_left }} дн.\n"
            "{% endif %}"
            "{% if anniversaries %}"
            "──────────────\n"
            "🎂 *Сегодня годовщины:*\n"
            "{% for tr, years in anniversaries %}"
            "• {{ tr.artist }} - {{ tr.title }}"
            "{% if tr.type %} ({{ tr.type }}){% endif %} — {{ years }} {{ 'год' if years==1 else 'года' if years<5 else 'лет' }}\n"
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