import json
from datetime import datetime, timedelta, timezone

import asyncpg

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (version integer PRIMARY KEY);
CREATE TABLE IF NOT EXISTS events (
    event_key text PRIMARY KEY, conversation_key text NOT NULL,
    status text NOT NULL DEFAULT 'claimed', reply_id text,
    created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_created_idx ON events(created_at);
CREATE TABLE IF NOT EXISTS turns (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_key text NOT NULL UNIQUE REFERENCES events(event_key),
    conversation_key text NOT NULL, user_text text NOT NULL, assistant_text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS turns_conversation_idx ON turns(conversation_key, id DESC);
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS outbound_messages (
    message_id text PRIMARY KEY, self_id text NOT NULL, group_id text,
    user_id text, event_key text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS outbound_group_idx ON outbound_messages(group_id, created_at);
INSERT INTO schema_versions(version) VALUES (2) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS usage_events (
    event_key text PRIMARY KEY,
    group_id text,
    user_key text,
    attempts integer NOT NULL DEFAULT 0,
    input_tokens integer NOT NULL DEFAULT 0,
    generated_tokens integer NOT NULL DEFAULT 0,
    cache_hit_tokens integer NOT NULL DEFAULT 0,
    cache_miss_tokens integer NOT NULL DEFAULT 0,
    reasoning_tokens integer NOT NULL DEFAULT 0,
    elapsed_ms integer NOT NULL DEFAULT 0,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS usage_created_idx ON usage_events(created_at);
INSERT INTO schema_versions(version) VALUES (3) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS inbox_tasks (
    event_key text PRIMARY KEY REFERENCES events(event_key) ON DELETE CASCADE,
    conversation_key text NOT NULL,
    self_id text NOT NULL, user_id text NOT NULL, group_id text,
    message_id text NOT NULL, original_time bigint NOT NULL,
    source text NOT NULL DEFAULT 'live', body text NOT NULL,
    message_json jsonb NOT NULL,
    state text NOT NULL DEFAULT 'received',
    received_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    lease_owner text, lease_until timestamptz,
    version bigint NOT NULL DEFAULT 0,
    session_generation bigint NOT NULL DEFAULT 0,
    attempt_count integer NOT NULL DEFAULT 0,
    answer_id text, answer_text text, answer_parts jsonb,
    finish_reason text, provider_usage jsonb,
    delivery_unknown_reason text, cancelled_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS inbox_recovery_idx ON inbox_tasks(state, expires_at, received_at);
ALTER TABLE inbox_tasks ADD COLUMN IF NOT EXISTS version bigint NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS outbox_tasks (
    job_id text PRIMARY KEY,
    event_key text NOT NULL REFERENCES inbox_tasks(event_key) ON DELETE CASCADE,
    part_index integer NOT NULL,
    self_id text NOT NULL, user_id text NOT NULL, group_id text,
    body text NOT NULL, state text NOT NULL DEFAULT 'ready_to_send',
    send_attempt_id text, send_started_at timestamptz,
    message_id text, confirmed_at timestamptz,
    expires_at timestamptz NOT NULL,
    delivery_unknown_reason text,
    UNIQUE(event_key, part_index)
);
CREATE INDEX IF NOT EXISTS outbox_recovery_idx ON outbox_tasks(state, expires_at);
INSERT INTO schema_versions(version) VALUES (4) ON CONFLICT DO NOTHING;
"""


class PostgresStore:
    def __init__(self, pool):
        self.pool = pool

    @classmethod
    async def connect(cls, settings):
        pool = await asyncpg.create_pool(host=settings.pg_host, user=settings.pg_user,
            password=settings.postgres_password, database=settings.pg_db,
            min_size=1, max_size=3, command_timeout=10, timeout=10)
        async with pool.acquire() as con:
            async with con.transaction():
                await con.execute("SELECT pg_advisory_xact_lock(817032)")
                await con.execute(SCHEMA)
        return cls(pool)

    async def healthy(self):
        return await self.pool.fetchval("SELECT 1") == 1

    async def claim(self, event_key, conversation_key):
        result = await self.pool.fetchval("INSERT INTO events(event_key, conversation_key) VALUES($1,$2) "
            "ON CONFLICT DO NOTHING RETURNING event_key", event_key, conversation_key)
        return result is not None

    async def persist_inbox(self, event_key, message, conversation_key, source="live",
                            ttl_seconds=7200):
        """Persist a bounded accepted message before it enters the memory queue."""
        from bot.gateway.events import message_to_dict

        expires = datetime.now(timezone.utc) + timedelta(seconds=max(60, int(ttl_seconds)))
        payload = json.dumps(message_to_dict(message), ensure_ascii=False)
        await self.pool.execute(
            "INSERT INTO inbox_tasks(event_key,conversation_key,self_id,user_id,group_id,message_id,"
            "original_time,source,body,message_json,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11) "
            "ON CONFLICT(event_key) DO NOTHING",
            str(event_key), str(conversation_key), str(message.self_id), str(message.user_id),
            str(message.group_id) if message.group_id is not None else None, str(message.message_id),
            int(message.timestamp), str(source), str(message.text), payload, expires,
        )

    async def save_answer(self, event_key, message, answer, parts, result=None, ttl_seconds=7200):
        """Commit the canonical answer and outbox parts before any WS send."""
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(60, int(ttl_seconds)))
        result = result if result is not None else {}
        usage = result.get("usage", {}) if isinstance(result, dict) else getattr(result, "usage", {})
        finish = result.get("finish_reason") if isinstance(result, dict) else getattr(result, "finish_reason", None)
        answer_id = f"answer:{event_key}"
        parts_json = json.dumps(list(parts), ensure_ascii=False)
        usage_json = json.dumps(usage if isinstance(usage, dict) else {}, ensure_ascii=False)
        async with self.pool.acquire() as con:
            async with con.transaction():
                await con.execute(
                    "UPDATE inbox_tasks SET state='ready_to_send', answer_id=$2, answer_text=$3, "
                    "answer_parts=$4::jsonb, finish_reason=$5, provider_usage=$6::jsonb, "
                    "expires_at=$7, updated_at=now() WHERE event_key=$1",
                    str(event_key), answer_id, str(answer), parts_json, finish, usage_json, expires,
                )
                for index, part in enumerate(parts):
                    await con.execute(
                        "INSERT INTO outbox_tasks(job_id,event_key,part_index,self_id,user_id,group_id,body,expires_at) "
                        "VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(event_key,part_index) DO UPDATE SET body=EXCLUDED.body",
                        f"{event_key}:{index}", str(event_key), index, str(message.self_id),
                        str(message.user_id), str(message.group_id) if message.group_id is not None else None,
                        str(part), expires,
                    )

    async def recoverable_tasks(self, limit=100):
        rows = await self.pool.fetch(
            "SELECT event_key, conversation_key, state, source, message_json, answer_text, answer_parts, "
            "finish_reason, provider_usage, expires_at FROM inbox_tasks "
            "WHERE expires_at > now() AND state IN ('received','queued','generated','ready_to_send') "
            "AND (lease_until IS NULL OR lease_until < now()) "
            "ORDER BY received_at ASC LIMIT $1", int(limit))
        result = []
        for row in rows:
            item = dict(row)
            for key in ("message_json", "answer_parts", "provider_usage"):
                value = item.get(key)
                if isinstance(value, str):
                    try:
                        item[key] = json.loads(value)
                    except json.JSONDecodeError:
                        item[key] = None
            result.append(item)
        return result

    async def acquire_recovery_lease(self, event_key, owner, seconds=180):
        row = await self.pool.fetchrow(
            "UPDATE inbox_tasks SET lease_owner=$2, lease_until=now()+($3 * interval '1 second'), "
            "version=version+1, updated_at=now() WHERE event_key=$1 AND expires_at > now() "
            "AND (lease_until IS NULL OR lease_until < now()) RETURNING version",
            str(event_key), str(owner), int(seconds))
        return row is not None

    async def release_recovery_lease(self, event_key, owner):
        await self.pool.execute(
            "UPDATE inbox_tasks SET lease_owner=NULL, lease_until=NULL, updated_at=now() "
            "WHERE event_key=$1 AND lease_owner=$2", str(event_key), str(owner))

    async def mark_outbox_sending(self, job_id, attempt_id):
        return await self.pool.execute(
            "UPDATE outbox_tasks SET state='sending', send_attempt_id=$2, send_started_at=now() "
            "WHERE job_id=$1 AND state='ready_to_send'", str(job_id), str(attempt_id))

    async def mark_outbox_sent(self, job_id, message_id):
        await self.pool.execute(
            "UPDATE outbox_tasks SET state='sent', message_id=$2, confirmed_at=now() WHERE job_id=$1",
            str(job_id), str(message_id))

    async def cancel_tasks(self, conversation_key):
        await self.pool.execute(
            "UPDATE inbox_tasks SET state='cancelled', cancelled_at=now(), updated_at=now() "
            "WHERE conversation_key=$1 AND state NOT IN ('sent','failed','cancelled','expired')",
            str(conversation_key))
        await self.pool.execute(
            "UPDATE outbox_tasks SET state='cancelled' WHERE event_key IN "
            "(SELECT event_key FROM inbox_tasks WHERE conversation_key=$1) "
            "AND state NOT IN ('sent','cancelled')", str(conversation_key))

    async def mark(self, event_key, status, reply_id=None):
        await self.pool.execute("UPDATE events SET status=$2, reply_id=$3, updated_at=now() WHERE event_key=$1",
            event_key, status, reply_id)
        await self.pool.execute("UPDATE inbox_tasks SET state=$2, delivery_unknown_reason=$3, updated_at=now() "
                                "WHERE event_key=$1", event_key, status,
                                status if status == "delivery_uncertain" else None)

    async def history(self, conversation_key, limit):
        rows = await self.pool.fetch("SELECT user_text, assistant_text FROM turns WHERE conversation_key=$1 "
            "ORDER BY id DESC LIMIT $2", conversation_key, limit)
        result = []
        for row in reversed(rows):
            result.extend([{"role": "user", "content": row["user_text"]},
                           {"role": "assistant", "content": row["assistant_text"]}])
        return result

    async def clear_conversation(self, conversation_key):
        await self.pool.execute("DELETE FROM turns WHERE conversation_key=$1", conversation_key)

    async def complete(self, event_key, conversation_key, user, assistant, reply_id, keep):
        async with self.pool.acquire() as con:
            async with con.transaction():
                await con.execute("INSERT INTO turns(event_key,conversation_key,user_text,assistant_text) "
                    "VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING", event_key, conversation_key, user, assistant)
                await con.execute("UPDATE events SET status='sent', reply_id=$2, updated_at=now() WHERE event_key=$1",
                    event_key, str(reply_id))
                await con.execute("UPDATE inbox_tasks SET state='sent', lease_owner=NULL, lease_until=NULL, "
                                  "updated_at=now() WHERE event_key=$1", event_key)
                await con.execute("DELETE FROM turns WHERE conversation_key=$1 AND id NOT IN "
                    "(SELECT id FROM turns WHERE conversation_key=$1 ORDER BY id DESC LIMIT $2)",
                    conversation_key, keep)

    async def record_outbound(self, message_id, self_id, group_id=None, user_id=None, event_key=None):
        await self.pool.execute(
            "INSERT INTO outbound_messages(message_id,self_id,group_id,user_id,event_key) "
            "VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
            str(message_id), str(self_id), str(group_id) if group_id is not None else None,
            str(user_id) if user_id is not None else None, event_key,
        )

    async def is_known_bot_reply(self, message_id, group_id=None):
        if message_id is None:
            return False
        row = await self.pool.fetchrow(
            "SELECT 1 FROM outbound_messages WHERE message_id=$1 AND ($2::text IS NULL OR group_id=$2)",
            str(message_id), str(group_id) if group_id is not None else None,
        )
        return row is not None

    async def record_usage(self, event_key, group_id, user_key, attempts, usage, elapsed_ms, status):
        usage = usage if isinstance(usage, dict) else {}
        await self.pool.execute(
            "INSERT INTO usage_events(event_key,group_id,user_key,attempts,input_tokens,generated_tokens,"
            "cache_hit_tokens,cache_miss_tokens,reasoning_tokens,elapsed_ms,status) "
            "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT (event_key) DO UPDATE SET "
            "attempts=EXCLUDED.attempts,input_tokens=EXCLUDED.input_tokens,generated_tokens=EXCLUDED.generated_tokens,"
            "cache_hit_tokens=EXCLUDED.cache_hit_tokens,cache_miss_tokens=EXCLUDED.cache_miss_tokens,"
            "reasoning_tokens=EXCLUDED.reasoning_tokens,elapsed_ms=EXCLUDED.elapsed_ms,status=EXCLUDED.status",
            str(event_key), str(group_id) if group_id is not None else None,
            str(user_key) if user_key is not None else None, int(attempts or 0),
            int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0),
            int(usage.get("prompt_cache_hit_tokens", 0) or 0), int(usage.get("prompt_cache_miss_tokens", 0) or 0),
            int(usage.get("reasoning_tokens", 0) or 0), int(elapsed_ms or 0), str(status),
        )

    async def prune(self, days):
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.pool.acquire() as con:
            async with con.transaction():
                await con.execute("DELETE FROM turns WHERE created_at < $1", cutoff)
                await con.execute("DELETE FROM events WHERE created_at < $1 AND NOT EXISTS "
                                  "(SELECT 1 FROM turns WHERE turns.event_key=events.event_key)", cutoff)
                await con.execute("DELETE FROM outbound_messages WHERE created_at < $1", cutoff)
                await con.execute("DELETE FROM usage_events WHERE created_at < $1", cutoff)
                await con.execute("DELETE FROM inbox_tasks WHERE expires_at < now()")
                await con.execute("DELETE FROM outbox_tasks WHERE expires_at < now()")

    async def close(self):
        await self.pool.close()
