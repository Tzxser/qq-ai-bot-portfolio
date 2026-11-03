"""Read only: report receipts and context counts, never send QQ messages."""
import asyncio
import json
from bot.config import Settings
from bot.persistence.postgres import PostgresStore


async def main():
    store = await PostgresStore.connect(Settings.from_env())
    try:
        rows = await store.pool.fetch("SELECT status,count(*) AS n FROM events WHERE created_at > now() - interval '1 hour' GROUP BY status")
        turns = await store.pool.fetchval("SELECT count(*) FROM turns WHERE created_at > now() - interval '1 hour'")
        print(json.dumps({"events_last_hour": {r["status"]: r["n"] for r in rows}, "context_turns_last_hour": turns}))
    finally:
        await store.close()


asyncio.run(main())
