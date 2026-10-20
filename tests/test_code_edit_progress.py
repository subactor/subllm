import hashlib
import json
from types import SimpleNamespace

import pytest

from subllm import client_code_edit, dsl_edit
from subllm.code_context import CodeContext
from subllm.code_edit_progress import CodeEditProgress
from subllm.errors import CompletionError


def context(root):
    source = b'def allowed():\n    return True\n'
    (root / '.git').mkdir()
    (root / 'auth.py').write_bytes(source)
    record = {'schemaVersion': 't2c.intent/v1', 'id': 'auth',
              'statement': {'kind': 'python_symbol_fact', 'text': 'declare allowed'},
              'epistemic': {'class': 'fact'},
              'source': {'path': 'auth.py', 'lines': {'start': 1, 'end': 2}, 'symbol': 'allowed',
                         'extractor': 't2c/python-ast@5', 'rawExcerpt': source.decode().rstrip()}}
    return CodeContext([record], {'auth.py': source}, {'source_sha': 'a' * 40})


@pytest.mark.parametrize('bad_answer', ['not json', '{"ids":["invented"]}'])
def test_budget_covers_json_and_selection_retries(tmp_path, monkeypatch, bad_answer):
    ctx = context(tmp_path)
    monkeypatch.setattr(dsl_edit, 'extract_context', lambda *a: ctx)
    calls = []

    def complete(*args, **kwargs):
        calls.append(args[1])
        return SimpleNamespace(content=bad_answer, provider='fixture', model='fixture')

    with pytest.raises(CompletionError, match='budget exhausted') as observed:
        dsl_edit.execute_dsl_edit(tmp_path, 'private task', provider=None, environ={}, timeout_seconds=30,
                                 complete=complete, max_context_queries=1)
    receipt = observed.value.code_edit_receipt
    assert calls == ['code-context']
    assert receipt['context_calls'] == 1 and len(receipt['queries']) == 1
    assert receipt['queries'][0]['status'] in ('rejected', 'parsed')
    assert 'private task' not in json.dumps(receipt)


