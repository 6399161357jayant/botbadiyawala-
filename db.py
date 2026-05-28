import asyncpg
import os
import random
import string
from datetime import datetime, date, timedelta
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=2, max_size=10)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS game_users (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL,
                balance INTEGER NOT NULL DEFAULT 1000,
                kills INTEGER NOT NULL DEFAULT 0,
                bounty_amount INTEGER NOT NULL DEFAULT 0,
                job TEXT,
                premium BOOLEAN NOT NULL DEFAULT FALSE,
                premium_expires TIMESTAMP,
                ship_id INTEGER,
                protection_until TIMESTAMP,
                custom_emoji TEXT,
                daily_last TIMESTAMP,
                rob_count_today INTEGER NOT NULL DEFAULT 0,
                rob_date DATE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ships (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                code CHAR(4) NOT NULL UNIQUE,
                captain_id BIGINT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ship_members (
                id SERIAL PRIMARY KEY,
                ship_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                role TEXT NOT NULL DEFAULT 'member'
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_items (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                item_name TEXT NOT NULL,
                purchased_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS balance_codes (
                code TEXT PRIMARY KEY,
                amount INTEGER NOT NULL,
                redeemed BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bounty_codes (
                code TEXT PRIMARY KEY,
                amount INTEGER NOT NULL,
                redeemed BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS group_warns (
                id SERIAL PRIMARY KEY,
                group_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                warn_count INTEGER NOT NULL DEFAULT 0
            )
        """)


async def get_or_create_user(telegram_id: int, first_name: str, username: Optional[str] = None) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM game_users WHERE telegram_id = $1", telegram_id)
        is_owner = username and username.lower() in ["light_speedy", "light_speedi"]
        if row:
            updates = {}
            if row["first_name"] != first_name:
                updates["first_name"] = first_name
            if row["username"] != (username or None):
                updates["username"] = username
            if is_owner and not row["premium"]:
                updates["premium"] = True
                updates["premium_expires"] = None
            if updates:
                set_clause = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(updates.keys()))
                vals = list(updates.values())
                await conn.execute(
                    f"UPDATE game_users SET {set_clause} WHERE telegram_id = $1",
                    telegram_id, *vals
                )
            return dict(row) | updates
        await conn.execute(
            """INSERT INTO game_users (telegram_id, first_name, username, balance, kills, bounty_amount, premium)
               VALUES ($1, $2, $3, 1000, 0, 0, $4)
               ON CONFLICT (telegram_id) DO NOTHING""",
            telegram_id, first_name, username, bool(is_owner)
        )
        row = await conn.fetchrow("SELECT * FROM game_users WHERE telegram_id = $1", telegram_id)
        return dict(row)


async def get_user_by_id(telegram_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM game_users WHERE telegram_id = $1", telegram_id)
        return dict(row) if row else None


async def get_user_by_username(username: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM game_users WHERE username = $1",
            username.lstrip("@")
        )
        return dict(row) if row else None


def is_premium_active(user: dict) -> bool:
    if not user.get("premium"):
        return False
    expires = user.get("premium_expires")
    if expires is None:
        return True
    if isinstance(expires, datetime):
        return expires > datetime.utcnow()
    return False


def is_protected(user: dict) -> bool:
    until = user.get("protection_until")
    if not until:
        return False
    if isinstance(until, datetime):
        return until > datetime.utcnow()
    return False


async def get_global_rank(telegram_id: int, balance: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM game_users WHERE balance > $1", balance
        )
        return int(row["cnt"]) + 1


async def get_kill_rank(telegram_id: int) -> int:
    user = await get_user_by_id(telegram_id)
    if not user:
        return 9999
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM game_users WHERE kills > $1", user["kills"]
        )
        return int(row["cnt"]) + 1


def get_kill_tag(kills: int, kill_rank: int) -> str:
    if kills >= 200 and kill_rank <= 7:
        return " [𝗪𝗮𝗿𝗹𝗼𝗿𝗱 𝗼𝗳 𝗦𝗲𝗮]"
    if 100 <= kills < 200 and kill_rank <= 30:
        return " [𝗦𝘄𝗼𝗿𝗱𝘀𝗺𝗮𝗻]"
    return ""


async def get_user_ship(ship_id: Optional[int]) -> Optional[dict]:
    if not ship_id:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ships WHERE id = $1", ship_id)
        return dict(row) if row else None


async def get_ship_balance(ship_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COALESCE(SUM(gu.balance), 0) as total
               FROM ship_members sm
               JOIN game_users gu ON sm.user_id = gu.telegram_id
               WHERE sm.ship_id = $1""",
            ship_id
        )
        return int(row["total"])


async def get_ship_member_count(ship_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) as cnt FROM ship_members WHERE ship_id = $1", ship_id
        )
        return int(row["cnt"])


async def get_ship_member_role(ship_id: int, user_id: int) -> Optional[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT role FROM ship_members WHERE ship_id = $1 AND user_id = $2",
            ship_id, user_id
        )
        return row["role"] if row else None


async def get_ship_by_code(code: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ships WHERE code = $1", code)
        return dict(row) if row else None


async def get_ship_by_name(name: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ships WHERE LOWER(name) = LOWER($1)", name
        )
        return dict(row) if row else None


async def get_ship_by_id(ship_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ships WHERE id = $1", ship_id)
        return dict(row) if row else None


async def get_top_ships(limit: int = 30) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM ships")
    result = []
    for row in rows:
        s = dict(row)
        s["ship_balance"] = await get_ship_balance(s["id"])
        s["member_count"] = await get_ship_member_count(s["id"])
        result.append(s)
    result.sort(key=lambda x: x["ship_balance"], reverse=True)
    return result[:limit]


async def generate_unique_ship_code() -> str:
    while True:
        code = str(random.randint(1000, 9999))
        if not await get_ship_by_code(code):
            return code


async def get_user_items(user_id: int) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT item_name FROM user_items WHERE user_id = $1", user_id
        )
        return [r["item_name"] for r in rows]


async def get_most_expensive_item(user_id: int) -> Optional[str]:
    from constants import ITEMS
    owned = await get_user_items(user_id)
    if not owned:
        return None
    matching = [i for i in ITEMS if i["name"] in owned]
    if not matching:
        return None
    best = sorted(matching, key=lambda x: x["price"], reverse=True)[0]
    return f"{best['emoji']} {best['name']} (${best['price']:,})"


async def get_top_rich(limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM game_users ORDER BY balance DESC LIMIT $1", limit
        )
        return [dict(r) for r in rows]


async def get_top_killers(limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM game_users ORDER BY kills DESC LIMIT $1", limit
        )
        return [dict(r) for r in rows]


async def get_top_bounty(limit: int = 10) -> list:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM game_users ORDER BY bounty_amount DESC LIMIT $1", limit
        )
        return [dict(r) for r in rows]


async def generate_balance_code(amount: int) -> str:
    code = "BAL-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO balance_codes (code, amount, redeemed) VALUES ($1, $2, FALSE)",
            code, amount
        )
    return code


async def redeem_balance_code(code: str) -> Optional[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM balance_codes WHERE code = $1", code)
        if not row or row["redeemed"]:
            return None
        await conn.execute(
            "UPDATE balance_codes SET redeemed = TRUE WHERE code = $1", code
        )
        return row["amount"]


async def generate_bounty_code(amount: int) -> str:
    code = "BNT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bounty_codes (code, amount, redeemed) VALUES ($1, $2, FALSE)",
            code, amount
        )
    return code


async def redeem_bounty_code(code: str) -> Optional[int]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM bounty_codes WHERE code = $1", code)
        if not row or row["redeemed"]:
            return None
        await conn.execute(
            "UPDATE bounty_codes SET redeemed = TRUE WHERE code = $1", code
        )
        return row["amount"]


async def get_warn_count(group_id: int, user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT warn_count FROM group_warns WHERE group_id = $1 AND user_id = $2",
            group_id, user_id
        )
        return row["warn_count"] if row else 0


async def add_warn(group_id: int, user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT warn_count FROM group_warns WHERE group_id = $1 AND user_id = $2",
            group_id, user_id
        )
        if row:
            new_count = row["warn_count"] + 1
            await conn.execute(
                "UPDATE group_warns SET warn_count = $1 WHERE group_id = $2 AND user_id = $3",
                new_count, group_id, user_id
            )
        else:
            new_count = 1
            await conn.execute(
                "INSERT INTO group_warns (group_id, user_id, warn_count) VALUES ($1, $2, 1)",
                group_id, user_id
            )
        return new_count


async def remove_warn(group_id: int, user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT warn_count FROM group_warns WHERE group_id = $1 AND user_id = $2",
            group_id, user_id
        )
        if not row or row["warn_count"] <= 0:
            return 0
        new_count = max(0, row["warn_count"] - 1)
        await conn.execute(
            "UPDATE group_warns SET warn_count = $1 WHERE group_id = $2 AND user_id = $3",
            new_count, group_id, user_id
        )
        return new_count


async def reset_warns(group_id: int, user_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM group_warns WHERE group_id = $1 AND user_id = $2",
            group_id, user_id
        )


def rand(min_val: int, max_val: int) -> int:
    return random.randint(min_val, max_val)


def today_date() -> str:
    return date.today().isoformat()


async def update_user(telegram_id: int, **kwargs):
    if not kwargs:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        set_clause = ", ".join(f"{c} = ${i+2}" for i, c in enumerate(cols))
        await conn.execute(
            f"UPDATE game_users SET {set_clause} WHERE telegram_id = $1",
            telegram_id, *vals
        )
