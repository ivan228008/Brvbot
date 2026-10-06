import time
import asyncpg


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: asyncpg.Pool | None = None

    async def init(self):
        if not self.url:
            raise RuntimeError("DATABASE_URL is empty")
        self.pool = await asyncpg.create_pool(
            dsn=self.url,
            min_size=1,
            max_size=5,
            command_timeout=30,
        )
        async with self.pool.acquire() as conn:
            await conn.execute("""
            CREATE TABLE IF NOT EXISTS chats(
                chat_id BIGINT PRIMARY KEY,
                activated_at BIGINT NOT NULL,
                title TEXT,
                created_at BIGINT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users(
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                username TEXT,
                display_name TEXT,
                messages BIGINT NOT NULL DEFAULT 0,
                last_message_at BIGINT,
                reputation INTEGER NOT NULL DEFAULT 100,
                PRIMARY KEY(chat_id,user_id)
            );

            CREATE TABLE IF NOT EXISTS violations(
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                rule_code TEXT NOT NULL,
                severity INTEGER NOT NULL DEFAULT 1,
                reason TEXT,
                message_text TEXT,
                message_id BIGINT,
                created_at BIGINT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_violations_user
            ON violations(chat_id,user_id,rule_code,created_at);

            CREATE TABLE IF NOT EXISTS punishments(
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                action TEXT NOT NULL,
                minutes INTEGER NOT NULL DEFAULT 0,
                rule_code TEXT,
                created_at BIGINT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS recent_messages(
                id BIGSERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                fingerprint TEXT NOT NULL,
                text TEXT,
                created_at BIGINT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_recent_messages
            ON recent_messages(chat_id,user_id,created_at);
            """)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def activate_chat(self, chat_id: int, title: str = ""):
        now = int(time.time())
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO chats(chat_id,activated_at,title,created_at)
                VALUES($1,$2,$3,$4)
                ON CONFLICT(chat_id) DO UPDATE SET
                    activated_at=EXCLUDED.activated_at,
                    title=EXCLUDED.title
            """, chat_id, now, title, now)
        return now

    async def get_activation(self, chat_id: int):
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT activated_at FROM chats WHERE chat_id=$1", chat_id
            )
            return int(row["activated_at"]) if row else None

    async def ensure_chat(self, chat_id: int, title: str = ""):
        ts = await self.get_activation(chat_id)
        if ts is None:
            ts = await self.activate_chat(chat_id, title)
        return ts

    async def bump_user(self, chat_id: int, user):
        now = int(time.time())
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users(chat_id,user_id,username,display_name,messages,last_message_at)
                VALUES($1,$2,$3,$4,1,$5)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    username=EXCLUDED.username,
                    display_name=EXCLUDED.display_name,
                    messages=users.messages+1,
                    last_message_at=EXCLUDED.last_message_at
            """, chat_id, user.id, user.username or "", user.full_name, now)

    async def add_violation(
        self, chat_id: int, user_id: int, rule_code: str, severity: int,
        reason: str, text: str, message_id: int | None
    ):
        now = int(time.time())
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO violations(
                        chat_id,user_id,rule_code,severity,reason,message_text,message_id,created_at
                    ) VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                """, chat_id, user_id, rule_code, severity, reason, text[:1000], message_id, now)

                await conn.execute("""
                    UPDATE users
                    SET reputation=GREATEST(0,reputation-$1)
                    WHERE chat_id=$2 AND user_id=$3
                """, severity * 5, chat_id, user_id)

    async def count_violations(
        self, chat_id: int, user_id: int, rule_code: str | None = None, days: int = 30
    ):
        since = int(time.time()) - days * 86400
        async with self.pool.acquire() as conn:
            if rule_code:
                value = await conn.fetchval("""
                    SELECT COUNT(*) FROM violations
                    WHERE chat_id=$1 AND user_id=$2 AND rule_code=$3 AND created_at>=$4
                """, chat_id, user_id, rule_code, since)
            else:
                value = await conn.fetchval("""
                    SELECT COUNT(*) FROM violations
                    WHERE chat_id=$1 AND user_id=$2 AND created_at>=$3
                """, chat_id, user_id, since)
            return int(value or 0)

    async def add_punishment(
        self, chat_id: int, user_id: int, action: str, minutes: int, rule_code: str
    ):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO punishments(chat_id,user_id,action,minutes,rule_code,created_at)
                VALUES($1,$2,$3,$4,$5,$6)
            """, chat_id, user_id, action, minutes, rule_code, int(time.time()))

    async def add_recent_message(
        self, chat_id: int, user_id: int, fingerprint: str, text: str
    ):
        now = int(time.time())
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO recent_messages(chat_id,user_id,fingerprint,text,created_at)
                    VALUES($1,$2,$3,$4,$5)
                """, chat_id, user_id, fingerprint, text[:500], now)
                await conn.execute(
                    "DELETE FROM recent_messages WHERE created_at<$1",
                    now - 86400
                )

    async def repeated_count(
        self, chat_id: int, user_id: int, fingerprint: str, seconds: int = 60
    ):
        since = int(time.time()) - seconds
        async with self.pool.acquire() as conn:
            value = await conn.fetchval("""
                SELECT COUNT(*) FROM recent_messages
                WHERE chat_id=$1 AND user_id=$2 AND fingerprint=$3 AND created_at>=$4
            """, chat_id, user_id, fingerprint, since)
            return int(value or 0)

    async def message_rate(self, chat_id: int, user_id: int, seconds: int = 20):
        since = int(time.time()) - seconds
        async with self.pool.acquire() as conn:
            value = await conn.fetchval("""
                SELECT COUNT(*) FROM recent_messages
                WHERE chat_id=$1 AND user_id=$2 AND created_at>=$3
            """, chat_id, user_id, since)
            return int(value or 0)

    async def top_chat(self, chat_id: int, limit: int = 10):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT user_id,username,display_name,messages,reputation
                FROM users
                WHERE chat_id=$1
                ORDER BY messages DESC
                LIMIT $2
            """, chat_id, limit)

    async def user_stats(self, chat_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT messages,reputation
                FROM users WHERE chat_id=$1 AND user_id=$2
            """, chat_id, user_id)

            rules = await conn.fetch("""
                SELECT rule_code,COUNT(*) AS count
                FROM violations
                WHERE chat_id=$1 AND user_id=$2
                GROUP BY rule_code
                ORDER BY COUNT(*) DESC
            """, chat_id, user_id)

            punishments = await conn.fetch("""
                SELECT action,minutes,rule_code,created_at
                FROM punishments
                WHERE chat_id=$1 AND user_id=$2
                ORDER BY id DESC LIMIT 10
            """, chat_id, user_id)

            return user, rules, punishments

    async def history(self, chat_id: int, user_id: int, limit: int = 10):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT rule_code,reason,created_at
                FROM violations
                WHERE chat_id=$1 AND user_id=$2
                ORDER BY id DESC
                LIMIT $3
            """, chat_id, user_id, limit)

    async def clear_user_violations(self, chat_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM violations WHERE chat_id=$1 AND user_id=$2",
                    chat_id, user_id
                )
                await conn.execute("""
                    UPDATE users SET reputation=100
                    WHERE chat_id=$1 AND user_id=$2
                """, chat_id, user_id)
