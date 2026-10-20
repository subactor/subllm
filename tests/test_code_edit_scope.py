import gzip
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from subllm import code_context_extraction, dsl_edit
from subllm.code_context import CodeContext
from subllm.code_context_scope import load_scope, parse_scope
from subllm.errors import CompletionError


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def record(name, identity):
    return {'schemaVersion': 't2c.intent/v1', 'id': identity,
            'statement': {'kind': 'python_symbol_fact', 'text': 'declare allowed'},
            'epistemic': {'class': 'fact'},
            'source': {'path': name, 'lines': {'start': 1, 'end': 2}, 'symbol': 'allowed',
                       'extractor': 't2c/python-ast@5', 'rawExcerpt': 'def allowed():\n    return True'}}


@pytest.fixture
def scoped_repository(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Scope test')
    git(tmp_path, 'config', 'user.email', 'scope@example.invalid')
    (tmp_path / 'src').mkdir()
    for name in ('auth.py', 'dependency.py'):
        (tmp_path / 'src' / name).write_text('def allowed():\n    return True\n')
    intent = tmp_path / 'project/ticket-001/intent.json'
    intent.parent.mkdir(parents=True)
    intent.write_text(json.dumps({'ticket': 'ticket-001', 'allowedPaths': ['src/auth.py', 'src/new.py']}))
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-qm', 'fixture')
    scope = {'schema': 'subllm.code-edit-scope/v1', 'worktree': str(tmp_path),
             'head_sha': git(tmp_path, 'rev-parse', 'HEAD'), 'ticket': 'ticket-001',
             'intent_sha256': hashlib.sha256(intent.read_bytes()).hexdigest(),
             'write_paths': ['src/auth.py', 'src/new.py'], 'read_paths': ['src/dependency.py']}
    return tmp_path, scope


def fixture_context(root):
    names = ['src/auth.py', 'src/dependency.py']
    return CodeContext([record(name, str(i)) for i, name in enumerate(names)],
                       {name: (root / name).read_bytes() for name in names}, {'source_sha': 'a' * 40})


@pytest.mark.parametrize('field,value', [
    ('head_sha', '0' * 40), ('intent_sha256', '0' * 64), ('worktree', '/wrong/worktree'),
    ('ticket', '../outside'), ('write_paths', ['src/dependency.py']), ('read_paths', ['../escape.py']),
    ('read_paths', ['.env.py']), ('write_paths', []), ('write_paths', ['src/auth.py', 'src/auth.py']),
])
def test_invalid_scope_prevents_extraction_and_completion(scoped_repository, monkeypatch, field, value):
    root, scope = scoped_repository
    scope[field] = value
    monkeypatch.setattr(dsl_edit, 'extract_context', lambda *a, **k: pytest.fail('must not extract'))
    with pytest.raises(CompletionError):
        dsl_edit.execute_dsl_edit(root, 'repair', provider=None, environ={}, timeout_seconds=30,
                                 complete=lambda *a, **k: pytest.fail('must not call provider'), context_scope=scope)


def test_scope_rejects_symlinked_context_and_stale_intent(scoped_repository):
    root, scope = scoped_repository
    (root / 'src/dependency.py').unlink()
    (root / 'src/dependency.py').symlink_to(root / 'src/auth.py')
    with pytest.raises(CompletionError, match='symlink'):
        parse_scope(root, scope)
    scope['read_paths'] = []
    parsed = parse_scope(root, scope)
    (root / 'project/ticket-001/intent.json').write_text('{}')
    with pytest.raises(CompletionError, match='stale'):
        parsed.verify()


def test_extraction_filters_before_reading_unrelated_sources(scoped_repository, monkeypatch):
    root, value = scoped_repository
    names = ['src/auth.py', 'src/dependency.py', *(f'src/unrelated-{i}.py' for i in range(2000))]
    scope = parse_scope(root, value)
    runtime = root / 'runtime'
    runtime.mkdir()
    original_read = Path.read_bytes
    snapshots = []

    def guarded_read(path):
        assert 'unrelated-' not in path.name
        return original_read(path)

    def execute(args, **kwargs):
        if args[0] == 'node':
            assert kwargs['env']['TMPDIR'] == str(Path(args[4]).parent)
            snapshot = Path(args[3])
            snapshots.append(sorted(p.relative_to(snapshot).as_posix() for p in snapshot.rglob('*.py')))
            Path(args[4]).write_bytes(gzip.compress(json.dumps({'records': [], 'warnings': []}).encode()))
            return subprocess.CompletedProcess(args, 0)
        output = 'a' * 40 if '-C' in args else '\0'.join(names)
        return subprocess.CompletedProcess(args, 0, output.encode())

    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    monkeypatch.setattr(code_context_extraction, 'runtime_digest', lambda p: 'b' * 64)
    monkeypatch.setattr(code_context_extraction.subprocess, 'run', execute)
    # The independently parsed scope binding was checked above; keep the test's
    # fake extractor transport from replacing the scope's real Git observation.
    monkeypatch.setattr(type(scope), 'verify', lambda self: None)
    result = code_context_extraction.extract_context(root, {
        'SUBLLM_CODE2DSL_RUNTIME': str(runtime), 'SUBLLM_CODE2DSL_SHA': 'a' * 40,
        'SUBLLM_CODE2DSL_BUILD_SHA256': 'b' * 64}, scope=scope)
    assert snapshots == [['src/auth.py', 'src/dependency.py']]
    assert set(result.sources) == {'src/auth.py', 'src/dependency.py'}
    assert result.runtime_receipt['context_scope_sha256'] == scope.sha256


def test_explicit_ignored_or_missing_read_context_is_rejected(scoped_repository):
    root, value = scoped_repository
    scope = parse_scope(root, value)
    with pytest.raises(CompletionError, match='ignored'):
        scope.source_names(['src/auth.py'])
    (root / 'src/dependency.py').unlink()
    with pytest.raises(CompletionError, match='must exist'):
        scope.source_names(['src/auth.py'])


@pytest.mark.parametrize('operation', ['edits', 'patches', 'json_updates', 'creates'])
def test_read_context_is_not_write_authority(scoped_repository, operation):
    root, value = scoped_repository
    scope = parse_scope(root, value)
    selected = [record('src/dependency.py', 'dependency')]
    answer = {operation: [{'path': 'src/dependency.py'} if operation == 'creates' else {'id': 'dependency'}]}
    with pytest.raises(CompletionError, match='write scope'):
        scope.check_plan(selected, answer)


def test_scoped_dsl_run_applies_only_declared_write(scoped_repository, monkeypatch):
    root, scope = scoped_repository
    context = fixture_context(root)
    monkeypatch.setattr(dsl_edit, 'extract_context', lambda *a, **k: context)
    calls = []

    def complete(application, function, messages, **kwargs):
        calls.append(function)
        answer = {'ids': ['0', '1']} if function == 'code-context' else {
            'edits': [{'id': '0', 'file_sha256': hashlib.sha256(context.sources['src/auth.py']).hexdigest(),
                       'replacement': 'def allowed():\n    return False\n'}], 'summary': 'repair'}
        return SimpleNamespace(content=json.dumps(answer), provider='fixture', model='fixture')

    result = dsl_edit.execute_dsl_edit(root, 'repair', provider=None, environ={}, timeout_seconds=30,
                                      complete=complete, context_scope=scope)
    assert calls == ['code-context', 'code-edit']
    assert 'return False' in (root / 'src/auth.py').read_text()
    assert 'return True' in (root / 'src/dependency.py').read_text()
    assert json.loads(result[2])['progress']['context_calls'] == 1


def test_changed_scope_after_selection_prevents_apply(scoped_repository, monkeypatch):
    root, scope = scoped_repository
    context = fixture_context(root)
    monkeypatch.setattr(dsl_edit, 'extract_context', lambda *a, **k: context)

    def complete(application, function, messages, **kwargs):
        if function == 'code-context':
            answer = {'ids': ['0']}
        else:
            (root / 'project/ticket-001/intent.json').write_text('{}')
            answer = {'edits': [{'id': '0', 'file_sha256': hashlib.sha256(context.sources['src/auth.py']).hexdigest(),
                                 'replacement': 'def allowed():\n    return False\n'}], 'summary': 'repair'}
        return SimpleNamespace(content=json.dumps(answer), provider='fixture', model='fixture')

    with pytest.raises(CompletionError):
        dsl_edit.execute_dsl_edit(root, 'repair', provider=None, environ={}, timeout_seconds=30,
                                 complete=complete, context_scope=scope)
    assert 'return True' in (root / 'src/auth.py').read_text()


def test_scope_file_requires_exact_digest_and_unique_fields(scoped_repository):
    root, scope = scoped_repository
    path = root / 'scope.json'
    path.write_text(json.dumps(scope))
    assert load_scope(path, hashlib.sha256(path.read_bytes()).hexdigest()) == scope
    with pytest.raises(CompletionError, match='digest'):
        load_scope(path, '0' * 64)
    path.write_text('{"schema":1,"schema":2}')
    with pytest.raises(CompletionError, match='JSON'):
        load_scope(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_scope_file_refuses_oversize_and_symlink(tmp_path):
    path = tmp_path / 'scope.json'
    path.write_bytes(b' ' * 65_537)
    with pytest.raises(CompletionError, match='budget'):
        load_scope(path, '0' * 64)
    link = tmp_path / 'scope-link.json'
    link.symlink_to(path)
    with pytest.raises(CompletionError, match='symlink'):
        load_scope(link, '0' * 64)
