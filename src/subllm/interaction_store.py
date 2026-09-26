"""Private interaction archive. Never copy payloads into public operational logs."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from collections.abc import Mapping
from typing import Any

from .interaction_events import canonical, make_event

DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
IDENT = re.compile(r"[a-f0-9]{32}\Z")
DEFAULT_LOCAL_POSTGRES_PORT = 15439
DEFAULT_LOCAL_POSTGRES_DSN = (
    "postgresql://subllm:JmOTxQvLA2uhUrN-IMsjAkoIOGVr3nN4lQgDMlEAtkuWXKRy@127.0.0.1:15439/subllm"
)


def default_postgres_dsn(environ: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    candidates = ("SUBLLM_POSTGRES_DSN", "SUBLLM_DATABASE_URL", "SUBLLM_GATEWAY_DATABASE_URL")
    for name in candidates:
        val = env.get(name, "").strip()
        if val:
            return val
    try:
        from .credential_env import merged_environment

        merged = merged_environment(environ=environ)
        for name in candidates:
            val = merged.get(name, "").strip()
            if val:
                return val
    except Exception:
        pass
    local_dev = env.get("SUBLLM_USE_LOCAL_POSTGRES", "1").strip().lower()
    if local_dev not in {"0", "false", "no"}:
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.05)
            result = sock.connect_ex(("127.0.0.1", DEFAULT_LOCAL_POSTGRES_PORT))
            sock.close()
            if result == 0:
                return DEFAULT_LOCAL_POSTGRES_DSN
        except Exception:
            pass
    return None


_DEFAULT_STORE: InteractionStore | None = None


def get_default_interaction_store(environ: Mapping[str, str] | None = None) -> InteractionStore | None:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is not None:
        return _DEFAULT_STORE
    dsn = default_postgres_dsn(environ=environ)
    env = os.environ if environ is None else environ
    archive_dir = env.get("SUBLLM_ARCHIVE_DIR")
    if not dsn and not archive_dir:
        return None
    root = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state").expanduser().absolute()
    directory = Path(archive_dir).expanduser().absolute() if archive_dir else root / "subllm" / "archive"
    _DEFAULT_STORE = InteractionStore(directory=directory, postgres_dsn=dsn)
    return _DEFAULT_STORE


def set_default_interaction_store(store: InteractionStore | None) -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = store


def utc_now():
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def checked_day(day):
    if not isinstance(day, str) or not DAY.fullmatch(day):
        raise ValueError("Expected UTC day YYYY-MM-DD")
    datetime.strptime(day, "%Y-%m-%d")
    return day


class InteractionStore:
    def __init__(self, directory: Path, postgres_dsn: str | None = None):
        self.directory = directory
        self.dsn = postgres_dsn

    @contextmanager
    def connect(self, day, write=False):
        checked_day(day)
        if self.dsn:
            import psycopg

            with psycopg.connect(self.dsn, connect_timeout=5) as db:
                if not write:
                    db.read_only = True
                if write:
                    # Serialize first-use DDL across service processes.
                    db.execute("SELECT pg_advisory_xact_lock(861940)")
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS interactions "
                        "(day date NOT NULL, id text NOT NULL, document text NOT NULL, "
                        "PRIMARY KEY(day,id)) PARTITION BY RANGE(day)"
                    )
                    from datetime import timedelta

                    following = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                    table = "interactions_" + day.replace("-", "")
                    db.execute(
                        f"CREATE TABLE IF NOT EXISTS {table} PARTITION OF interactions "
                        f"FOR VALUES FROM ('{day}') TO ('{following}')"
                    )
                if write:
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS operational_events "
                        "(day TEXT, sequence INTEGER, event TEXT NOT NULL, PRIMARY KEY(day,sequence))"
                    )
                if write:
                    db.execute(
                        "CREATE INDEX IF NOT EXISTS interaction_started ON interactions "
                        "(day, ((document::jsonb->>'started_at')),id)"
                    )
                yield db
            return
        path = self.directory / f"{day}.sqlite3"
        if write:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.directory.is_symlink() or path.is_symlink():
                raise OSError("Archive symlinks are forbidden")
            if self.directory.stat().st_mode & 0o077:
                raise OSError("Archive directory must be private (0700)")
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            if path.stat().st_mode & 0o077:
                raise OSError("Archive file must be private (0600)")
        elif not path.exists():
            yield None
            return
        elif path.is_symlink():
            raise OSError("Archive symlinks are forbidden")
        db = sqlite3.connect(path if write else path.as_uri() + "?mode=ro", uri=not write, timeout=5)
        try:
            with db:
                if write:
                    db.execute("BEGIN IMMEDIATE")
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS interactions "
                        "(day TEXT NOT NULL, id TEXT NOT NULL, document TEXT NOT NULL, PRIMARY KEY(day,id))"
                    )
                    db.execute(
                        "CREATE TABLE IF NOT EXISTS operational_events "
                        "(day TEXT, sequence INTEGER, event TEXT NOT NULL, PRIMARY KEY(day,sequence))"
                    )
                    db.execute(
                        "CREATE INDEX IF NOT EXISTS interaction_started ON interactions "
                        "(json_extract(document,'$.started_at'),id)"
                    )
                yield db
        finally:
            db.close()

    def sql(self, db, query, args=()):
        return db.execute(query.replace("?", "%s") if self.dsn else query, args)

    def append_event(self, db, record):
        row = self.sql(
            db,
            "SELECT sequence,event FROM operational_events WHERE day=? ORDER BY sequence DESC LIMIT 1",
            (record["day"],),
        ).fetchone()
        sequence, previous = (row[0] + 1, json.loads(row[1])["eventHash"]) if row else (1, "0" * 64)
        event = make_event(record, sequence, previous)
        self.sql(
            db,
            "INSERT INTO operational_events(day,sequence,event) VALUES(?,?,?)",
            (record["day"], sequence, canonical(event)),
        )

    def begin(self, *, kind, caller, target, request, direction="client_to_server", correlation_id=None):
        stamp = utc_now()
        record = dict(
            id=uuid.uuid4().hex,
            day=stamp[:10],
            started_at=stamp,
            finished_at=None,
            duration_ms=None,
            kind=kind,
            caller=caller,
            target=target,
            direction=direction,
            correlation_id=correlation_id or uuid.uuid4().hex,
            status="pending",
            request=request,
            response=None,
            diagnostic=None,
        )
        with self.connect(record["day"], True) as db:
            self.sql(
                db,
                "INSERT INTO interactions(day,id,document) VALUES(?,?,?)",
                (record["day"], record["id"], json.dumps(record, ensure_ascii=False)),
            )
            self.append_event(db, record)
        return record

    def finish(self, record, response, *, duration_ms=0, diagnostic=None, metadata=None):
        record = {
            **record,
            "finished_at": utc_now(),
            "duration_ms": max(0, int(duration_ms)),
            "status": "error" if diagnostic else "success",
            "response": response,
            "diagnostic": diagnostic,
            "metadata": metadata or {},
        }
        with self.connect(record["day"], True) as db:
            self.sql(
                db,
                "UPDATE interactions SET document=? WHERE day=? AND id=?",
                (json.dumps(record, ensure_ascii=False), record["day"], record["id"]),
            )
            self.append_event(db, record)
        return record

    def query(
        self,
        day,
        record_id=None,
        *,
        kind=None,
        caller=None,
        status=None,
        limit=100,
        before=None,
        include_payloads: bool = False,
    ):
        checked_day(day)
        if record_id is not None and not IDENT.fullmatch(record_id):
            raise ValueError("Invalid interaction id")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("Limit must be between 1 and 500")
        with self.connect(day) as db:
            if db is None:
                return None if record_id else []
            # Use indexed exact lookup for payloads; bounded SQL metadata projection for lists.
            if record_id:
                row = self.sql(
                    db, "SELECT document FROM interactions WHERE day=? AND id=?", (day, record_id)
                ).fetchone()
                return json.loads(row[0]) if row else None

            def expr(field):
                return f"document::jsonb->>'{field}'" if self.dsn else f"json_extract(document,'$.{field}')"

            clauses, args = ["day=?"], [day]
            for key, val in (("kind", kind), ("caller", caller), ("status", status)):
                if val:
                    clauses.append(expr(key) + "=?")
                    args.append(val)
            if before:
                clauses.append(expr("started_at") + " < ?")
                args.append(before)
            args.append(limit)
            if include_payloads:
                projection = "document"
            else:
                projection = (
                    "(document::jsonb - 'request' - 'response')::text"
                    if self.dsn
                    else "json_remove(document,'$.request','$.response')"
                )
            rows = self.sql(
                db,
                "SELECT "
                + projection
                + " FROM interactions WHERE "
                + " AND ".join(clauses)
                + " ORDER BY "
                + expr("started_at")
                + " DESC,id DESC LIMIT ?",
                args,
            ).fetchall()
            if include_payloads:
                return [json.loads(row[0]) for row in rows]
            return [{k: v for k, v in json.loads(row[0]).items() if k not in ("request", "response")} for row in rows]

    def get_interaction(self, record_id: str, day: str | None = None) -> dict[str, Any] | None:
        if not IDENT.fullmatch(record_id):
            raise ValueError("Invalid interaction id")
        if day:
            checked_day(day)
            with self.connect(day) as db:
                if db is None:
                    return None
                row = self.sql(
                    db, "SELECT document FROM interactions WHERE day=? AND id=?", (day, record_id)
                ).fetchone()
                return json.loads(row[0]) if row else None
        if self.dsn:
            import psycopg

            with psycopg.connect(self.dsn, connect_timeout=5) as db:
                db.read_only = True
                row = db.execute("SELECT document FROM interactions WHERE id = %s LIMIT 1", (record_id,)).fetchone()
                return json.loads(row[0]) if row else None
        if self.directory.exists():
            for candidate in sorted(self.directory.glob("????-??-??.sqlite3"), reverse=True)[:30]:
                doc = self.query(candidate.stem, record_id)
                if doc:
                    return doc
        return None

    def query_attempts(
        self,
        *,
        application: str | None = None,
        provider: str | None = None,
        status: str | None = None,
        since: str | None = None,
        until: str | None = None,
        before: str | None = None,
        limit: int = 100,
        include_payloads: bool = True,
        search: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("Limit must be between 1 and 500")
        if self.dsn:
            import psycopg

            with psycopg.connect(self.dsn, connect_timeout=5) as db:
                db.read_only = True
                clauses = ["document::jsonb->>'kind' IN ('llm', 'llm_attempt')"]
                args: list[Any] = []
                if application:
                    clauses.append("document::jsonb->>'caller' = %s")
                    args.append(application)
                if status:
                    clauses.append("document::jsonb->>'status' = %s")
                    args.append(status)
                if provider:
                    clauses.append(
                        "(document::jsonb->'metadata'->>'provider' = %s OR document::jsonb->>'target' LIKE %s)"
                    )
                    args.append(provider)
                    args.append(f"{provider}/%")
                if since:
                    clauses.append("document::jsonb->>'started_at' >= %s")
                    args.append(since)
                if until:
                    clauses.append("document::jsonb->>'started_at' <= %s")
                    args.append(until)
                if before:
                    clauses.append("document::jsonb->>'started_at' < %s")
                    args.append(before)
                if search:
                    clauses.append("document::text ILIKE %s")
                    args.append(f"%{search}%")
                where_clause = " WHERE " + " AND ".join(clauses)

                sum_sql = (
                    "SELECT "
                    "COUNT(*) as attempts, "
                    "COUNT(DISTINCT document::jsonb->>'correlation_id') as requests, "
                    "COALESCE(SUM(CASE WHEN document::jsonb->>'status' = 'error' THEN 1 ELSE 0 END), 0) as errors, "
                    "SUM(COALESCE((document::jsonb->'metadata'->>'input_tokens')::numeric, (document::jsonb->'response'->'usage'->>'prompt_tokens')::numeric, 0)) as input_tokens, "
                    "SUM(COALESCE((document::jsonb->'metadata'->>'output_tokens')::numeric, (document::jsonb->'response'->'usage'->>'completion_tokens')::numeric, 0)) as output_tokens, "
                    "ROUND(AVG(COALESCE((document::jsonb->>'duration_ms')::numeric, 0))) as average_ms, "
                    "COALESCE(SUM(CASE WHEN (document::jsonb->'metadata'->>'input_tokens' IS NOT NULL OR document::jsonb->'response'->'usage'->>'prompt_tokens' IS NOT NULL) THEN 1 ELSE 0 END), 0) as usage_known "
                    f"FROM interactions {where_clause}"
                )
                sum_row = db.execute(sum_sql, args).fetchone()

                apps = [
                    r[0]
                    for r in db.execute(
                        "SELECT DISTINCT document::jsonb->>'caller' FROM interactions "
                        "WHERE document::jsonb->>'caller' IS NOT NULL ORDER BY 1 LIMIT 500"
                    ).fetchall()
                ]
                provs = [
                    r[0]
                    for r in db.execute(
                        "SELECT DISTINCT COALESCE(document::jsonb->'metadata'->>'provider', split_part(document::jsonb->>'target', '/', 1)) "
                        "FROM interactions WHERE document::jsonb->>'target' IS NOT NULL ORDER BY 1 LIMIT 500"
                    ).fetchall()
                ]

                proj = "document" if include_payloads else "(document::jsonb - 'request' - 'response')::text"
                rows_sql = (
                    f"SELECT id, day, {proj} FROM interactions {where_clause} "
                    "ORDER BY (document::jsonb->>'started_at') DESC, id DESC LIMIT %s"
                )
                rows = db.execute(rows_sql, [*args, limit + 1]).fetchall()
                attempts_list = []
                for row in rows[:limit]:
                    doc = json.loads(row[2])
                    meta = doc.get("metadata") or {}
                    resp = doc.get("response") or {}
                    usage_info = resp.get("usage") or {}
                    inp_tok = (
                        meta.get("input_tokens")
                        or usage_info.get("prompt_tokens")
                        or usage_info.get("input_tokens")
                    )
                    out_tok = (
                        meta.get("output_tokens")
                        or usage_info.get("completion_tokens")
                        or usage_info.get("output_tokens")
                    )
                    target = doc.get("target") or ""
                    prov = meta.get("provider") or (target.split("/")[0] if "/" in target else "unknown")
                    model = meta.get("model") or (target.split("/", 1)[1] if "/" in target else target)
                    diag = doc.get("diagnostic") or {}
                    diag_code = (
                        diag.get("code")
                        if isinstance(diag, dict)
                        else (diag if isinstance(diag, str) else None)
                    )

                    item: dict[str, Any] = {
                        "id": doc.get("id", row[0]),
                        "timestamp": doc.get("started_at", ""),
                        "request_id": doc.get("correlation_id", doc.get("id", "")),
                        "application": doc.get("caller", "unknown"),
                        "function": meta.get("function", "chat"),
                        "provider": prov,
                        "model": model,
                        "status": doc.get("status", "success"),
                        "diagnostic_code": diag_code,
                        "duration_ms": doc.get("duration_ms") or 0,
                        "input_tokens": int(inp_tok) if inp_tok is not None else None,
                        "output_tokens": int(out_tok) if out_tok is not None else None,
                    }
                    if include_payloads:
                        item["request"] = doc.get("request")
                        item["response"] = doc.get("response")
                    attempts_list.append(item)

                next_before = attempts_list[-1]["timestamp"] if len(rows) > limit else None
                s_attempts, s_requests, s_errors, s_inp, s_out, s_avg, s_known = sum_row
                return {
                    "schema": "subllm.usage/v1",
                    "storage": "postgres",
                    "attempts": attempts_list,
                    "next_before": next_before,
                    "summary": {
                        "attempts": int(s_attempts or 0),
                        "requests": int(s_requests or 0),
                        "errors": int(s_errors or 0),
                        "input_tokens": int(s_inp) if s_inp is not None else None,
                        "output_tokens": int(s_out) if s_out is not None else None,
                        "usage_known": int(s_known or 0),
                        "average_ms": int(s_avg) if s_avg is not None else None,
                    },
                    "applications": [a for a in apps if a],
                    "providers": [p for p in provs if p],
                    "coverage": "Persisted in PostgreSQL interaction store with full prompt and response payloads.",
                }
        return {
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
            "coverage": "Interaction store is not configured with PostgreSQL.",
        }

    def export_day(self, day, destination):
        """Consistent private SQLite snapshot. Never overwrite an existing archive."""
        checked_day(day)
        destination = Path(destination).absolute()
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if destination.parent.stat().st_mode & 0o077:
            raise OSError("Export directory must be private")
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        target = sqlite3.connect(destination)
        try:
            with self.connect(day) as source, target:
                if source is None:
                    raise ValueError("No archive for this day")
                if self.dsn:
                    source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                else:
                    source.execute("BEGIN")
                target.execute("CREATE TABLE interactions(day TEXT,id TEXT,document TEXT,PRIMARY KEY(day,id))")
                target.execute(
                    "CREATE TABLE operational_events(day TEXT,sequence INTEGER,event TEXT,PRIMARY KEY(day,sequence))"
                )
                for table, columns in (
                    ("interactions", "day,id,document"),
                    ("operational_events", "day,sequence,event"),
                ):
                    cursor = self.sql(source, f"SELECT {columns} FROM {table} WHERE day=?", (day,))
                    while rows := cursor.fetchmany(500):
                        target.executemany(
                            f"INSERT INTO {table} VALUES(?,?,?)", [(str(row[0]), *row[1:]) for row in rows]
                        )
        except BaseException:
            target.close()
            destination.unlink(missing_ok=True)
            raise
        finally:
            target.close()
