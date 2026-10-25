"""Explicit, bounded PostgreSQL archive index maintenance.

Run ``python -m subllm.usage_indexes plan`` to observe the native database.
``apply --expected-plan-sha256 SHA`` applies at most four missing leaf indexes;
observe a new plan before the next batch. A digest binds content, not authority.
The native DSN resolver handles authentication; receipts contain no credentials
or interaction payloads. Historical index creation never runs on provider writes.

For a known interrupted build, explicit recover-plan/recover also require the
exact managed index name and observed OID. Recovery rebuilds one nonunique
invalid index concurrently and preserves its logical definition and all rows.
It is never invoked by ordinary apply and does not clean unknown artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from contextlib import contextmanager
from datetime import datetime

from .errors import InvalidPolicyError

LOCK = 861941
MAX_PARTITIONS = 4
INDEX_TIMEOUT_MS = 30000
BATCH_SECONDS = 45
LOCK_TIMEOUT_MS = 5000
KEYS = ("document::jsonb->>'caller'::text", "document::jsonb->>'kind'::text",
        "document::jsonb->>'started_at'::text", "id")


def _fail(message: str):
    raise InvalidPolicyError("usage indexes: " + message)


def _leaf(name: str):
    if not isinstance(name, str) or not re.fullmatch(r"interactions_\d{8}", name):
        _fail("unsupported archive partition")
    try:
        datetime.strptime(name[-8:], "%Y%m%d")
    except ValueError:
        _fail("invalid partition day")


def index_name(schema: str, table: str) -> str:
    _leaf(table)
    return "subllm_caller_v1_" + hashlib.sha256((schema + "." + table).encode()).hexdigest()[:20]


def create_index(db, schema: str, table: str, *, concurrent: bool):
    from psycopg import sql
    _leaf(table)
    db.execute(sql.SQL("CREATE INDEX {}{} ON {}.{} "
                       "(((document::jsonb->>'caller')),((document::jsonb->>'kind')),"
                       "((document::jsonb->>'started_at')) DESC,id DESC)").format(
        sql.SQL("CONCURRENTLY " if concurrent else ""), sql.Identifier(index_name(schema, table)),
        sql.Identifier(schema), sql.Identifier(table)))


def create_empty_partition_index(db, table: str):
    """Called only in the transaction that just created this empty partition."""
    schema = db.execute("SELECT current_schema()").fetchone()[0]
    oid = db.execute("SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                     "WHERE n.nspname=%s AND c.relname=%s", (schema, table)).fetchone()[0]
    if _indexes(db, oid, index_name(schema, table)) is None:
        create_index(db, schema, table, concurrent=False)



def _key_tokens(value: str) -> tuple[str, ...]:
    # Preserve quoted JSON keys and function-call syntax. Removing every space
    # or parenthesis can mistake 'ca ll er' or document() for the caller column.
    tokens = re.findall(r"'(?:[^']|'')*'|::|->>|[A-Za-z_][A-Za-z_0-9]*|[()]|\S", value)
    while tokens and tokens[0] == '(':
        depth, closing = 0, None
        for position, token in enumerate(tokens):
            depth += (token == '(') - (token == ')')
            if depth == 0:
                closing = position
                break
        if closing != len(tokens) - 1:
            break
        tokens = tokens[1:-1]
    while True:
        position = next((i for i in range(len(tokens) - 2)
                         if tokens[i:i + 3] == ['(', 'document', ')']), None)
        if position is None:
            break
        tokens[position:position + 3] = ['document']
    return tuple(tokens)

def _index_rows(db, oid: int):
    rows = db.execute(
        "SELECT c.relname,i.indisvalid AND i.indisready,i.indisunique,i.indpred IS NULL,"
        "i.indnkeyatts,i.indnatts,i.indoption::text,a.amname,"
        "ARRAY(SELECT pg_get_indexdef(i.indexrelid,n,false) FROM generate_series(1,i.indnkeyatts)n),"
        "i.indcollation::text,i.indclass::text "
        "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid JOIN pg_am a ON a.oid=c.relam "
        "WHERE i.indrelid=%s ORDER BY c.relname", (oid,)).fetchall()
    collation, opclass = db.execute(
        "SELECT t.typcollation,o.oid FROM pg_type t JOIN pg_opclass o ON o.opcintype=t.oid "
        "JOIN pg_am a ON a.oid=o.opcmethod WHERE t.oid='text'::regtype AND o.opcdefault AND a.amname='btree'"
    ).fetchone()
    return rows, collation, opclass


def _definition_matches(row, collation, opclass):
    normalized = tuple(_key_tokens(key) for key in row[8])
    return (not row[2] and row[3] and row[4:6] == (4, 4)
            and row[6] == "0 0 3 3" and row[7] == "btree"
            and normalized == tuple(_key_tokens(key) for key in KEYS)
            and row[9] == " ".join([str(collation)] * 4)
            and row[10] == " ".join([str(opclass)] * 4))


def _indexes(db, oid: int, name: str):
    rows, collation, opclass = _index_rows(db, oid)
    def matches(row):
        return row[1] and _definition_matches(row, collation, opclass)
    for row in rows:
        if row[0] == name and not matches(row):
            _fail("existing named index is invalid or conflicts; preserved")
    return next((row[0] for row in rows if matches(row)), None)


def _archive(db):
    parent = db.execute("SELECT oid,relkind FROM pg_class WHERE oid=to_regclass('public.interactions')").fetchone()
    if parent is None or parent[1] != "p":
        _fail("expected public partitioned archive")
    columns = db.execute("SELECT attname,format_type(atttypid,atttypmod) FROM pg_attribute "
                         "WHERE attrelid=%s AND attnum>0 AND NOT attisdropped ORDER BY attnum",
                         (parent[0],)).fetchall()
    if columns != [("day", "date"), ("id", "text"), ("document", "text")]:
        _fail("archive shape differs")
    rows = db.execute("SELECT c.oid,n.nspname,c.relname,c.relkind FROM pg_inherits i "
                      "JOIN pg_class c ON c.oid=i.inhrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                      "WHERE i.inhparent=%s ORDER BY c.relname LIMIT 129", (parent[0],)).fetchall()
    if len(rows) > 128:
        _fail("partition inventory exceeds bounded plan")
    for _, namespace, table, kind in rows:
        if namespace != "public" or kind != "r":
            _fail("unsupported partition layout")
        _leaf(table)
    return parent[0], rows


def _database(db):
    oid = db.execute("SELECT oid FROM pg_database WHERE datname=current_database()").fetchone()[0]
    return {"host": db.info.host, "port": db.info.port, "name": db.info.dbname,
            "user": db.info.user, "oid": oid}


def _seal(value):
    return {**value, "sha256": hashlib.sha256(json.dumps(value, sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()}


def plan(db) -> dict:
    """Query metadata only; never parse an interaction document or create DDL."""
    parent, rows = _archive(db)
    leaves = []
    for oid, namespace, table, kind in rows:
        if namespace != "public" or kind != "r":
            _fail("unsupported partition layout")
        name = index_name(namespace, table)
        ready = _indexes(db, oid, name)
        leaves.append({"oid": oid, "schema": namespace, "table": table, "index": name,
                       "ready_index": ready})
    value = {"schema": "subllm.usage-index-plan/v1", "authority": "none", "parent_oid": parent,
             "database": _database(db),
             "index_spec": {"version": 1, "keys": list(KEYS), "order": ["asc", "asc", "desc", "desc"],
                            "unique": False, "predicate": None, "mode": "concurrent-leaf",
                            "statement_timeout_ms": INDEX_TIMEOUT_MS, "lock_timeout_ms": LOCK_TIMEOUT_MS,
                            "batch_budget_seconds": BATCH_SECONDS, "maximum_partitions": MAX_PARTITIONS},
             "leaves": leaves}
    return _seal(value)


@contextmanager
def _maintenance(db):
    if not db.autocommit:
        _fail("maintenance requires autocommit")
    settings = {key: db.execute("SELECT current_setting(%s)", (key,)).fetchone()[0]
                for key in ("statement_timeout", "lock_timeout",
                            "max_parallel_maintenance_workers", "maintenance_work_mem")}
    locked = False
    try:
        for key, value in (("statement_timeout", "5000"), ("lock_timeout", str(LOCK_TIMEOUT_MS)),
                           ("max_parallel_maintenance_workers", "0"), ("maintenance_work_mem", "32MB")):
            db.execute("SELECT set_config(%s,%s,false)", (key, value))
        locked = db.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()[0]
        if not locked:
            _fail("another index maintenance owns the archive")
        yield
    finally:
        if locked:
            db.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
        for key, value in settings.items():
            db.execute("SELECT set_config(%s,%s,false)", (key, value))


def apply(db, expected_sha256: str, *, maximum: int = 4) -> dict:
    """One explicit batch. Failure preserves partial indexes for owner inspection."""
    import psycopg
    if (not db.autocommit or type(maximum) is not int or not 1 <= maximum <= MAX_PARTITIONS
            or not isinstance(expected_sha256, str) or not re.fullmatch("[a-f0-9]{64}", expected_sha256)):
        _fail("apply requires autocommit, a plan digest and a batch from 1 to 4")
    with _maintenance(db):
        observed = plan(db)
        if observed["sha256"] != expected_sha256:
            _fail("plan is stale; observe again")
        missing = [leaf for leaf in observed["leaves"] if leaf["ready_index"] is None]
        result = {"schema": "subllm.usage-index-receipt/v1", "authority": "none", "status": "completed",
                  "plan_sha256": expected_sha256, "created": [], "remaining": len(missing)}
        deadline = time.monotonic() + BATCH_SECONDS
        for leaf in missing[:maximum]:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                result["status"] = "batch-budget-exhausted"
                break
            observed_oid = db.execute("SELECT to_regclass(%s)::oid",
                                      (leaf["schema"] + "." + leaf["table"],)).fetchone()[0]
            if observed_oid != leaf["oid"]:
                _fail("partition identity changed")
            db.execute("SELECT set_config('statement_timeout',%s,false)", (str(min(INDEX_TIMEOUT_MS, remaining_ms)),))
            try:
                create_index(db, leaf["schema"], leaf["table"], concurrent=True)
                if _indexes(db, leaf["oid"], leaf["index"]) != leaf["index"]:
                    _fail("created index did not pass readback")
            except psycopg.Error as exc:
                result.update(status="interrupted", failed_index=leaf["index"], sqlstate=exc.sqlstate)
                break
            result["created"].append(leaf["index"])
            result["remaining"] -= 1
        return result



def _owned_index_state(db, name):
    if not isinstance(name, str) or not re.fullmatch(r"subllm_caller_v1_[a-f0-9]{20}", name):
        _fail("recovery requires an exact managed index name")
    parent, leaves = _archive(db)
    found = db.execute("SELECT i.indexrelid,i.indrelid,i.indisvalid,i.indisready,"
                       "EXISTS(SELECT 1 FROM pg_constraint k WHERE k.conindid=i.indexrelid),c.relowner "
                       "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                       "WHERE i.indexrelid=to_regclass(%s)", ('public.' + name,)).fetchone()
    if found is None or found[4]:
        _fail("missing or constraint-owned index; preserved")
    leaf = next((row for row in leaves if row[0] == found[1]), None)
    if leaf is None or index_name(leaf[1], leaf[2]) != name:
        _fail("index does not belong to the managed archive leaf")
    rows, collation, opclass = _index_rows(db, leaf[0])
    row = next((row for row in rows if row[0] == name), None)
    if row is None or not _definition_matches(row, collation, opclass):
        _fail("index definition conflicts; preserved")
    if db.execute("SELECT count(*) FROM pg_stat_progress_create_index WHERE relid=%s", (leaf[0],)).fetchone()[0]:
        _fail("an index build is still active on this leaf; preserved")
    prefix = name + '_cc'
    if db.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                  "WHERE n.nspname='public' AND left(c.relname,length(%s))=%s", (prefix, prefix)).fetchone()[0]:
        _fail("concurrent-rebuild artifacts require owner inspection; preserved")
    return {"parent_oid": parent, "table_oid": leaf[0], "namespace": leaf[1], "table": leaf[2],
            "index": name, "index_oid": found[0], "owner_oid": found[5], "valid": found[2], "ready": found[3]}


def recovery_plan(db, name: str, expected_index_oid: int) -> dict:
    if type(expected_index_oid) is not int or not 1 <= expected_index_oid <= 2**32 - 1:
        _fail("an exact positive index OID is required")
    state = _owned_index_state(db, name)
    if state['index_oid'] != expected_index_oid or state['valid']:
        _fail("index OID changed or index is already valid; preserved")
    return _seal({"schema": "subllm.usage-index-recovery-plan/v1", "authority": "none",
                  "database": _database(db), "target": state,
                  "keys": list(KEYS), "operation": "REINDEX INDEX CONCURRENTLY",
                  "statement_timeout_ms": INDEX_TIMEOUT_MS, "lock_timeout_ms": LOCK_TIMEOUT_MS})


def _reindex(db, namespace, name):
    from psycopg import sql
    db.execute(sql.SQL("REINDEX INDEX CONCURRENTLY {}").format(sql.Identifier(namespace, name)))


def recover(db, name: str, expected_index_oid: int, expected_sha256: str) -> dict:
    """One explicit physical rebuild; never called automatically by apply."""
    import psycopg
    if not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256):
        _fail("recovery requires a pinned plan")
    with _maintenance(db):
        observed = recovery_plan(db, name, expected_index_oid)
        if observed['sha256'] != expected_sha256:
            _fail("recovery plan is stale; observe again")
        target = observed['target']
        result = {"schema": "subllm.usage-index-recovery-receipt/v1", "authority": "none",
                  "plan_sha256": expected_sha256, "index": name, "previous_oid": expected_index_oid}
        db.execute("SELECT set_config('statement_timeout',%s,false)", (str(INDEX_TIMEOUT_MS),))
        try:
            _reindex(db, target['namespace'], name)
        except psycopg.Error as exc:
            return {**result, "status": "interrupted", "sqlstate": exc.sqlstate}
        after = _owned_index_state(db, name)
        if (not after['valid'] or not after['ready'] or after['table_oid'] != target['table_oid']
                or after['owner_oid'] != target['owner_oid']):
            _fail("recovery readback failed; inspect preserved objects")
        return {**result, "status": "completed", "observed_oid": after['index_oid'], "valid": True}

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan")
    edit = commands.add_parser("apply")
    edit.add_argument("--expected-plan-sha256", required=True)
    edit.add_argument("--max-partitions", type=int, default=4, choices=range(1, 5))
    for command in ('recover-plan', 'recover'):
        recovery = commands.add_parser(command)
        recovery.add_argument('--index', required=True)
        recovery.add_argument('--index-oid', type=int, required=True)
        if command == 'recover':
            recovery.add_argument('--expected-plan-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        import psycopg

        from .interaction_store import default_postgres_dsn
        dsn = default_postgres_dsn()
        if not dsn:
            _fail("native PostgreSQL is unavailable")
        # Index DDL is bounded separately; usage queries retain their 5000ms deadline.
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5,
                             options="-c statement_timeout=5000 -c lock_timeout=5000") as db:
            if args.command == "plan":
                db.read_only = True
                result = plan(db)
            elif args.command == 'recover-plan':
                db.read_only = True
                result = recovery_plan(db, args.index, args.index_oid)
            elif args.command == 'recover':
                result = recover(db, args.index, args.index_oid, args.expected_plan_sha256)
            else:
                result = apply(db, args.expected_plan_sha256, maximum=args.max_partitions)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get("status", "completed") == "completed" else 2
    except InvalidPolicyError as exc:
        print(json.dumps({"schema": "subllm.usage-index-result/v1", "status": "invalid",
                          "reason": str(exc), "authority": "none"}))
        return 2
    except (ImportError, OSError, ValueError):
        print(json.dumps({"schema": "subllm.usage-index-result/v1", "status": "failed", "authority": "none"}))
        return 2
    except Exception:
        # Driver messages can contain connection/row values. Never emit them.
        print(json.dumps({"schema": "subllm.usage-index-result/v1", "status": "database-error", "authority": "none"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
