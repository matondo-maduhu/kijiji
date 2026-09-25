"""
db.py — Database layer for Kijiji Tanzania (Neon PostgreSQL)
"""
from __future__ import annotations
import os
import re

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
UPLOAD_BADGES_FOLDER = os.path.join(BASE_DIR, "uploads", "badges")
ALLOWED_BADGE_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}
DB_PATH = os.path.join(BASE_DIR, "database.db")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(UPLOAD_BADGES_FOLDER, exist_ok=True)

DATABASE_URL = (os.environ.get("DATABASE_URL") or "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

_psycopg2 = None
_DictCursor = None
OperationalError = Exception


def _import_psycopg2():
    global _psycopg2, _DictCursor, OperationalError
    if _psycopg2 is None:
        import psycopg2
        from psycopg2.extras import DictCursor
        from psycopg2 import OperationalError as _OE
        _psycopg2 = psycopg2
        _DictCursor = DictCursor
        OperationalError = _OE
    return _psycopg2, _DictCursor


def allowed_badge_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_BADGE_EXTENSIONS


def _adapt_sql(sql: str) -> str:
    if not sql:
        return sql
    # Usibadilishe "?" ndani ya maoni (-- ...) — vinginevyo psycopg2
    # inaona %s za ziada → IndexError: tuple index out of range
    lines = []
    for line in sql.splitlines():
        if "--" in line:
            code, comment = line.split("--", 1)
            lines.append(code + "--" + comment.replace("?", ""))
        else:
            lines.append(line)
    s = "\n".join(lines)
    s = s.replace("?", "%s")
    # Escape lone % (LIKE patterns) but keep %s placeholders
    out = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "%":
            if i + 1 < n and s[i + 1] == "s":
                out.append("%s")
                i += 2
            elif i + 1 < n and s[i + 1] == "%":
                out.append("%%")
                i += 2
            else:
                out.append("%%")
                i += 1
        else:
            out.append(s[i])
            i += 1
    s = "".join(out)
    if re.search(r"INSERT\s+OR\s+IGNORE\s+INTO", s, re.I):
        s = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", s, flags=re.I)
        if "ON CONFLICT" not in s.upper():
            s = s.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    s = re.sub(r"\s+COLLATE\s+NOCASE", "", s, flags=re.I)
    s = re.sub(r"datetime\s*\(\s*'now'\s*\)", "NOW()", s, flags=re.I)
    return s



class CompatCursor:
    def __init__(self, raw_cursor, conn_wrapper):
        self._cur = raw_cursor
        self._conn = conn_wrapper
        self.lastrowid = None
        self.rowcount = -1

    def execute(self, sql, params=None):
        adapted = _adapt_sql(sql)
        if params is not None:
            if isinstance(params, list):
                params = tuple(params)
        is_insert = bool(re.match(r"\s*INSERT\s+", adapted, re.I))
        has_returning = "RETURNING" in adapted.upper()
        if is_insert and not has_returning and "ON CONFLICT DO NOTHING" not in adapted.upper():
            adapted_ret = adapted.rstrip().rstrip(";") + " RETURNING id"
            try:
                if params is not None:
                    self._cur.execute(adapted_ret, params)
                else:
                    self._cur.execute(adapted_ret)
                row = self._cur.fetchone()
                self.rowcount = self._cur.rowcount
                if row is not None:
                    try:
                        self.lastrowid = row["id"]
                    except Exception:
                        try:
                            self.lastrowid = list(row.values())[0]
                        except Exception:
                            self.lastrowid = None
                return self
            except Exception:
                # fallback bila RETURNING
                if params is not None:
                    self._cur.execute(adapted, params)
                else:
                    self._cur.execute(adapted)
                self.rowcount = self._cur.rowcount
                return self
        if params is not None:
            self._cur.execute(adapted, params)
        else:
            self._cur.execute(adapted)
        self.rowcount = self._cur.rowcount
        return self

    def executemany(self, sql, seq_of_params):
        self._cur.executemany(_adapt_sql(sql), seq_of_params)
        self.rowcount = self._cur.rowcount
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany() if size is None else self._cur.fetchmany(size)

    def close(self):
        self._cur.close()

    @property
    def description(self):
        return self._cur.description

    def __iter__(self):
        return iter(self._cur)


class CompatConnection:
    def __init__(self, raw_conn):
        self._conn = raw_conn
        self.row_factory = None

    def execute(self, sql, params=None):
        cur = self._conn.cursor(cursor_factory=_DictCursor)
        adapted = _adapt_sql(sql)
        is_insert = bool(re.match(r"\s*INSERT\s+", adapted, re.I))
        has_returning = "RETURNING" in adapted.upper()
        if is_insert and not has_returning and "ON CONFLICT DO NOTHING" not in adapted.upper():
            adapted_ret = adapted.rstrip().rstrip(";") + " RETURNING id"
            try:
                if params is not None:
                    if isinstance(params, list):
                        params = tuple(params)
                    cur.execute(adapted_ret, params)
                else:
                    cur.execute(adapted_ret)
                row = cur.fetchone()
                compat = CompatCursor(cur, self)
                if row is not None:
                    try:
                        compat.lastrowid = row["id"]
                    except Exception:
                        try:
                            compat.lastrowid = list(row.values())[0]
                        except Exception:
                            compat.lastrowid = None
                return compat
            except Exception:
                cur = self._conn.cursor(cursor_factory=_DictCursor)
                if params is not None:
                    if isinstance(params, list):
                        params = tuple(params)
                    cur.execute(adapted, params)
                else:
                    cur.execute(adapted)
                return CompatCursor(cur, self)
        if params is not None:
            if isinstance(params, list):
                params = tuple(params)
            cur.execute(adapted, params)
        else:
            cur.execute(adapted)
        return CompatCursor(cur, self)

    def cursor(self):
        return CompatCursor(self._conn.cursor(cursor_factory=_DictCursor), self)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set. Add Neon connection string in Render Environment.")
    psycopg2, DictCursor = _import_psycopg2()
    raw = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
    raw.autocommit = False
    return CompatConnection(raw)


def init_db():
    if not DATABASE_URL:
        print("[db] DATABASE_URL missing — skip init_db")
        return
    psycopg2, DictCursor = _import_psycopg2()
    raw = psycopg2.connect(DATABASE_URL)
    raw.autocommit = True
    cur = raw.cursor()

    def run(sql):
        try:
            cur.execute(sql)
        except Exception as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate" in msg:
                return
            print("[db init]", e)

    stmts = [
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, role TEXT DEFAULT 'user', bio TEXT, profile_pic TEXT,
            is_verified INTEGER DEFAULT 0, is_blocked INTEGER DEFAULT 0, warning_message TEXT,
            post_visibility TEXT DEFAULT 'public', is_email_verified INTEGER DEFAULT 1,
            full_name TEXT, language TEXT DEFAULT 'sw', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            auth_provider TEXT DEFAULT 'local', is_deactivated INTEGER DEFAULT 0, deactivated_at TEXT,
            warning_count INTEGER DEFAULT 0, restricted_until TEXT, village_mode INTEGER DEFAULT 0,
            profile_category TEXT, birthday TEXT, join_year TEXT, sex TEXT, marital_status TEXT,
            cover_photo TEXT, website TEXT, facebook TEXT, instagram TEXT, tiktok TEXT, youtube TEXT,
            whatsapp TEXT, telegram TEXT, x TEXT, linkedin TEXT, snapchat TEXT, pinterest TEXT,
            reddit TEXT, discord TEXT, github TEXT, twitch TEXT, spotify TEXT, threads TEXT,
            tumblr TEXT, vimeo TEXT, wordpress TEXT, medium TEXT, blogger TEXT)""",
        """CREATE TABLE IF NOT EXISTS pending_registrations (
            id SERIAL PRIMARY KEY, username TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL, otp TEXT NOT NULL, expires_at TIMESTAMP NOT NULL,
            resend_available_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, full_name TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_pending_email ON pending_registrations(email)",
        """CREATE TABLE IF NOT EXISTS posts (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), content TEXT,
            file_path TEXT, media_type TEXT, shares INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, category TEXT DEFAULT 'general',
            moderation_status TEXT DEFAULT 'approved', nsfw_score REAL DEFAULT 0, repost_of INTEGER,
            is_draft INTEGER DEFAULT 0, scheduled_at TEXT, published_at TEXT, linkup_id INTEGER)""",
        "CREATE INDEX IF NOT EXISTS idx_posts_linkup ON posts(linkup_id)",
        "CREATE INDEX IF NOT EXISTS idx_posts_user ON posts(user_id)",
        """CREATE TABLE IF NOT EXISTS moderation_flags (
            id SERIAL PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
            user_id INTEGER NOT NULL REFERENCES users(id), flag_type TEXT NOT NULL, nsfw_score REAL,
            labels TEXT, status TEXT DEFAULT 'pending', admin_note TEXT, created_at TEXT,
            reviewed_at TEXT, reviewed_by INTEGER)""",
        """CREATE TABLE IF NOT EXISTS comments (
            id SERIAL PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
            user_id INTEGER NOT NULL REFERENCES users(id), content TEXT NOT NULL,
            parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_hidden INTEGER DEFAULT 0, updated_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS comment_likes (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS likes (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            post_id INTEGER NOT NULL REFERENCES posts(id))""",
        """CREATE TABLE IF NOT EXISTS saved_posts (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            post_id INTEGER NOT NULL REFERENCES posts(id))""",
        """CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            sender_id INTEGER NOT NULL REFERENCES users(id), type TEXT NOT NULL, post_id INTEGER,
            message TEXT, is_read INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS history (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            action_description TEXT NOT NULL, post_id INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS badge_requests (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), username TEXT NOT NULL,
            account_type TEXT, full_name TEXT, alias_name TEXT, email TEXT, phone TEXT, category TEXT,
            id_type TEXT, id_number TEXT, id_document_path TEXT, website_link TEXT, media_links TEXT,
            other_socials TEXT, reason TEXT NOT NULL, status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, request_type TEXT DEFAULT 'user', linkup_id INTEGER)""",
        """CREATE TABLE IF NOT EXISTS admin_messages (
            id SERIAL PRIMARY KEY, name TEXT, email TEXT, message TEXT, admin_reply TEXT,
            status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS follows (
            id SERIAL PRIMARY KEY, follower_id INTEGER REFERENCES users(id),
            following_id INTEGER REFERENCES users(id), source_post_id INTEGER)""",
        """CREATE TABLE IF NOT EXISTS reposts (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            original_post_id INTEGER NOT NULL REFERENCES posts(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, original_post_id))""",
        """CREATE TABLE IF NOT EXISTS reports (
            id SERIAL PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id),
            reporter_id INTEGER NOT NULL REFERENCES users(id), reason TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status TEXT DEFAULT 'pending',
            admin_note TEXT, reviewed_at TEXT, reviewed_by INTEGER)""",
        """CREATE TABLE IF NOT EXISTS blocks (
            id SERIAL PRIMARY KEY, blocker_id INTEGER NOT NULL REFERENCES users(id),
            blocked_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(blocker_id, blocked_id))""",
        """CREATE TABLE IF NOT EXISTS post_views (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            post_id INTEGER NOT NULL REFERENCES posts(id), watch_seconds REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS community_groups (
            id SERIAL PRIMARY KEY, name TEXT NOT NULL, description TEXT, category TEXT DEFAULT 'general',
            creator_id INTEGER NOT NULL REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS group_members (
            id SERIAL PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES community_groups(id),
            user_id INTEGER NOT NULL REFERENCES users(id), joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(group_id, user_id))""",
        """CREATE TABLE IF NOT EXISTS group_messages (
            id SERIAL PRIMARY KEY, group_id INTEGER NOT NULL REFERENCES community_groups(id),
            user_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS community_posts (
            id SERIAL PRIMARY KEY, category TEXT NOT NULL, subcategory TEXT DEFAULT 'all',
            user_id INTEGER NOT NULL REFERENCES users(id), content TEXT, file_path TEXT, media_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS private_messages (
            id SERIAL PRIMARY KEY, sender_id INTEGER NOT NULL REFERENCES users(id),
            receiver_id INTEGER NOT NULL REFERENCES users(id), message TEXT NOT NULL, is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_delivered INTEGER DEFAULT 0,
            file_path TEXT, media_type TEXT, reaction TEXT, is_hidden INTEGER DEFAULT 0,
            reply_to_id INTEGER, status_id INTEGER, deleted_for_sender INTEGER DEFAULT 0,
            deleted_for_receiver INTEGER DEFAULT 0, edited_at TEXT)""",
        """CREATE TABLE IF NOT EXISTS call_signals (
            id SERIAL PRIMARY KEY, from_user_id INTEGER NOT NULL, to_user_id INTEGER NOT NULL,
            type TEXT NOT NULL, payload TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_read INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS push_subscriptions (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL, auth TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        "CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id)",
        """CREATE TABLE IF NOT EXISTS pinned_chats (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            other_user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, other_user_id))""",
        """CREATE TABLE IF NOT EXISTS statuses (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), content TEXT,
            file_path TEXT, media_type TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            music_path TEXT, privacy TEXT DEFAULT 'public')""",
        "CREATE INDEX IF NOT EXISTS idx_status_user ON statuses(user_id)",
        """CREATE TABLE IF NOT EXISTS status_views (
            id SERIAL PRIMARY KEY, status_id INTEGER NOT NULL REFERENCES statuses(id),
            viewer_id INTEGER NOT NULL REFERENCES users(id), viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(status_id, viewer_id))""",
        """CREATE TABLE IF NOT EXISTS status_reactions (
            id SERIAL PRIMARY KEY, status_id INTEGER NOT NULL REFERENCES statuses(id),
            user_id INTEGER NOT NULL REFERENCES users(id), reaction TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(status_id, user_id))""",
        """CREATE TABLE IF NOT EXISTS otps (
            id SERIAL PRIMARY KEY, email TEXT NOT NULL, otp TEXT NOT NULL, purpose TEXT NOT NULL,
            expires_at TIMESTAMP NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS data_deletion_requests (
            id SERIAL PRIMARY KEY, user_id INTEGER REFERENCES users(id), email TEXT NOT NULL,
            status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, processed_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS mutes (
            id SERIAL PRIMARY KEY, muter_id INTEGER NOT NULL REFERENCES users(id),
            muted_id INTEGER NOT NULL REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(muter_id, muted_id))""",
        """CREATE TABLE IF NOT EXISTS close_friends (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            friend_id INTEGER NOT NULL REFERENCES users(id), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, friend_id))""",
        """CREATE TABLE IF NOT EXISTS hashtags (
            id SERIAL PRIMARY KEY, tag TEXT UNIQUE NOT NULL, use_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS post_hashtags (
            id SERIAL PRIMARY KEY, post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
            hashtag_id INTEGER NOT NULL REFERENCES hashtags(id) ON DELETE CASCADE, UNIQUE(post_id, hashtag_id))""",
        """CREATE TABLE IF NOT EXISTS starred_messages (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            message_id INTEGER NOT NULL REFERENCES private_messages(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, message_id))""",
        """CREATE TABLE IF NOT EXISTS archived_chats (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            other_user_id INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(user_id, other_user_id))""",
        """CREATE TABLE IF NOT EXISTS user_sessions (
            id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            session_token TEXT UNIQUE NOT NULL, device_info TEXT, ip_address TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_current INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS linkups (
            id SERIAL PRIMARY KEY, owner_user_id INTEGER NOT NULL REFERENCES users(id),
            username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, category TEXT DEFAULT 'general',
            bio TEXT, profile_pic TEXT, cover_photo TEXT, is_active INTEGER DEFAULT 1,
            is_verified INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            about TEXT, website TEXT, phone TEXT, email_public TEXT, hometown TEXT, current_city TEXT,
            country TEXT, workplace_name TEXT, workplace_role TEXT, workplace_city TEXT,
            employment_type TEXT, primary_school TEXT, primary_year TEXT, secondary_school TEXT,
            secondary_year TEXT, college_name TEXT, college_year TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_linkups_owner ON linkups(owner_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_linkups_username ON linkups(username)",
        """CREATE TABLE IF NOT EXISTS linkup_follows (
            id SERIAL PRIMARY KEY, follower_id INTEGER NOT NULL REFERENCES users(id),
            linkup_id INTEGER NOT NULL REFERENCES linkups(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(follower_id, linkup_id))""",
        "CREATE INDEX IF NOT EXISTS idx_linkup_follows_linkup ON linkup_follows(linkup_id)",
    ]
    for s in stmts:
        run(s)
    cur.close()
    raw.close()
    print("[db] init_db OK (Neon PostgreSQL)")


try:
    if DATABASE_URL:
        init_db()
except Exception as e:
    print("[db] init on import failed:", e)
