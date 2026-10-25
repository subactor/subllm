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
import time
from pathlib import Path
from threading import Thread

import psycopg
import pytest

from subllm import usage_indexes as indexes
from subllm.errors import InvalidPolicyError


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
        raise psycopg.errors.LockNotAvailable('private row or credential text must not escape')
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
            raise psycopg.errors.QueryCanceled('private driver detail')
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


@pytest.mark.parametrize('field,value', [(1, False), (2, True), (3, False), (5, 5),
                                        (6, '0 0 0 0'), (9, '0 0 0 0'), (10, '0 0 0 0')])
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
        with psycopg.connect(dsn, options='-c statement_timeout=1000') as fresh_writer:
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
    # A conflicting named index is preserved, never dropped/rebuilt implicitly.
    with psycopg.connect(dsn, autocommit=True) as db:
        db.execute("CREATE TABLE interactions_20260105 PARTITION OF interactions "
                   "FOR VALUES FROM ('2026-01-05') TO ('2026-01-06')")
        name = indexes.index_name('public', 'interactions_20260105')
        from psycopg import sql
        db.execute(sql.SQL('CREATE INDEX {} ON interactions_20260105(id)').format(sql.Identifier(name)))
        with pytest.raises(InvalidPolicyError):
            indexes.plan(db)
        assert db.execute('SELECT to_regclass(%s)', (name,)).fetchone()[0] is not None
    print(json.dumps({'status': 'passed', 'rows': 1500, 'payload_bytes': 65536,
                      'before_ms': round(before_ms, 3), 'after_ms': round(after_ms, 3),
                      'concurrent_writer': 'passed', 'query_parity': 'passed', 'caller_index_conditions': 3}))


if __name__ == '__main__':
    verify_postgres()
