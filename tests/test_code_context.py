import subprocess

import pytest

from subllm.code_context import CodeContext, encode, extract_context, pages, safe_path, select_code_context
from subllm.dsl_edit import apply_edits, editing_records
from subllm.errors import CompletionError


def context_record(name='src/auth.py', identity='auth', body='def allow(user):\n    return True\n'):
    return {
        'schemaVersion': 't2c.intent/v1', 'id': identity,
        'statement': {'kind': 'python_symbol_fact', 'action': 'declare', 'object': 'allow', 'text': 'declare allow'},
        'source': {'path': name, 'lines': {'start': 1, 'end': len(body.splitlines())},
                   'symbol': 'allow', 'extractor': 't2c/python-ast@5', 'rawExcerpt': body.rstrip('\n')},
        'epistemic': {'class': 'fact'}, 'metadata': {'arguments': ['user']},
    }


def fixture_context(root):
    source = b'def allow(user):\n    return True\n'
    file = root / 'src/auth.py'
    file.parent.mkdir(exist_ok=True)
    file.write_bytes(source)
    context = CodeContext([context_record()], {'src/auth.py': source}, {'source_sha': 'a' * 40})
    return context, file


def test_prose_tests_and_docs_select_only_model_chosen_record():
    records = [context_record()]
    sources = {'src/auth.py': b'def allow(user):\n    return True\n'}
    for i in range(80):
        name = f'tests/unrelated_{i}.py'
        body = '# Unrelated large file\n' * 4000
        records.append(context_record(name, f'other-{i}', body))
        sources[name] = body.encode()
    context = CodeContext(records, sources, {})
    seen = []

    def query(function, instruction, payload):
        seen.extend(r['id'] for r in payload['records'])
        assert 'rawExcerpt' not in encode(payload)
        assert 'Unrelated large file' not in encode(payload)
        return {'ids': ['auth'] if any(r['id'] == 'auth' for r in payload['records']) else []}

    selected = select_code_context(context, 'Fix authentication; update tests and docs, uruchom testów.', query)
    assert [r['id'] for r in selected] == ['auth']
    assert set(seen) == {r['id'] for r in records}
    assert sum(map(len, sources.values())) > 262144


@pytest.mark.parametrize('answer', [{'ids': ['../private.py']}, {'ids': ['auth', 'auth']},
                                   {'ids': ['auth'], 'shell': 'touch evil'}, {'ids': 'auth'}])
def test_model_cannot_invent_selection(tmp_path, answer):
    context, _ = fixture_context(tmp_path)
    with pytest.raises(CompletionError, match='invalid record IDs'):
        select_code_context(context, 'repair', lambda *args: answer)


def test_every_page_is_queried_and_reduction_is_model_driven():
    records = [context_record(identity=f'node-{i}') for i in range(60)]
    context = CodeContext(records, {'src/auth.py': b'def allow(user):\n    return True\n'}, {})
    calls = []

    def query(function, instruction, payload):
        calls.append(instruction)
        ids = [r['id'] for r in payload['records']]
        return {'ids': ids[:4 if 'reduction pass' in instruction else 32]}

    # Enough nodes to force multi-page selection and a semantic reduction.
    for r in records:
        r['statement']['text'] = 'semantic description ' * 80
    chosen = select_code_context(context, 'repair', query)
    assert len(chosen) <= 32
    assert any('reduction pass' in c for c in calls)


def test_page_byte_budget_uses_utf8_and_has_no_silent_truncation():
    records = [{'id': str(i), 'text': 'ą' * 30} for i in range(3)]
    result = pages(records, budget=100)
    assert [r for p in result for r in p] == records
    assert all(len(encode(p).encode()) <= 100 for p in result)
    with pytest.raises(CompletionError, match='single record'):
        pages([{'text': 'x' * 100}], budget=100)


def test_source_boundary_excludes_secret_paths_symlinks_and_traversal(tmp_path):
    for name in ['../auth.py', '.env.py', 'vendor/auth.py', '/tmp/auth.py', 'x/../../auth.py', 'a\\b.py']:
        with pytest.raises(CompletionError):
            safe_path(tmp_path, name)
    (tmp_path / 'linked').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(CompletionError, match='symlink'):
        safe_path(tmp_path, 'linked/auth.py')


def edit_for(record, replacement='def allow(user):\n    return user is not None\n'):
    return {'edits': [{'id': record['id'], 'file_sha256': record['file_sha256'], 'replacement': replacement}],
            'summary': 'Reject missing identity'}


def test_applies_only_exact_node_and_preserves_unrelated_source(tmp_path):
    context, file = fixture_context(tmp_path)
    file.write_bytes(file.read_bytes() + b'\nUNCHANGED = 42\n')
    context.sources['src/auth.py'] = file.read_bytes()
    selected = editing_records(context, [context.projection(context.records[0])])
    receipts = apply_edits(tmp_path, context, selected, edit_for(selected[0]))
    assert file.read_text() == 'def allow(user):\n    return user is not None\n\nUNCHANGED = 42\n'
    assert receipts[0]['before_sha256'] != receipts[0]['after_sha256']


@pytest.mark.parametrize('failure', ['stale', 'digest', 'unknown', 'overlap', 'syntax', 'truncated'])
def test_rejects_unsafe_edits_without_writing(tmp_path, failure):
    context, file = fixture_context(tmp_path)
    if failure == 'truncated':
        context.records[0]['source']['rawExcerpt'] = 'def allow(user):'
    selected = editing_records(context, [context.projection(context.records[0])])
    answer = edit_for(selected[0])
    if failure == 'stale':
        file.write_text('changed by another writer\n')
    elif failure == 'digest':
        answer['edits'][0]['file_sha256'] = '0' * 64
    elif failure == 'unknown':
        answer['edits'][0]['id'] = 'outside'
    elif failure == 'overlap':
        answer['edits'].append(answer['edits'][0])
    elif failure == 'syntax':
        answer['edits'][0]['replacement'] = 'def invalid(\n'
    before = file.read_bytes()
    with pytest.raises(CompletionError):
        apply_edits(tmp_path, context, selected, answer)
    assert file.read_bytes() == before


def test_missing_runtime_does_not_fall_back_to_source(tmp_path):
    with pytest.raises(CompletionError, match='independent build'):
        extract_context(tmp_path, {})






def test_runtime_pin_mismatch_is_rejected_before_extraction(tmp_path, monkeypatch):
    from subllm import code_context

    monkeypatch.setattr(code_context.subprocess, 'run',
                        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, b'b' * 40))
    with pytest.raises(CompletionError, match='pin mismatch'):
        extract_context(tmp_path, {'SUBLLM_CODE2DSL_RUNTIME': str(tmp_path),
                                  'SUBLLM_CODE2DSL_SHA': 'a' * 40,
                                  'SUBLLM_CODE2DSL_BUILD_SHA256': '0' * 64})
