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

from .interaction_events import canonical, make_event

DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
IDENT = re.compile(r"[a-f0-9]{32}\Z")


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

    def query(self, day, record_id=None, *, kind=None, caller=None, status=None, limit=100, before=None):
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
            return [{k: v for k, v in json.loads(row[0]).items() if k not in ("request", "response")} for row in rows]

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
