"""Private, cross-process attempt history. Payloads and credentials never enter the journal."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .poa.errors import PoaContractError

LOG = logging.getLogger(__name__)
_WRITE_LOCK = threading.Lock()
_IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
FILTERS = {"application", "provider", "status", "since", "until", "before", "limit", "search"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
 id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, request_id TEXT NOT NULL,
 application TEXT NOT NULL, function TEXT NOT NULL, provider TEXT NOT NULL,
 model TEXT NOT NULL, status TEXT NOT NULL, diagnostic_code TEXT,
 duration_ms INTEGER NOT NULL, input_tokens INTEGER, output_tokens INTEGER
);
CREATE INDEX IF NOT EXISTS attempts_time ON attempts(timestamp);
CREATE INDEX IF NOT EXISTS attempts_application ON attempts(application, id);
CREATE INDEX IF NOT EXISTS attempts_provider ON attempts(provider, id);
"""


def journal_path(override: str | Path | None = None) -> Path:
    override = override or os.environ.get("SUBLLM_USAGE_DB")
    if override:
        return Path(override).expanduser().absolute()
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state").expanduser().absolute()
    return root / "subllm" / "usage.sqlite3"


def identifier(value: Any) -> str:
    # Do not turn arbitrary user headers, exception strings or provider payloads into logs.
    return value if isinstance(value, str) and _IDENT.fullmatch(value) else "unknown"


def _count(usage: Mapping[str, Any], *names: str) -> int | None:
    for name in names:
        value = usage.get(name)
        if type(value) is int and 0 <= value <= 10**12:
            return value
    return None


