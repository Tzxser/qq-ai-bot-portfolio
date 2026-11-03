import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit


DEFAULT_SOURCE = "https://acm.xinciqq.top/"


@dataclass(frozen=True)
class KnowledgeRecord:
    id: str
    title: str
    body: str
    category: str
    source_type: str
    source_url: str | None = None
    source_ref: str | None = None
    group_scope: tuple[str, ...] = ()
    source_updated_at: str | None = None
    fetched_at: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    review_status: str = "pending"
    reviewed_by: str | None = None
    version: int = 1
    content_hash: str = ""
    owner_department: str | None = None

    def __post_init__(self):
        if not self.content_hash:
            object.__setattr__(self, "content_hash",
                               hashlib.sha256(self.body.encode("utf-8")).hexdigest())


def validate_source_url(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname == "acm.xinciqq.top"
            and not parts.username and not parts.password and not parts.query and not parts.fragment)


class KnowledgeService:
    """Small reviewed-record retrieval layer; no online fetch or vector DB."""

    def __init__(self, records=()):
        self.records = tuple(records)

    @classmethod
    def empty(cls):
        return cls(())

    @classmethod
    def from_json(cls, path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("knowledge file must be a list")
        records = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            source_url = item.get("source_url")
            if source_url and not validate_source_url(source_url):
                raise ValueError("knowledge source is outside the allowlist")
            records.append(KnowledgeRecord(**item))
        return cls(records)

    def search(self, query, group_id=None, limit=3, now=None):
        now = now or datetime.now(timezone.utc)
        tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", (query or "").lower()))
        candidates = []
        for record in self.records:
            if record.review_status != "approved":
                continue
            if group_id and record.group_scope and str(group_id) not in record.group_scope:
                continue
            if record.valid_until:
                try:
                    if now >= datetime.fromisoformat(record.valid_until.replace("Z", "+00:00")):
                        continue
                except ValueError:
                    continue
            haystack = set(re.findall(r"[\w\u4e00-\u9fff]+", (record.title + " " + record.body).lower()))
            score = len(tokens & haystack)
            if query and query.lower().replace(" ", "") in (record.title + record.body).lower().replace(" ", ""):
                score += 1
            if score:
                candidates.append((score, record))
        candidates.sort(key=lambda item: (-item[0], item[1].id))
        return tuple(record for _, record in candidates[:max(0, min(limit, 3))])
