import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bot.knowledge.fetch import fetch_draft

OUT = ROOT / "runtime" / "knowledge"

try:
    draft = fetch_draft()
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = OUT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps([draft], ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)
    print("KNOWLEDGE_DRAFT_OK: pending_review=true")
except Exception as exc:
    print("KNOWLEDGE_DRAFT_FAILED: " + type(exc).__name__)
    raise SystemExit(1)
