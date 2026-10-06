
import time
import aiosqlite

class Database:
    def __init__(self, path="moderator.db"):
        self.path = path

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS chats(
                chat_id INTEGER PRIMARY KEY,
                activated_at INTEGER NOT NULL,
                title TEXT,
                smart_mode INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users(
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                display_name TEXT,
                messages INTEGER NOT NULL DEFAULT 0,
                last_message_at INTEGER,
                reputation INTEGER NOT NULL DEFAULT 100,
                PRIMARY KEY(chat_id,user_id)
            );

            CREATE TABLE IF NOT EXISTS violations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rule_code TEXT NOT NULL,
                severity INTEGER NOT NULL DEFAULT 1,
                reason TEXT,
                message_text TEXT,
                message_id INTEGER,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_violations_user
            ON violations(chat_id,user_id,rule_code,created_at);

            CREATE TABLE IF NOT EXISTS punishments(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                minutes INTEGER NOT NULL DEFAULT 0,
                rule_code TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recent_messages(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                text TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_recent_messages
            ON recent_messages(chat_id,user_id,created_at);

            CREATE TABLE IF NOT EXISTS settings(
                chat_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY(chat_id,key)
            );
            """)
            await db.commit()

    async def activate_chat(self, chat_id:int, title:str=""):
        now=int(time.time())
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
            INSERT INTO chats(chat_id,activated_at,title,created_at)
            VALUES(?,?,?,?)
            ON CONFLICT(chat_id) DO UPDATE SET
                activated_at=excluded.activated_at,
                title=excluded.title
            """,(chat_id,now,title,now))
            await db.commit()
        return now

    async def get_activation(self, chat_id:int):
        async with aiosqlite.connect(self.path) as db:
            cur=await db.execute("SELECT activated_at FROM chats WHERE chat_id=?",(chat_id,))
            row=await cur.fetchone()
            return row[0] if row else None

    async def ensure_chat(self, chat_id:int, title:str=""):
        ts=await self.get_activation(chat_id)
        if ts is None:
            ts=await self.activate_chat(chat_id,title)
        return ts

    async def bump_user(self, chat_id:int, user):
        now=int(time.time())
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
            INSERT INTO users(chat_id,user_id,username,display_name,messages,last_message_at)
            VALUES(?,?,?,?,1,?)
            ON CONFLICT(chat_id,user_id) DO UPDATE SET
                username=excluded.username,
                display_name=excluded.display_name,
                messages=users.messages+1,
                last_message_at=excluded.last_message_at
            """,(chat_id,user.id,user.username or "",user.full_name,now))
            await db.commit()

    async def add_violation(self, chat_id:int, user_id:int, rule_code:str, severity:int,
                            reason:str, text:str, message_id:int|None):
        now=int(time.time())
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
            INSERT INTO violations(chat_id,user_id,rule_code,severity,reason,message_text,message_id,created_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,(chat_id,user_id,rule_code,severity,reason,text[:1000],message_id,now))
            # lower reputation according to severity
            await db.execute("""
            UPDATE users SET reputation=MAX(0,reputation-?)
            WHERE chat_id=? AND user_id=?
            """,(severity*5,chat_id,user_id))
            await db.commit()

    async def count_violations(self, chat_id:int, user_id:int, rule_code:str|None=None, days:int=30):
        since=int(time.time())-days*86400
        async with aiosqlite.connect(self.path) as db:
            if rule_code:
                cur=await db.execute("""
                SELECT COUNT(*) FROM violations
                WHERE chat_id=? AND user_id=? AND rule_code=? AND created_at>=?
                """,(chat_id,user_id,rule_code,since))
            else:
                cur=await db.execute("""
                SELECT COUNT(*) FROM violations
                WHERE chat_id=? AND user_id=? AND created_at>=?
                """,(chat_id,user_id,since))
            row=await cur.fetchone()
            return int(row[0] if row else 0)

    async def add_punishment(self, chat_id:int, user_id:int, action:str, minutes:int, rule_code:str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
            INSERT INTO punishments(chat_id,user_id,action,minutes,rule_code,created_at)
            VALUES(?,?,?,?,?,?)
            """,(chat_id,user_id,action,minutes,rule_code,int(time.time())))
            await db.commit()

    async def add_recent_message(self, chat_id:int, user_id:int, fingerprint:str, text:str):
        now=int(time.time())
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
            INSERT INTO recent_messages(chat_id,user_id,fingerprint,text,created_at)
            VALUES(?,?,?,?,?)
            """,(chat_id,user_id,fingerprint,text[:500],now))
            # cleanup older than 24h
            await db.execute("DELETE FROM recent_messages WHERE created_at<?",(now-86400,))
            await db.commit()

    async def repeated_count(self, chat_id:int, user_id:int, fingerprint:str, seconds:int=60):
        since=int(time.time())-seconds
        async with aiosqlite.connect(self.path) as db:
            cur=await db.execute("""
            SELECT COUNT(*) FROM recent_messages
            WHERE chat_id=? AND user_id=? AND fingerprint=? AND created_at>=?
            """,(chat_id,user_id,fingerprint,since))
            row=await cur.fetchone()
            return int(row[0] if row else 0)

    async def message_rate(self, chat_id:int, user_id:int, seconds:int=20):
        since=int(time.time())-seconds
        async with aiosqlite.connect(self.path) as db:
            cur=await db.execute("""
            SELECT COUNT(*) FROM recent_messages
            WHERE chat_id=? AND user_id=? AND created_at>=?
            """,(chat_id,user_id,since))
            row=await cur.fetchone()
            return int(row[0] if row else 0)

    async def top_chat(self, chat_id:int, limit:int=10):
        async with aiosqlite.connect(self.path) as db:
            cur=await db.execute("""
            SELECT user_id,username,display_name,messages,reputation
            FROM users WHERE chat_id=?
            ORDER BY messages DESC LIMIT ?
            """,(chat_id,limit))
            return await cur.fetchall()

    async def user_stats(self, chat_id:int, user_id:int):
        async with aiosqlite.connect(self.path) as db:
            cur=await db.execute("""
            SELECT messages,reputation FROM users WHERE chat_id=? AND user_id=?
            """,(chat_id,user_id))
            user=await cur.fetchone() or (0,100)

            cur=await db.execute("""
            SELECT rule_code,COUNT(*) FROM violations
            WHERE chat_id=? AND user_id=?
            GROUP BY rule_code ORDER BY COUNT(*) DESC
            """,(chat_id,user_id))
            rules=await cur.fetchall()

            cur=await db.execute("""
            SELECT action,minutes,rule_code,created_at FROM punishments
            WHERE chat_id=? AND user_id=?
            ORDER BY id DESC LIMIT 10
            """,(chat_id,user_id))
            punish=await cur.fetchall()

            return user, rules, punish

    async def history(self, chat_id:int, user_id:int, limit:int=10):
        async with aiosqlite.connect(self.path) as db:
            cur=await db.execute("""
            SELECT rule_code,reason,created_at FROM violations
            WHERE chat_id=? AND user_id=?
            ORDER BY id DESC LIMIT ?
            """,(chat_id,user_id,limit))
            return await cur.fetchall()

    async def clear_user_violations(self, chat_id:int, user_id:int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM violations WHERE chat_id=? AND user_id=?",(chat_id,user_id))
            await db.execute("UPDATE users SET reputation=100 WHERE chat_id=? AND user_id=?",(chat_id,user_id))
            await db.commit()
