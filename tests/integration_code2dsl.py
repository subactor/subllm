"""Explicit real-runtime suite: missing pins fail; no conditional test skipping."""
import os
import subprocess

from subllm.code_context import encode, extract_context


def test_real_canonical_code2dsl_extracts_python_and_js_without_full_file_context(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    body = 'def allow(user):\n    return user is not None\n' + '# PRIVATE_UNRELATED_SENTINEL\n' * 15000
    (tmp_path / 'auth.py').write_text(body)
    (tmp_path / 'auth.mjs').write_text('export function allow(user) { return user !== null; }\n')
    (tmp_path / '.env.py').write_text('PRIVATE_CREDENTIAL_SENTINEL = "secret"\n')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    context = extract_context(tmp_path, os.environ)
    assert {r['source']['path'] for r in context.records} == {'auth.py', 'auth.mjs'}
    sent = encode([context.projection(r) for r in context.records])
    assert 'PRIVATE_UNRELATED_SENTINEL' not in sent
    assert 'PRIVATE_CREDENTIAL_SENTINEL' not in sent
    assert len(sent.encode()) < len(body.encode()) / 10
    assert any(r['source']['symbol'] == 'allow' for r in context.records)
    assert not (tmp_path / '.intent').exists()
    assert not context.warnings



def test_real_extraction_preserves_operator_ignore_policy(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    (tmp_path / 'auth.py').write_text('def allow(user):\n    return True\n')
    (tmp_path / 'restricted.py').write_text('def private_credentials():\n    return "DO_NOT_SEND"\n')
    (tmp_path / '.aiderignore').write_text('restricted.py\n')
    subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True)
    context = extract_context(tmp_path, os.environ)
    assert {r['source']['path'] for r in context.records} == {'auth.py'}
    assert 'DO_NOT_SEND' not in encode([context.projection(r) for r in context.records])
