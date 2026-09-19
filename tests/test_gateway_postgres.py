"""Optional real PostgreSQL matrix; each run owns a disposable schema."""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from subllm.interaction_store import InteractionStore


@pytest.mark.skipif(not os.environ.get("SUBLLM_TEST_POSTGRES_DSN"), reason="dedicated PostgreSQL test DSN not supplied")
def test_postgres_concurrency_partition_midnight_export(tmp_path, monkeypatch):
    import psycopg
    from psycopg.conninfo import make_conninfo
    from psycopg.sql import SQL, Identifier

    dsn = os.environ["SUBLLM_TEST_POSTGRES_DSN"]
    schema = "gateway_test_" + uuid4().hex
    with psycopg.connect(dsn) as admin:
        admin.execute(SQL("CREATE SCHEMA {}").format(Identifier(schema)))
    try:
        store = InteractionStore(tmp_path / "unused", make_conninfo(dsn, options=f"-c search_path={schema}"))
        monkeypatch.setattr("subllm.interaction_store.utc_now", lambda: "2026-09-19T23:59:59.999Z")
        def begin(number):
            return store.begin(kind="mcp", caller="test", target="tool", request={"number": number})
        with ThreadPoolExecutor(8) as pool:
            records = list(pool.map(begin, range(16)))
        monkeypatch.setattr("subllm.interaction_store.utc_now", lambda: "2026-09-20T00:00:01.000Z")
        for record in records:
            store.finish(record, {"ok": True}, duration_ms=1001)
        assert len(store.query("2026-09-19")) == 16
        assert store.query("2026-09-20") == []
        destination = tmp_path / "export" / "2026-09-19.sqlite3"
        store.export_day("2026-09-19", destination)
        local = InteractionStore(destination.parent)
        assert all(local.query("2026-09-19", record["id"])["status"] == "success" for record in records)
    finally:
        with psycopg.connect(dsn) as admin:
            admin.execute(SQL("DROP SCHEMA {} CASCADE").format(Identifier(schema)))