def test_one_budget_spans_multiple_selection_queries(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    monkeypatch.setattr(dsl_edit, 'extract_context', lambda *a: ctx)
    monkeypatch.setattr(dsl_edit, 'select_code_context', lambda c, p, q: [
        q('code-context', phase, {'records': []}) for phase in ('inventory', 'detail', 'reduction')])
    calls = []

    def complete(*args, **kwargs):
        calls.append(args[1])
        return SimpleNamespace(content='{"ids":[]}', provider='fixture', model='fixture')

    with pytest.raises(CompletionError, match='budget exhausted') as observed:
        dsl_edit.execute_dsl_edit(tmp_path, 'repair', provider=None, environ={}, timeout_seconds=30,
                                 complete=complete, max_context_queries=2)
    assert calls == ['code-context', 'code-context']
    assert observed.value.code_edit_receipt['context_calls'] == 2


def test_progress_sink_failure_cannot_retry_a_completion(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    monkeypatch.setattr(dsl_edit, 'extract_context', lambda *a: ctx)
    calls, events = [], []

    def sink(event):
        events.append(event)
        if event['phase'] == 'query':
            raise RuntimeError('PRIVATE SINK ERROR')

    def complete(*args, **kwargs):
        calls.append(args[1])
        answer = {'ids': ['auth']} if args[1] == 'code-context' else {
            'edits': [{'id': 'auth', 'file_sha256': hashlib.sha256(ctx.sources['auth.py']).hexdigest(),
                       'replacement': 'def allowed():\n    return False\n'}], 'summary': 'repair'}
        return SimpleNamespace(content=json.dumps(answer), provider='fixture', model='fixture')

    result = dsl_edit.execute_dsl_edit(tmp_path, 'PRIVATE PROMPT', provider=None, environ={'SECRET': 'PRIVATE KEY'},
                                      timeout_seconds=30, complete=complete, progress_sink=sink)
    receipt = json.loads(result[2])
    assert calls == ['code-context', 'code-edit']
    assert receipt['progress']['sink_failed']
    assert len({event['run_id'] for event in events}) == 1
    assert len({q['query_id'] for q in receipt['queries']}) == 2
    assert all(secret not in json.dumps(events) for secret in ('PRIVATE PROMPT', 'PRIVATE KEY', 'def allowed'))


def test_failed_provider_retains_completed_history(tmp_path, monkeypatch):
    ctx = context(tmp_path)
    monkeypatch.setattr(dsl_edit, 'extract_context', lambda *a: ctx)
    events = []

    def complete(*args, **kwargs):
        if args[1] == 'code-edit':
            raise CompletionError('PRIVATE PROVIDER ERROR')
        return SimpleNamespace(content='{"ids":["auth"]}', provider='fixture', model='fixture')

    with pytest.raises(CompletionError) as observed:
        dsl_edit.execute_dsl_edit(tmp_path, 'repair', provider=None, environ={}, timeout_seconds=30,
                                 complete=complete, progress_sink=events.append)
    receipt = observed.value.code_edit_receipt
    assert [a['status'] for a in receipt['queries']] == ['parsed', 'failed']
    assert events[-1]['phase'] == 'run' and events[-1]['status'] == 'failed'
    assert 'PRIVATE PROVIDER ERROR' not in json.dumps(events + [receipt])


@pytest.mark.parametrize('maximum,timeout', [(True, 30), (0, 30), (129, 30), (1, float('nan')), (1, 0)])
def test_invalid_budgets_fail_before_any_call(maximum, timeout):
    with pytest.raises(CompletionError):
        CodeEditProgress(maximum, timeout)


def test_cli_progress_is_jsonl_on_stderr_and_result_is_single_stdout_json(tmp_path, monkeypatch, capsys):
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('PRIVATE TASK')

    def execute(*args, **kwargs):
        kwargs['progress_sink']({'schema': 'subllm.code-edit-progress/v1', 'phase': 'query'})
        return SimpleNamespace(provider='fixture', model='fixture', response='done')

    monkeypatch.setattr(client_code_edit, 'execute_code_edit', execute)
    assert client_code_edit.code_edit_main(['onedev-agent', 'code-edit', '--worktree', str(tmp_path),
                                           '--prompt-file', str(prompt)]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'SUCCESS'
    assert json.loads(output.err)['phase'] == 'query'
    assert 'PRIVATE TASK' not in output.out + output.err


def test_cli_error_does_not_echo_private_provider_text(tmp_path, monkeypatch, capsys):
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('PRIVATE TASK')

    def execute(*args, **kwargs):
        raise CompletionError('PRIVATE PROVIDER RESPONSE')

    monkeypatch.setattr(client_code_edit, 'execute_code_edit', execute)
    assert client_code_edit.code_edit_main(['onedev-agent', 'code-edit', '--worktree', str(tmp_path),
                                           '--prompt-file', str(prompt)]) == 2
    output = capsys.readouterr()
    assert output.out == ''
    assert 'PRIVATE' not in output.err and 'SUBLLM-CODE-EDIT-FAILED' in output.err


def test_cli_passes_pinned_scope_and_budget_to_sdk(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'scope.json'
    scope = {'schema': 'subllm.code-edit-scope/v1'}
    path.write_text(json.dumps(scope))
    prompt = tmp_path / 'prompt.txt'
    prompt.write_text('repair')
    seen = []

    def execute(*args, **kwargs):
        seen.append(kwargs)
        return SimpleNamespace(provider='fixture', model='fixture', response='done')

    monkeypatch.setattr(client_code_edit, 'execute_code_edit', execute)
    assert client_code_edit.code_edit_main([
        'onedev-agent', 'code-edit', '--worktree', str(tmp_path), '--prompt-file', str(prompt),
        '--context-scope', str(path), '--context-scope-sha256', hashlib.sha256(path.read_bytes()).hexdigest(),
        '--max-context-queries', '7']) == 0
    assert seen[0]['context_scope'] == scope and seen[0]['max_context_queries'] == 7
    assert json.loads(capsys.readouterr().out)['status'] == 'SUCCESS'
