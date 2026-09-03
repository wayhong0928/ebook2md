"""
Append-only activity log (JSONL) + per-book history in manifest.
Every pipeline action is recorded here for auditing and history.
"""
import json
from datetime import datetime
from pathlib import Path

from config import PIPELINE_DIR
from logger import get_logger

log = get_logger("activity")

ACTIVITY_LOG = PIPELINE_DIR / "activity_log.jsonl"


def record(action: str, book_id: str | None = None, details: dict | None = None) -> None:
    """Append one action entry to activity_log.jsonl."""
    entry = {
        "ts": datetime.now().isoformat(),
        "action": action,
    }
    if book_id:
        entry["book_id"] = book_id
    if details:
        entry["details"] = details

    with open(ACTIVITY_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    log.debug("activity: %s | book=%s | %s", action, book_id or "-", details or {})


def record_book_action(action: str, book_id: str, details: dict | None = None) -> None:
    """Record action and append to the book's history inside manifest."""
    from manifest import load_manifest, save_manifest  # late import to avoid circular dep

    record(action, book_id=book_id, details=details)

    manifest = load_manifest()
    if book_id in manifest["books"]:
        history = manifest["books"][book_id].setdefault("activity_history", [])
        history.append({
            "ts": datetime.now().isoformat(),
            "action": action,
            **(details or {}),
        })
        save_manifest(manifest)


def tail(n: int = 20) -> list[dict]:
    """Return the last n activity log entries."""
    if not ACTIVITY_LOG.exists():
        return []
    lines = ACTIVITY_LOG.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[-n:]]


def print_recent(n: int = 20) -> None:
    entries = tail(n)
    if not entries:
        print("No activity recorded yet.")
        return
    print(f"=== Last {len(entries)} activity entries ===")
    for e in entries:
        book = f" [{e['book_id']}]" if "book_id" in e else ""
        details = f" — {e.get('details', '')}" if e.get("details") else ""
        print(f"  {e['ts'][:19]}  {e['action']}{book}{details}")


def book_history(book_id: str) -> None:
    """Print history for a specific book."""
    from manifest import load_manifest
    manifest = load_manifest()
    entry = manifest["books"].get(book_id)
    if not entry:
        print(f"Book not found: {book_id}")
        return
    history = entry.get("activity_history", [])
    if not history:
        print(f"No history for {book_id}")
        return
    print(f"=== History for '{book_id}' ({len(history)} entries) ===")
    for h in history:
        extras = {k: v for k, v in h.items() if k not in ("ts", "action")}
        detail_str = f"  — {extras}" if extras else ""
        print(f"  {h['ts'][:19]}  {h['action']}{detail_str}")