def archive_reference(value: Any) -> dict[str, str] | None:
    """An opaque exact reference, never a payload or a heuristic correlation."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"id", "day"}:
        raise ValueError("Invalid archive reference")
    if not isinstance(value["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", value["id"]):
        raise ValueError("Invalid archive reference")
    day = value["day"]
    if not isinstance(day, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
        raise ValueError("Invalid archive reference")
    datetime.strptime(day, "%Y-%m-%d")
    return {"id": value["id"], "day": day}


def record_attempt(
    *,
    request_id: str,
    application: str,
    function: str,
    provider: str,
    model: str,
    status: str,
    diagnostic_code: str | None,
    duration_ms: int,
    usage: Mapping[str, Any],
    event_key: str | None = None,
    archive_ref: dict[str, str] | None = None,
    strict: bool = False,
) -> bool:
    """Logging failure must never retry a paid request or replace its result."""
    try:
        reference = archive_reference(archive_ref)
        path = journal_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Exclusive creation prevents a window with world-readable default permissions.
        if path.is_symlink():
            raise OSError("Journal must not be a symbolic link")
        try:
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with _WRITE_LOCK, closing(sqlite3.connect(path, timeout=0.5)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            for statement in _SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            columns = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
            if "event_key" not in columns:
                db.execute("ALTER TABLE attempts ADD COLUMN event_key TEXT")
            for column in ("archive_id", "archive_day"):
                if column not in columns:
                    db.execute(f"ALTER TABLE attempts ADD COLUMN {column} TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS attempts_event ON attempts(event_key)")
            cursor = db.execute(
                "INSERT OR IGNORE INTO attempts(timestamp,request_id,application,function,provider,model,status,"
                "diagnostic_code,duration_ms,input_tokens,output_tokens,event_key,archive_id,archive_day) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(UTC).isoformat(timespec="milliseconds"),
                    hashlib.sha256(request_id.encode()).hexdigest()[:24],
                    identifier(application),
                    identifier(function),
                    identifier(provider),
                    identifier(model),
                    "success" if status == "success" else "error",
                    identifier(diagnostic_code) if diagnostic_code else None,
                    max(0, int(duration_ms)),
                    _count(usage, "input_tokens", "prompt_tokens"),
                    _count(usage, "output_tokens", "completion_tokens"),
                    hashlib.sha256(event_key.encode()).hexdigest() if event_key else None,
                    reference["id"] if reference else None,
                    reference["day"] if reference else None,
                ),
            )
        return cursor.rowcount == 1
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        if strict:
            raise PoaContractError("USAGE-STORAGE-001", "Usage history is temporarily unavailable") from exc
        # Fixed message only: database errors can contain sensitive paths or SQL values.
        LOG.warning("SubLLM usage journal unavailable; completion result preserved")
        return False


def _invalid() -> PoaContractError:
    return PoaContractError("USAGE-FILTER-001", "Invalid usage filter")


def _time(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(UTC).isoformat(timespec="milliseconds")
    except (ValueError, TypeError, AttributeError) as exc:
        raise _invalid() from exc


def query_usage(filters: Mapping[str, Any], database: str | Path | None = None) -> dict[str, Any]:
    """Read-only projection: querying an empty installation does not create a database."""
    if set(filters) - FILTERS:
        raise _invalid()
    where: list[str] = []
    values: list[Any] = []
    for key in ("application", "provider", "status"):
        if key in filters:
            value = filters[key]
            if identifier(value) != value or (key == "status" and value not in {"success", "error"}):
                raise _invalid()
            where.append(f"{key} = ?")
            values.append(value)
    for key, op in (("since", ">="), ("until", "<=")):
        if key in filters:
            where.append(f"timestamp {op} ?")
            values.append(_time(filters[key]))
    if "since" in filters and "until" in filters and _time(filters["since"]) > _time(filters["until"]):
        raise _invalid()
    try:
        limit = int(filters.get("limit", 100))
        before = int(filters["before"]) if "before" in filters else None
        if isinstance(filters.get("limit"), bool) or not 1 <= limit <= 500 or (before is not None and before < 1):
            raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise _invalid() from exc
    result: dict[str, Any] = {
        "schema": "subllm.usage/v1",
        "storage": "empty",
        "attempts": [],
        "next_before": None,
        "summary": {
            "attempts": 0,
            "requests": 0,
            "errors": 0,
            "input_tokens": None,
            "output_tokens": None,
            "usage_known": 0,
            "average_ms": None,
        },
        "applications": [],
        "providers": [],
        "coverage": "Instrumented SubLLM clients and transports reporting through the local usage ingest. "
        "Direct external API calls, local Ollama forwarding and code-edit transports are not included. "
        "Application identity is declared by the caller; missing identity appears as subactor-proxy.",
    }

    search = filters.get("search")
    if search is not None:
        if not isinstance(search, str) or len(search) > 256:
            raise _invalid()
        search = search.strip()
        if not search:
            search = None

    from .interaction_store import default_postgres_dsn

    postgres_dsn = None
    if isinstance(database, str) and (database.startswith("postgresql://") or database.startswith("postgres://")):
        postgres_dsn = database
    elif database is None and not os.environ.get("SUBLLM_USAGE_DB"):
        postgres_dsn = default_postgres_dsn()

    if postgres_dsn:
        try:
            from .interaction_store import InteractionStore

            root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state").expanduser().absolute()
            store = InteractionStore(directory=root / "subllm" / "archive", postgres_dsn=postgres_dsn)
            pg_res = store.query_attempts(
                application=filters.get("application"),
                provider=filters.get("provider"),
                status=filters.get("status"),
                since=filters.get("since"),
                until=filters.get("until"),
                before=filters.get("before"),
                limit=limit,
                include_payloads=True,
                search=search,
            )
            if pg_res["summary"]["attempts"] > 0 or not journal_path(database).exists():
                return pg_res
        except Exception as exc:
            LOG.warning("PostgreSQL usage query failed; falling back to SQLite: %s", exc)

    path = journal_path(database)
    if not path.exists():
        return result
    if search:
        where.append(
            "(application LIKE ? OR function LIKE ? OR provider LIKE ? OR model LIKE ? OR diagnostic_code LIKE ?)"
        )
        pattern = f"%{search}%"
        values.extend([pattern, pattern, pattern, pattern, pattern])
    clause = " WHERE " + " AND ".join(where) if where else ""
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.5)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")  # Page, totals and choices describe the same snapshot.
            summary = db.execute(
                "SELECT COUNT(*) attempts, COUNT(DISTINCT request_id) requests, "
                "COALESCE(SUM(status='error'),0) errors, SUM(input_tokens) input_tokens, "
                "SUM(output_tokens) output_tokens, "
                "COALESCE(SUM(input_tokens IS NOT NULL AND output_tokens IS NOT NULL),0) usage_known, "
                "ROUND(AVG(duration_ms)) average_ms FROM attempts" + clause,
                values,
            ).fetchone()
            result["summary"] = dict(summary)
            page_clause = clause
            page_values = list(values)
            if before is not None:
                page_clause += (" AND " if clause else " WHERE ") + "id < ?"
                page_values.append(before)
            rows = db.execute(
                "SELECT id,timestamp,request_id,application,function,provider,model,status,"
                "diagnostic_code,duration_ms,input_tokens,output_tokens FROM attempts"
                + page_clause
                + " ORDER BY id DESC LIMIT ?",
                [*page_values, limit + 1],
            ).fetchall()
            result["attempts"] = [dict(row) for row in rows[:limit]]
            result["next_before"] = rows[limit - 1]["id"] if len(rows) > limit else None
            for column, key in (("application", "applications"), ("provider", "providers")):
                result[key] = [
                    row[0] for row in db.execute(f"SELECT DISTINCT {column} FROM attempts ORDER BY {column} LIMIT 500")
                ]
            result["storage"] = "ready"
        return result
    except sqlite3.Error as exc:
        raise PoaContractError("USAGE-STORAGE-001", "Usage history is temporarily unavailable") from exc


def query_interaction_detail(record_id: str, database: str | Path | None = None) -> dict[str, Any] | None:
    from .interaction_store import get_default_interaction_store

    if not isinstance(record_id, str) or not 1 <= len(record_id) <= 128:
        return None
    archive_failed = False
    if re.fullmatch(r"[a-f0-9]{32}", record_id):
        try:
            store = get_default_interaction_store()
            detail = store.get_interaction(record_id) if store is not None else None
            if detail is not None:
                return {**detail, "payload_capture": {"state": "stored", "source": "private-archive"}}
        except Exception:
            archive_failed = True

    # Fallback to local SQLite attempt journal for numeric attempt IDs or correlation IDs
    path = journal_path(database)
    if not path.exists():
        if archive_failed:
            raise PoaContractError("USAGE-STORAGE-001", "Interaction archive is temporarily unavailable")
        return None
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.5)) as db:
            db.row_factory = sqlite3.Row
            columns = {row[1] for row in db.execute("PRAGMA table_info(attempts)")}
            projection = (
                "id,timestamp,request_id,application,function,provider,model,status,"
                "diagnostic_code,duration_ms,input_tokens,output_tokens,"
                + ("archive_id,archive_day" if {"archive_id", "archive_day"} <= columns
                   else "NULL AS archive_id,NULL AS archive_day")
            )
            row = None
            if record_id.isascii() and record_id.isdecimal() and len(record_id) <= 19 and int(record_id) < 2**63:
                row = db.execute(
                    f"SELECT {projection} FROM attempts WHERE id = ?",
                    (int(record_id),),
                ).fetchone()
            if row is None:
                row = db.execute(
                    f"SELECT {projection} FROM attempts WHERE request_id = ? ORDER BY id DESC LIMIT 2",
                    (record_id,),
                ).fetchall()
                if len(row) > 1:
                    raise PoaContractError("USAGE-DETAIL-001", "Select an individual usage attempt")
                row = row[0] if row else None
            if row is None:
                if archive_failed:
                    raise PoaContractError("USAGE-STORAGE-001", "Interaction archive is temporarily unavailable")
                return None
            data = dict(row)
            if data["archive_id"] is not None or data["archive_day"] is not None:
                return _linked_detail(data)
            return {
                "id": data["id"],
                "day": data["timestamp"][:10],
                "started_at": data["timestamp"],
                "finished_at": data["timestamp"],
                "duration_ms": data["duration_ms"],
                "kind": "llm_attempt",
                "caller": data["application"],
                "target": f"{data['provider']}/{data['model']}",
                "direction": "outbound",
                "correlation_id": data["request_id"],
                "status": data["status"],
                "request": None,
                "response": None,
                # The journal never stores payloads. Their absence here says
                # nothing about unlinked records in a private proxy archive.
                "payload_capture": {
                    "state": "unlinked", "source": "usage-journal", "reason": "no_archive_reference",
                },
                "diagnostic": {"code": data["diagnostic_code"]} if data["diagnostic_code"] else None,
                "metadata": {
                    "application": data["application"],
                    "function": data["function"],
                    "provider": data["provider"],
                    "model": data["model"],
                    "input_tokens": data["input_tokens"],
                    "output_tokens": data["output_tokens"],
                },
            }
    except sqlite3.Error as exc:
        raise PoaContractError("USAGE-STORAGE-001", "Usage history is temporarily unavailable") from exc


def _linked_detail(attempt: Mapping[str, Any]) -> dict[str, Any]:
    from .interaction_store import get_default_interaction_store

    try:
        reference = archive_reference({"id": attempt["archive_id"], "day": attempt["archive_day"]})
        store = get_default_interaction_store()
        detail = store.get_interaction(reference["id"], day=reference["day"]) if store is not None else None
    except Exception as exc:
        raise PoaContractError("USAGE-STORAGE-001", "Interaction archive is temporarily unavailable") from exc
    if detail is None:
        raise PoaContractError("USAGE-STORAGE-001", "Referenced interaction archive is unavailable")
    metadata = detail.get("metadata", {})
    correlation = detail.get("correlation_id")
    if (
        detail.get("id") != reference["id"] or detail.get("day") != reference["day"]
        or detail.get("caller") != attempt["application"]
        or detail.get("status") != attempt["status"]
        or not isinstance(correlation, str)
        or hashlib.sha256(correlation.encode()).hexdigest()[:24] != attempt["request_id"]
        or not isinstance(metadata, dict)
        or any(metadata.get(key) != attempt[key] for key in ("application", "function", "provider", "model"))
    ):
        raise PoaContractError("USAGE-DETAIL-001", "Interaction archive reference does not match the usage attempt")
    return {**detail, "usage_attempt_id": attempt["id"],
            "payload_capture": {"state": "stored", "source": "private-archive"}}
