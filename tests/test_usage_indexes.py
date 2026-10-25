"""Unit regressions plus an explicit real-PostgreSQL verification entrypoint.

After starting a disposable PostgreSQL database named usage_test_<unique>, set
SUBLLM_TEST_POSTGRES_DSN and run ``python tests/test_usage_indexes.py``. This
entrypoint refuses the shared archive, seeds only synthetic fixture documents,
and checks actual concurrent DDL, query plans and payload/search parity. The
normal pytest suite runs the unit boundaries without requiring Docker.
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from subllm import usage_indexes as indexes
from subllm.errors import InvalidPolicyError


class DatabaseError(Exception):
    def __init__(self, message, sqlstate):
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.fixture(autouse=True)
def _optional_postgres_driver(monkeypatch):
    # Unit cases model driver failures without requiring the optional gateway
    # package. The explicit PostgreSQL entrypoint below uses the real driver.
    monkeypatch.setitem(sys.modules, 'psycopg', SimpleNamespace(Error=DatabaseError))

class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class Connection:
    autocommit = True

    def __init__(self, *, locked=True):
        self.calls = []
        self.locked = locked

    def execute(self, query, values=()):
        self.calls.append((query, values))
        if 'current_setting' in query:
            return Result(('5000',))
        if 'pg_try_advisory_lock' in query:
            return Result((self.locked,))
        return Result((12,))


def catalog():
    return {'sha256': 'a' * 64, 'leaves': [
        {'oid': 12, 'schema': 'public', 'table': f'interactions_2026010{n}',
         'index': indexes.index_name('public', f'interactions_2026010{n}'), 'ready_index': None}
        for n in range(1, 7)]}


@pytest.mark.parametrize('value', ['interactions_bad', 'interactions_20260230',
                                  'other_20260101', 'interactions_20260101;'])
def test_partition_identifiers_are_native_days(value):
    with pytest.raises(InvalidPolicyError):
        indexes.index_name('public', value)


@pytest.mark.parametrize('limit', [True, 0, 5, 1.0])
def test_invalid_batch_cannot_acquire_a_lock(limit):
    db = Connection()
    with pytest.raises(InvalidPolicyError):
        indexes.apply(db, 'a' * 64, maximum=limit)
    assert not db.calls


def test_stale_plan_and_other_owner_prevent_ddl(monkeypatch):
    monkeypatch.setattr(indexes, 'plan', lambda db: catalog())
    monkeypatch.setattr(indexes, 'create_index', lambda *a, **kw: pytest.fail('DDL must not run'))
    for db, pin in [(Connection(), 'b' * 64), (Connection(locked=False), 'a' * 64)]:
        with pytest.raises(InvalidPolicyError):
            indexes.apply(db, pin)
    assert any('pg_advisory_unlock' in q for q, _ in db.calls) is False


def test_apply_caps_work_and_restores_connection_settings(monkeypatch):
    expected = catalog()
    monkeypatch.setattr(indexes, 'plan', lambda db: expected)
    created = []
    monkeypatch.setattr(indexes, 'create_index', lambda db, schema, table, **kw: created.append((table, kw)))
    monkeypatch.setattr(indexes, '_indexes', lambda db, oid, name: name)
    db = Connection()
    receipt = indexes.apply(db, expected['sha256'])
    assert len(created) == 4 and all(kw == {'concurrent': True} for _, kw in created)
    assert receipt['remaining'] == 2 and receipt['status'] == 'completed'
    restored = [v for q, v in db.calls if q == 'SELECT set_config(%s,%s,false)' and v[1] == '5000']
    assert {v[0] for v in restored} >= {'statement_timeout', 'lock_timeout', 'maintenance_work_mem'}
    assert any('pg_advisory_unlock' in q for q, _ in db.calls)


def test_interrupted_batch_reports_only_public_context(monkeypatch):
    expected = catalog()
    monkeypatch.setattr(indexes, 'plan', lambda db: expected)

    def interrupted(*args, **kwargs):
        raise DatabaseError('private row or credential text must not escape', '55P03')
    monkeypatch.setattr(indexes, 'create_index', interrupted)
    db = Connection()
    receipt = indexes.apply(db, expected['sha256'])
    assert receipt['status'] == 'interrupted' and receipt['sqlstate'] == '55P03'
    assert receipt['created'] == [] and receipt['remaining'] == 6
    assert 'private' not in json.dumps(receipt)
    assert any('pg_advisory_unlock' in q for q, _ in db.calls)



def test_partial_batch_keeps_earlier_successes_and_stops(monkeypatch):
    expected, calls = catalog(), []
    monkeypatch.setattr(indexes, 'plan', lambda db: expected)
    monkeypatch.setattr(indexes, '_indexes', lambda db, oid, name: name)

    def build(db, schema, table, **kw):
        calls.append(table)
        if len(calls) == 2:
            raise DatabaseError('private driver detail', '57014')
    monkeypatch.setattr(indexes, 'create_index', build)
    result = indexes.apply(Connection(), expected['sha256'])
    assert len(calls) == 2 and len(result['created']) == 1
    assert result['remaining'] == 5 and result['status'] == 'interrupted'


def test_batch_time_budget_does_not_start_another_index(monkeypatch):
    monkeypatch.setattr(indexes, 'plan', lambda db: catalog())
    times = iter([0, indexes.BATCH_SECONDS + 1])
    monkeypatch.setattr(indexes.time, 'monotonic', lambda: next(times))
    monkeypatch.setattr(indexes, 'create_index', lambda *a, **kw: pytest.fail('budget exhausted'))
    result = indexes.apply(Connection(), 'a' * 64)
    assert result['status'] == 'batch-budget-exhausted' and result['created'] == []


def test_batch_never_shortens_the_next_statement_budget(monkeypatch):
    monkeypatch.setattr(indexes, 'plan', lambda db: catalog())
    monkeypatch.setattr(indexes, '_indexes', lambda db, oid, name: name)
    times = iter([0, 0, 20])
    monkeypatch.setattr(indexes.time, 'monotonic', lambda: next(times))
    created = []
    monkeypatch.setattr(indexes, 'create_index', lambda *a, **kw: created.append(kw))
    result = indexes.apply(Connection(), 'a' * 64)
    assert len(created) == 1 and result['remaining'] == 5
    assert result['status'] == 'batch-budget-exhausted'


@pytest.mark.parametrize('timeout', [True, 0, 999, 120001, 30000.0, '120000'])
def test_unbounded_or_ambiguous_ddl_budget_is_rejected_before_lock(timeout):
    db = Connection()
    with pytest.raises(InvalidPolicyError):
        indexes.apply(db, 'a' * 64, statement_timeout_ms=timeout)
    assert not db.calls


def test_extended_ddl_budget_is_pinned_and_bounded(monkeypatch):
    observed = []
    def planned(db, *, statement_timeout_ms):
        observed.append(statement_timeout_ms)
        return catalog()
    monkeypatch.setattr(indexes, 'plan', planned)
    monkeypatch.setattr(indexes, '_indexes', lambda db, oid, name: name)
    monkeypatch.setattr(indexes, 'create_index', lambda *a, **kw: None)
    db = Connection()
    assert indexes.apply(db, 'a' * 64, maximum=1, statement_timeout_ms=120000)['remaining'] == 5
    assert observed == [120000]
    assert ("SELECT set_config('statement_timeout',%s,false)", ('120000',)) in db.calls
    assert indexes._batch_seconds(120000) == 135


@pytest.mark.parametrize('oid,artifacts', [(True, [2]), (0, [2]), (1, []), (1, [2, 2]),
                                        (1, [True]), (1, [2**32]), (1, list(range(1, 6)))])
def test_replacement_requires_explicit_bounded_oid_set(oid, artifacts):
    db = Connection()
    with pytest.raises(InvalidPolicyError):
        indexes.replacement_plan(db, 'unused', oid, artifacts)
    assert not db.calls


def test_replacement_plan_binds_original_artifacts_and_budget(monkeypatch):
    target = {'index': indexes.index_name('public', 'interactions_20260101'), 'index_oid': 12}
    artifacts = [{'oid': 13}]
    monkeypatch.setattr(indexes, '_replacement_context', lambda *a: (target, artifacts))
    monkeypatch.setattr(indexes, '_database', lambda db: {'oid': 20})
    class Empty(Connection):
        def execute(self, *a):
            return Result((None,))
    first = indexes.replacement_plan(Empty(), target['index'], 12, [13])
    extended = indexes.replacement_plan(Empty(), target['index'], 12, [13], statement_timeout_ms=120000)
    assert first['sha256'] != extended['sha256']
    assert extended['preserved_objects_modified'] is False
    with pytest.raises(InvalidPolicyError):
        indexes.replacement_plan(Empty(), target['index'], 12, [14])
    with pytest.raises(InvalidPolicyError):
        indexes.replacement_plan(Empty(), target['index'], 11, [13])


def test_stale_replacement_never_creates_an_index(monkeypatch):
    monkeypatch.setattr(indexes, 'replacement_plan', lambda *a, **kw: {'sha256': 'a' * 64})
    monkeypatch.setattr(indexes, 'create_index', lambda *a, **kw: pytest.fail('stale plan'))
    with pytest.raises(InvalidPolicyError):
        indexes.replace(Connection(), 'index', 12, [13], 'b' * 64)


def test_interrupted_replacement_reports_preserved_objects_without_driver_text(monkeypatch):
    plan = {'sha256': 'a' * 64, 'target': {'namespace': 'public', 'table': 'interactions_20260101'},
            'replacement': 'new', 'statement_timeout_ms': 120000}
    monkeypatch.setattr(indexes, 'replacement_plan', lambda *a, **kw: plan)
    def fail(*a, **kw):
        raise DatabaseError('private credential detail', '57014')
    monkeypatch.setattr(indexes, 'create_index', fail)
    result = indexes.replace(Connection(), 'old', 12, [13], 'a' * 64, statement_timeout_ms=120000)
    assert result['status'] == 'interrupted' and result['preserved_artifact_oids'] == [13]
    assert result['preserved_objects_modified'] is False and 'private' not in json.dumps(result)


@pytest.mark.parametrize('change', ['healthy-original', 'owner', 'unknown-name', 'healthy-artifact',
                                  'constraint', 'foreign-leaf', 'changed-definition'])
def test_replacement_preserves_unowned_or_conflicting_artifacts(monkeypatch, change):
    name = indexes.index_name('public', 'interactions_20260101')
    target = {'index': name, 'index_oid': 12, 'table_oid': 10, 'owner_oid': 20,
              'valid': change == 'healthy-original'}
    monkeypatch.setattr(indexes, '_owned_index_state', lambda *a, **kw: target)
    artifact = [13, name + '_ccnew', 20, 10, False, False, False]
    if change == 'unknown-name':
        artifact[1] = name + '_ccold'
    for tag, position, value in [('owner', 2, 21), ('healthy-artifact', 4, True),
                                 ('constraint', 6, True), ('foreign-leaf', 3, 11)]:
        if change == tag:
            artifact[position] = value
    monkeypatch.setattr(indexes, '_index_rows', lambda *a: ([(artifact[1],)], None, None))
    monkeypatch.setattr(indexes, '_definition_matches', lambda *a: change != 'changed-definition')
    class Catalog:
        def execute(self, query, args=()):
            if query.startswith('SELECT relowner'):
                return Result((20,))
            return SimpleNamespace(fetchall=lambda: [tuple(artifact)])
    with pytest.raises(InvalidPolicyError):
        indexes._replacement_context(Catalog(), name)


@pytest.mark.parametrize('exists', [False, True])
def test_native_writer_preserves_first_use_without_recurring_index_ddl(monkeypatch, tmp_path, exists):
    from subllm.interaction_store import InteractionStore
    calls = []
    class Native:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def execute(self, query, values=()):
            calls.append(query)
            if 'pg_class i JOIN pg_class t' in query:
                return Result((1,) if exists else None)
            return Result(('existing-partition',))
    monkeypatch.setattr(sys.modules['psycopg'], 'connect', lambda *a, **kw: Native(), raising=False)
    with InteractionStore(tmp_path, postgres_dsn='fixture').connect('2026-01-01', True):
        pass
    assert calls[0] == 'SELECT pg_advisory_xact_lock(861940)'
    ddl = [q for q in calls if q.startswith('CREATE INDEX IF NOT EXISTS interaction_started')]
    assert len(ddl) == (0 if exists else 1)


def test_sqlite_writers_share_a_gate_across_store_instances(monkeypatch, tmp_path):
    from subllm.interaction_store import InteractionStore
    monkeypatch.setattr('subllm.interaction_store.utc_now', lambda: '2026-01-01T00:00:00.000Z')
    def write(n):
        return InteractionStore(tmp_path / 'private').begin(kind='llm', caller='fixture',
                                                           target='fixture', request={'number': n})
    with ThreadPoolExecutor(8) as pool:
        records = list(pool.map(write, range(24)))
    store = InteractionStore(tmp_path / 'private')
    assert len(store.query('2026-01-01')) == len({r['id'] for r in records}) == 24
    with store.connect('2026-01-01') as db:
        summary = db.execute('SELECT count(*),min(sequence),max(sequence) FROM operational_events').fetchone()
        assert summary == (24, 1, 24)


def test_sqlite_local_queue_shares_the_existing_busy_budget(monkeypatch, tmp_path):
    from subllm import interaction_store
    path = tmp_path / 'fixture.sqlite3'
    path.touch(mode=0o600)
    clock = iter([0, 3])
    monkeypatch.setattr(interaction_store.time, 'monotonic', lambda: next(clock))
    with interaction_store._sqlite_write_slot(path, True) as remaining:
        assert remaining == 2


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='POSIX fork required')
def test_sqlite_child_does_not_inherit_a_parent_thread_gate(monkeypatch, tmp_path):
    from subllm import interaction_store
    monkeypatch.setattr(interaction_store, 'utc_now', lambda: '2026-01-01T00:00:00.000Z')
    directory = tmp_path / 'private'
    directory.mkdir(mode=0o700)
    path = directory / '2026-01-01.sqlite3'
    path.touch(mode=0o600)
    with interaction_store._sqlite_write_slot(path, True):
        pid = os.fork()
        if pid == 0:
            try:
                interaction_store.InteractionStore(directory).begin(kind='llm', caller='fixture',
                                                                    target='fixture', request={})
            except BaseException:
                os._exit(1)
            os._exit(0)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 0


@pytest.mark.parametrize('change', ['oid', 'healthy', 'owner', 'constraint', 'leaf', 'definition', 'artifact'])
def test_failed_replacement_recovery_is_exact_and_preserves_conflicts(monkeypatch, change):
    target = {'index': indexes.index_name('public', 'interactions_20260101'), 'table_oid': 10, 'owner_oid': 20}
    monkeypatch.setattr(indexes, '_replacement_inputs', lambda *a: (target, [{'oid': 12}]))
    name = indexes._replacement_name(target, [{'oid': 12}])
    found = [13, 10, False, True, 20, False]
    for tag, position, value in [('healthy', 2, True), ('owner', 4, 21),
                                 ('constraint', 5, True), ('leaf', 1, 11)]:
        if change == tag:
            found[position] = value
    monkeypatch.setattr(indexes, '_index_rows', lambda *a: ([(name,)], None, None))
    monkeypatch.setattr(indexes, '_definition_matches', lambda *a: change != 'definition')
    class Metadata:
        def execute(self, query, args=()):
            return Result((int(change == 'artifact'),) if 'SELECT count(*)' in query else tuple(found))
    with pytest.raises(InvalidPolicyError):
        indexes.replacement_recovery_plan(Metadata(), target['index'], 11, [12], 14 if change == 'oid' else 13)


def test_failed_replacement_recovery_never_retries_or_exports_deadlock_text(monkeypatch):
    selected = {'sha256': 'a' * 64, 'target': {'namespace': 'public'},
                'replacement': 'exact-replacement', 'statement_timeout_ms': 120000}
    monkeypatch.setattr(indexes, 'replacement_recovery_plan', lambda *a, **kw: selected)
    rebuilt = []
    def fail(*a):
        rebuilt.append(a)
        raise DatabaseError('private transaction text', '40P01')
    monkeypatch.setattr(indexes, '_reindex', fail)
    with pytest.raises(InvalidPolicyError):
        indexes.recover_replacement(Connection(), 'original', 11, [12], 13, 'b' * 64)
    assert not rebuilt
    receipt = indexes.recover_replacement(Connection(), 'original', 11, [12], 13, 'a' * 64)
    assert len(rebuilt) == 1 and receipt['status'] == 'interrupted'
    assert receipt['sqlstate'] == '40P01' and receipt['preserved_index_oid'] == 11
    assert 'private' not in json.dumps(receipt)


@pytest.mark.parametrize('field,value', [(1, False), (2, True), (3, False), (5, 5),
                                        (6, '0 0 0 0'), (9, '0 0 0 0'), (10, '0 0 0 0'),
                                        (8, ["document::jsonb->>'ca ll er'::text",
                                             "document::jsonb->>'kind'::text",
                                             "document::jsonb->>'started_at'::text", 'id']),
                                        (8, ["document::jsonb->>'call(er)'::text",
                                             "document::jsonb->>'kind'::text",
                                             "document::jsonb->>'started_at'::text", 'id']),
                                        (8, ["document()::jsonb->>'caller'::text",
                                             "document::jsonb->>'kind'::text",
                                             "document::jsonb->>'started_at'::text", 'id'])])
def test_conflicting_named_index_is_preserved(field, value):
    row = ['owned_index', True, False, True, 4, 4, '0 0 3 3', 'btree',
           ["(document::jsonb ->> 'caller'::text)", "(document::jsonb ->> 'kind'::text)",
            "(document::jsonb ->> 'started_at'::text)", 'id'], '100 100 100 100', '3126 3126 3126 3126']
    row[field] = value

    class Metadata:
        def execute(self, query, args=()):
            if 'FROM pg_index' in query:
                class Rows:
                    def fetchall(self):
                        return [tuple(row)]
                return Rows()
            return Result((100, 3126))
    with pytest.raises(InvalidPolicyError):
        indexes._indexes(Metadata(), 12, 'owned_index')


@pytest.mark.parametrize('oid', [True, 0, -1, 2**32])
def test_recovery_requires_exact_positive_oid(monkeypatch, oid):
    monkeypatch.setattr(indexes, '_owned_index_state', lambda *a: pytest.fail('metadata must not be read'))
    with pytest.raises(InvalidPolicyError):
        indexes.recovery_plan(Connection(), 'unused', oid)


@pytest.mark.parametrize('state', [{'index_oid': 13, 'valid': False}, {'index_oid': 12, 'valid': True}])
def test_recovery_plan_rejects_replaced_or_healthy_index(monkeypatch, state):
    monkeypatch.setattr(indexes, '_owned_index_state', lambda *a: state)
    with pytest.raises(InvalidPolicyError):
        indexes.recovery_plan(Connection(), 'unused', 12)


def recovery_document():
    return {'sha256': 'a' * 64, 'target': {'namespace': 'public', 'table_oid': 22, 'owner_oid': 7}}


def test_recovery_is_explicit_and_stale_plan_does_not_rebuild(monkeypatch):
    monkeypatch.setattr(indexes, 'recovery_plan', lambda *a: recovery_document())
    monkeypatch.setattr(indexes, '_reindex', lambda *a: pytest.fail('stale plan must not rebuild'))
    with pytest.raises(InvalidPolicyError):
        indexes.recover(Connection(), 'managed', 12, 'b' * 64)


def test_recovery_rebuilds_once_and_reads_back_logical_identity(monkeypatch):
    monkeypatch.setattr(indexes, 'recovery_plan', lambda *a: recovery_document())
    calls = []
    monkeypatch.setattr(indexes, '_reindex', lambda *a: calls.append(a[1:]))
    monkeypatch.setattr(indexes, '_owned_index_state', lambda *a:
                        {'valid': True, 'ready': True, 'table_oid': 22, 'index_oid': 99, 'owner_oid': 7})
    result = indexes.recover(Connection(), 'managed', 12, 'a' * 64)
    assert calls == [('public', 'managed')]
    assert result['status'] == 'completed' and result['previous_oid'] == 12 and result['observed_oid'] == 99


def test_interrupted_recovery_preserves_objects_and_driver_privacy(monkeypatch):
    monkeypatch.setattr(indexes, 'recovery_plan', lambda *a: recovery_document())
    def interrupted(*a):
        raise DatabaseError('private row or credential detail', '55P03')
    monkeypatch.setattr(indexes, '_reindex', interrupted)
    result = indexes.recover(Connection(), 'managed', 12, 'a' * 64)
    assert result['status'] == 'interrupted' and result['sqlstate'] == '55P03'
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('found', [None, (12, 22, False, True, True), (12, 99, False, True, False)])
def test_recovery_preserves_missing_constraint_or_foreign_indexes(monkeypatch, found):
    monkeypatch.setattr(indexes, '_archive', lambda db: (1, [(22, 'public', 'interactions_20260101', 'r')]))
    class Metadata:
        def execute(self, *args):
            return Result(found)
    with pytest.raises(InvalidPolicyError):
        indexes._owned_index_state(Metadata(), indexes.index_name('public', 'interactions_20260101'))


def test_recovery_rejects_a_still_active_build(monkeypatch):
    table = 'interactions_20260101'
    name = indexes.index_name('public', table)
    monkeypatch.setattr(indexes, '_archive', lambda db: (1, [(22, 'public', table, 'r')]))
    monkeypatch.setattr(indexes, '_index_rows', lambda *a: ([(name,)], 100, 3126))
    monkeypatch.setattr(indexes, '_definition_matches', lambda *a: True)
    class Metadata:
        def execute(self, query, *args):
            return Result((1,)) if 'pg_stat_progress_create_index' in query else Result((12, 22, False, True, False, 7))
    with pytest.raises(InvalidPolicyError):
        indexes._owned_index_state(Metadata(), name)

def test_cli_unavailable_database_has_a_secret_free_result(monkeypatch, capsys):
    from subllm import interaction_store
    monkeypatch.setattr(interaction_store, 'default_postgres_dsn', lambda: None)
    assert indexes.main(['plan']) == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'invalid'


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from _nodes(value)


def verify_postgres():
    import psycopg

    from subllm.interaction_store import InteractionStore
    dsn = os.environ['SUBLLM_TEST_POSTGRES_DSN']
    with psycopg.connect(dsn, autocommit=True) as db:
        assert db.info.dbname.startswith('usage_test_') and db.info.host == '127.0.0.1', 'owned fixture required'
        assert db.execute("SELECT to_regclass('public.interactions')").fetchone()[0] is None, 'fresh fixture required'
    store = InteractionStore(Path('/unused-fixture-archive'), postgres_dsn=dsn)
    with store.connect('2026-01-01', True):
        pass
    with psycopg.connect(dsn, autocommit=True) as db:
        assert indexes.plan(db)['leaves'][0]['ready_index'] is not None
        for n in range(2, 5):
            db.execute(f"CREATE TABLE interactions_2026010{n} PARTITION OF interactions "
                       f"FOR VALUES FROM ('2026-01-0{n}') TO ('2026-01-0{n + 1}')")
            db.execute("INSERT INTO interactions(day,id,document) SELECT %s::date,md5(%s||i::text),"
                       "json_build_object('id',md5(%s||i::text),'day',%s::text,'kind','llm_attempt',"
                       "'caller',CASE WHEN i%%250=0 THEN 'index-target' ELSE 'index-other' END,"
                       "'started_at',%s||'T00:'||lpad((i/60)::text,2,'0')||':'||lpad((i%%60)::text,2,'0')||'Z',"
                       "'status','success','correlation_id',md5(%s||i::text),'duration_ms',12,"
                       "'target','test/model','metadata',json_build_object('provider','test','input_tokens',7,'output_tokens',5),"
                       "'request',json_build_object('prompt',repeat(md5(i::text),2048)),"
                       "'response',json_build_object('content','needle-fixture'))::text FROM generate_series(1,500)i",
                       (f'2026-01-0{n}', f'd{n}', f'd{n}', f'2026-01-0{n}', f'2026-01-0{n}', f'd{n}'))
        db.execute('ANALYZE interactions')
        original = indexes.plan(db)
        assert sum(leaf['ready_index'] is None for leaf in original['leaves']) == 3
    # A normal write on an existing historical partition must not backfill it.
    with store.connect('2026-01-02', True):
        pass
    with psycopg.connect(dsn, autocommit=True) as db:
        assert indexes.plan(db)['sha256'] == original['sha256']
    start = time.perf_counter()
    before = store.query_attempts(application='index-target', limit=2)
    before_ms = (time.perf_counter() - start) * 1000
    assert before['summary']['attempts'] == 6 and before['summary']['input_tokens'] == 42
    assert len(before['attempts'][0]['request']['prompt']) == 65536

    # Hold an existing writer open while the concurrent index starts; a fresh
    # writer must still commit, unlike a queued ordinary CREATE INDEX lock.
    failures, receipt = [], []
    with psycopg.connect(dsn) as writer:
        writer.execute("INSERT INTO interactions VALUES('2026-01-02','fixture-held','{}')")

        def build():
            try:
                with psycopg.connect(dsn, autocommit=True) as builder:
                    receipt.append(indexes.apply(builder, original['sha256'], maximum=1))
            except BaseException as exc:
                failures.append(type(exc).__name__)
        task = Thread(target=build)
        task.start()
        with psycopg.connect(dsn, autocommit=True) as observer:
            deadline = time.monotonic() + 5
            active = False
            while time.monotonic() < deadline:
                active = observer.execute("SELECT count(*) FROM pg_stat_progress_create_index "
                                          "WHERE datname=current_database()").fetchone()[0] > 0
                if active:
                    break
                time.sleep(.02)
            assert active, 'concurrent build did not reach the database'
        from psycopg.conninfo import make_conninfo
        native_writer = InteractionStore(Path('/unused-native-writer'),
                                         postgres_dsn=make_conninfo(dsn, options='-c statement_timeout=1000'))
        with native_writer.connect('2026-01-02', True) as fresh_writer:
            fresh_writer.execute("INSERT INTO interactions VALUES('2026-01-02','fixture-new-writer','{}')")
        writer.commit()
        task.join(35)
        assert not task.is_alive() and not failures and receipt[0]['status'] == 'completed', failures
    with psycopg.connect(dsn, autocommit=True) as db:
        with pytest.raises(InvalidPolicyError):
            indexes.apply(db, original['sha256'])
        current = indexes.plan(db)
        result = indexes.apply(db, current['sha256'])
        assert result['remaining'] == 0
        ready = indexes.plan(db)
        assert all(leaf['ready_index'] for leaf in ready['leaves'])
        db.execute('ANALYZE interactions')
        plan = db.execute("EXPLAIN (FORMAT JSON) SELECT COUNT(*) FROM interactions "
                          "WHERE document::jsonb->>'kind' IN ('llm','llm_attempt') "
                          "AND document::jsonb->>'caller'='index-target'").fetchone()[0]
        assert sum('caller' in node.get('Index Cond', '') for node in _nodes(plan)) >= 3
    start = time.perf_counter()
    after = store.query_attempts(application='index-target', limit=2)
    after_ms = (time.perf_counter() - start) * 1000
    assert before == after
    second = store.query_attempts(application='index-target', limit=2, before=after['next_before'])
    assert not {a['id'] for a in after['attempts']} & {a['id'] for a in second['attempts']}
    found = store.query_attempts(application='index-target', search='needle-fixture')
    assert found['summary']['attempts'] == 6
    assert store.query_attempts(application='index-target', search='not-found')['summary']['attempts'] == 0
    # Reproduce an actual abandoned concurrent build, then explicitly rebuild
    # only its exact nonunique component-owned OID and logical definition.
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("CREATE TABLE interactions_20260105 PARTITION OF interactions "
                   "FOR VALUES FROM ('2026-01-05') TO ('2026-01-06')")
        db.execute("INSERT INTO interactions SELECT '2026-01-05'::date,id,document "
                   "FROM interactions_20260104")
    with psycopg.connect(dsn) as blocker:
        blocker.execute("INSERT INTO interactions VALUES('2026-01-05','recovery-held','{}')")
        with (
            psycopg.connect(dsn, autocommit=True, options='-c statement_timeout=1000') as builder,
            pytest.raises(psycopg.errors.QueryCanceled),
        ):
            indexes.create_index(builder, 'public', 'interactions_20260105', concurrent=True)
        blocker.commit()
    with psycopg.connect(dsn, autocommit=True) as db:
        name = indexes.index_name('public', 'interactions_20260105')
        oid = db.execute('SELECT to_regclass(%s)::oid', (name,)).fetchone()[0]
        repair = indexes.recovery_plan(db, name, oid)
        assert not repair['target']['valid']
        with pytest.raises(InvalidPolicyError):
            indexes.plan(db)
        with pytest.raises(InvalidPolicyError):
            indexes.recover(db, name, oid, '0' * 64)
        repaired = indexes.recover(db, name, oid, repair['sha256'])
        assert repaired['status'] == 'completed' and repaired['valid']
        assert all(leaf['ready_index'] for leaf in indexes.plan(db)['leaves'])
        with pytest.raises(InvalidPolicyError):
            indexes.recovery_plan(db, name, repaired['observed_oid'])
    # A canceled REINDEX leaves a real _ccnew artifact. Replacement must add a
    # different equivalent index while preserving both old OIDs and definitions.
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("CREATE TABLE interactions_20260106 PARTITION OF interactions "
                   "FOR VALUES FROM ('2026-01-06') TO ('2026-01-07')")
        db.execute("INSERT INTO interactions SELECT '2026-01-06'::date,id,document "
                   "FROM interactions_20260104")
    name = indexes.index_name('public', 'interactions_20260106')
    for operation in ('create', 'reindex'):
        with psycopg.connect(dsn) as blocker:
            blocker.execute("INSERT INTO interactions VALUES('2026-01-06',%s,'{}')", ('held-' + operation,))
            with (psycopg.connect(dsn, autocommit=True, options='-c statement_timeout=1000') as builder,
                  pytest.raises(psycopg.errors.QueryCanceled)):
                if operation == 'create':
                    indexes.create_index(builder, 'public', 'interactions_20260106', concurrent=True)
                else:
                    indexes._reindex(builder, 'public', name)
            blocker.commit()
    with psycopg.connect(dsn, autocommit=True) as db:
        target, artifacts = indexes._replacement_context(db, name)
        artifact_oids = [x['oid'] for x in artifacts]
        assert len(artifact_oids) == 1
        with pytest.raises(InvalidPolicyError):
            indexes.plan(db)
        with pytest.raises(InvalidPolicyError):
            indexes.recovery_plan(db, name, target['index_oid'])
        snapshot = db.execute('SELECT count(*),sum(length(document)) FROM interactions_20260106').fetchone()
        replacement = indexes.replacement_plan(db, name, target['index_oid'], artifact_oids,
                                               statement_timeout_ms=120000)
        with pytest.raises(InvalidPolicyError):
            indexes.replace(db, name, target['index_oid'], artifact_oids, replacement['sha256'])
        with psycopg.connect(dsn) as blocker:
            blocker.execute("INSERT INTO interactions VALUES('2026-01-06','held-replacement','{}')")
            with (psycopg.connect(dsn, autocommit=True, options='-c statement_timeout=1000') as builder,
                  pytest.raises(psycopg.errors.QueryCanceled)):
                indexes.create_index(builder, 'public', 'interactions_20260106', concurrent=True,
                                     name=replacement['replacement'])
            blocker.rollback()
        replacement_oid = db.execute('SELECT to_regclass(%s)::oid', (replacement['replacement'],)).fetchone()[0]
        repair = indexes.replacement_recovery_plan(db, name, target['index_oid'], artifact_oids, replacement_oid,
                                                  statement_timeout_ms=120000)
        with pytest.raises(InvalidPolicyError):
            indexes.recover_replacement(db, name, target['index_oid'], artifact_oids, replacement_oid,
                                        repair['sha256'])
        result = indexes.recover_replacement(db, name, target['index_oid'], artifact_oids, replacement_oid,
                                             repair['sha256'], statement_timeout_ms=120000)
        assert result['status'] == 'completed' and result['preserved_objects_modified'] is False
        assert indexes._replacement_context(db, name) == (target, artifacts)
        assert db.execute('SELECT count(*),sum(length(document)) FROM interactions_20260106').fetchone() == snapshot
        ready = indexes.plan(db, statement_timeout_ms=120000)
        assert ready['leaves'][-1]['ready_index'] == replacement['replacement']
        with pytest.raises(InvalidPolicyError):
            indexes.replacement_plan(db, name, target['index_oid'], artifact_oids)
        with pytest.raises(InvalidPolicyError):
            indexes.replacement_recovery_plan(db, name, target['index_oid'], artifact_oids,
                                              result['observed_oid'])
    large_ms = None
    if os.environ.get('SUBLLM_TEST_LARGE_INDEX') == '1':
        # One GiB of synthetic uncompressed documents exercises the opt-in
        # maintenance budget; no shared archive or interaction payload is read.
        with psycopg.connect(dsn, autocommit=True, options='-c statement_timeout=120000') as db:
            db.execute("CREATE TABLE interactions_20260108 PARTITION OF interactions "
                       "FOR VALUES FROM ('2026-01-08') TO ('2026-01-09')")
            db.execute("INSERT INTO interactions SELECT '2026-01-08'::date,'large-'||i,"
                       "json_build_object('kind','llm_attempt','caller','index-large',"
                       "'started_at','2026-01-08T00:00:00Z','request',repeat(md5(i::text),16384))::text "
                       "FROM generate_series(1,2048)i")
            selected = indexes.plan(db, statement_timeout_ms=120000)
            start = time.perf_counter()
            large = indexes.apply(db, selected['sha256'], maximum=1, statement_timeout_ms=120000)
            large_ms = round((time.perf_counter() - start) * 1000, 3)
            assert large['status'] == 'completed' and large['remaining'] == 0
            assert all(x['ready_index'] for x in indexes.plan(db)['leaves'])
    # A conflicting named index is preserved, never dropped/rebuilt implicitly.
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("CREATE TABLE interactions_20260107 PARTITION OF interactions "
                   "FOR VALUES FROM ('2026-01-07') TO ('2026-01-08')")
        name = indexes.index_name('public', 'interactions_20260107')
        from psycopg import sql
        db.execute(sql.SQL('CREATE INDEX {} ON interactions_20260107(id)').format(sql.Identifier(name)))
        with pytest.raises(InvalidPolicyError):
            indexes.plan(db)
        assert db.execute('SELECT to_regclass(%s)', (name,)).fetchone()[0] is not None
        db.execute('CREATE SCHEMA writer_scope')
    # A public index with the same name must not suppress first-use creation
    # in the writer's actual creation namespace.
    from psycopg.conninfo import make_conninfo
    scoped = InteractionStore(Path('/unused-scoped-writer'),
                              postgres_dsn=make_conninfo(dsn, options='-c search_path=writer_scope,public'))
    with scoped.connect('2026-01-01', True) as db:
        assert db.execute("SELECT to_regclass('writer_scope.interaction_started')").fetchone()[0] is not None
    print(json.dumps({'status': 'passed', 'rows': 1500, 'payload_bytes': 65536,
                      'before_ms': round(before_ms, 3), 'after_ms': round(after_ms, 3),
                      'concurrent_writer': 'passed', 'query_parity': 'passed', 'caller_index_conditions': 3,
                      'invalid_index_recovery': 'passed', 'recovery_fixture_rows': 500,
                      'preserved_reindex_artifact_replacement': 'passed',
                      'failed_replacement_recovery': 'passed', 'native_writer_namespace': 'passed',
                      'large_fixture_document_bytes': 1073741824 if large_ms is not None else None,
                      'large_index_ms': large_ms}))


if __name__ == '__main__':
    verify_postgres()
