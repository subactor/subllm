from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from subllm import policy
from subllm.catalog import compile_catalog, export_catalog, load_catalog, read_document
from subllm.catalog_cli import main, propose
from subllm.catalog_schema import schema
from subllm.errors import InvalidPolicyError
from subllm.resolver import configured_routes


def document():
    return copy.deepcopy(export_catalog())


def test_compilation_preserves_all_legacy_structures_and_is_immutable():
    raw = document()
    compiled = compile_catalog(raw)
    assert dict(compiled.providers) == dict(policy._BASE_PROVIDERS)
    assert dict(compiled.models) == dict(policy._BASE_MODELS)
    assert dict(compiled.applications) == dict(policy.APPLICATIONS)
    assert dict(compiled.routes) == dict(policy.ROUTES)
    with pytest.raises(TypeError):
        compiled.models['other'] = compiled.models['glm-5.3']
    with pytest.raises(TypeError):
        compiled.provider_defaults['zai']['enabled'] = False
    raw['applications']['wellman']['title'] = 'changed'
    assert compiled.applications['wellman'].title != 'changed'


def toml(value):
    if isinstance(value, dict):
        return '{' + ', '.join(json.dumps(k) + '=' + toml(v) for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(toml(v) for v in value) + ']'
    return json.dumps(value, ensure_ascii=False)


def test_json_and_toml_share_semantic_identity_and_raw_file_pins(tmp_path):
    raw = document()
    paths = [tmp_path / 'catalog.json', tmp_path / 'catalog.toml']
    paths[0].write_text(json.dumps(raw))
    paths[1].write_text('\n'.join(k + '=' + toml(v) for k, v in raw.items()))
    compiled = [load_catalog(p, hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths]
    assert compiled[0].sha256 == compiled[1].sha256
    assert dict(compiled[0].routes) == dict(compiled[1].routes)
    with pytest.raises(InvalidPolicyError):
        load_catalog(paths[0], '0' * 64)
    linked = tmp_path / 'link.json'
    linked.symlink_to(paths[0])
    with pytest.raises(InvalidPolicyError):
        load_catalog(linked, hashlib.sha256(paths[0].read_bytes()).hexdigest())
    paths[0].write_text('{"schema":1,"schema":2}')
    with pytest.raises(InvalidPolicyError):
        read_document(paths[0])


def test_transport_schema_accepts_export_and_rejects_unknown_fields():
    spec = schema()
    Draft202012Validator.check_schema(spec)
    validator = Draft202012Validator(spec)
    raw = document()
    validator.validate(raw)
    raw['providers']['openrouter']['credential'] = 'redacted'
    assert list(validator.iter_errors(raw))
    with pytest.raises(InvalidPolicyError):
        compile_catalog(raw)


@pytest.mark.parametrize('case', ['version', 'provider', 'endpoint', 'credential-name', 'transport', 'priority',
                                 'model', 'forbidden', 'route', 'application', 'duplicate', 'parameters', 'vision',
                                 'header', 'url', 'default', 'candidate-model', 'empty-alias', 'wire-alias',
                                 'provider-priority', 'route-priority', 'surrogate'])
def test_bad_catalog_fails_before_registration(case):
    raw = document()
    candidate = raw['routes'][0]['candidates'][0]
    if case == 'version':
        raw['version'] = True
    elif case == 'provider':
        del raw['providers']['openrouter']
    elif case == 'endpoint':
        raw['providers']['openrouter']['api_base'] = 'https://unapproved.invalid'
    elif case == 'credential-name':
        raw['providers']['openrouter']['api_key_env'] = 'OTHER_KEY'
    elif case == 'transport':
        raw['providers']['openrouter']['transport'] = 'shell'
    elif case == 'priority':
        raw['providers']['zai']['priority'] = -1
    elif case == 'model':
        candidate['model'] = 'missing'
    elif case == 'forbidden':
        banned = next(k for k, v in raw['models'].items() if v['forbidden'])
        raw['models'][banned]['forbidden'] = False
    elif case == 'route':
        raw['routes'].append(copy.deepcopy(raw['routes'][0]))
    elif case == 'application':
        raw['routes'][0]['application'] = 'missing'
    elif case == 'duplicate':
        raw['routes'][0]['candidates'].append(copy.deepcopy(candidate))
    elif case == 'parameters':
        candidate['model_parameters'] = {'messages': 'override'}
    elif case == 'vision':
        raw['routes'][0]['modality'] = 'vision'
    elif case == 'header':
        raw['applications']['wellman']['title'] = 'Title\nInjected'
    elif case == 'url':
        raw['applications']['wellman']['url'] = 'https://[bad'
    elif case == 'default':
        raw['providers']['zai']['default_model'] = 'missing'
    elif case == 'candidate-model':
        candidate['model'] = []
    elif case == 'empty-alias':
        candidate['model'] = ''
    elif case == 'wire-alias':
        raw['models']['deepseek-v4.1-flash']['providers']['openrouter']['litellm_model'] = 'openai/other'
    elif case == 'provider-priority':
        raw['providers']['openrouter']['priority'] = raw['providers']['zai']['priority']
    elif case == 'route-priority':
        other = copy.deepcopy(candidate)
        other['model_parameters'] = {'verbosity': 'low'}
        raw['routes'][0]['candidates'].append(other)
    elif case == 'surrogate':
        raw['applications']['wellman']['title'] = '\ud800'
    with pytest.raises(InvalidPolicyError):
        compile_catalog(raw)


def test_editor_validates_complete_candidate_and_never_overwrites(tmp_path, capsys):
    raw = document()
    ops = [{'op': 'replace', 'path': ['applications', 'wellman', 'title'], 'value': 'Wellman proposal'}]
    base = compile_catalog(raw).sha256
    updated, receipt = propose(raw, ops, base)
    assert receipt['authority'] == 'none' and receipt['base_sha256'] == base
    assert updated['applications']['wellman']['title'] == 'Wellman proposal'
    assert raw['applications']['wellman']['title'] != 'Wellman proposal'
    with pytest.raises(InvalidPolicyError):
        propose(raw, ops, '0' * 64)
    with pytest.raises(InvalidPolicyError):
        propose(raw, [{'op': 'remove', 'path': ['providers', 'zai']}], base)
    source, operations, output = (tmp_path / n for n in ('source.json', 'ops.json', 'proposal.json'))
    source.write_text(json.dumps(raw))
    operations.write_text(json.dumps(ops))
    args = ['propose', str(source), '--operations', str(operations), '--expected-sha256', base, '--output', str(output)]
    assert main(args) == 0
    first = output.read_bytes()
    assert compile_catalog(json.loads(first)).sha256 == receipt['catalog_sha256']
    assert main(args) == 2 and output.read_bytes() == first
    assert json.loads(source.read_text()) == raw
    assert output.stat().st_mode & 0o777 == 0o600
    capsys.readouterr()


def test_pinned_startup_adds_application_from_data_without_code_changes(tmp_path):
    raw = document()
    raw['applications']['catalog-demo'] = {'title': 'Catalog demo', 'url': 'https://example.invalid/catalog'}
    raw['routes'].append({'application': 'catalog-demo', 'function': 'generate', 'modality': 'text',
                          'candidates': [{'provider': 'openrouter', 'model': 'deepseek-v4.1-flash',
                                          'priority_offset': 0, 'model_parameters': {}}]})
    file = tmp_path / 'catalog.json'
    file.write_text(json.dumps(raw))
    env = {**os.environ, 'SUBLLM_CATALOG_FILE': str(file),
           'SUBLLM_CATALOG_SHA256': hashlib.sha256(file.read_bytes()).hexdigest()}
    env.pop('SUBLLM_POLICY_FILE', None)
    code = '''import json
from subllm.resolver import configured_routes,validate_policy
validate_policy()
print(json.dumps(configured_routes('catalog-demo','generate',environ={})[0].public_dict()))'''
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, text=True,
                            capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route['model'] == 'deepseek-v4.1-flash' and len(route['policy_sha256']) == 64
    file.write_text(file.read_text() + ' ')
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, text=True,
                            capture_output=True, timeout=20)
    assert result.returncode != 0 and 'pin mismatch' in result.stderr


def test_effective_digest_binds_runtime_and_concrete_route(monkeypatch):
    first = configured_routes('subactor-proxy', 'chat', environ={})
    second = configured_routes('subactor-proxy', 'chat', environ={})
    assert [r.policy_sha256 for r in first] == [r.policy_sha256 for r in second]
    assert all(len(r.public_dict()['policy_sha256']) == 64 for r in first)
    from subllm.catalog import effective_digest
    from subllm.policy_config import load_policy_config
    runtime = load_policy_config(environ=dict(os.environ))
    from dataclasses import replace
    changed = replace(runtime, execution=replace(runtime.execution, max_attempts=runtime.execution.max_attempts + 1))
    assert effective_digest(runtime, first[0]) == first[0].policy_sha256
    plain = replace(first[0], policy_sha256='')
    assert effective_digest(runtime, plain) != effective_digest(changed, plain)
    assert effective_digest(runtime, plain) != effective_digest(runtime, replace(plain, model='other'))


def test_unknown_route_and_malformed_editor_operation_fail_with_typed_errors():
    from subllm.errors import UnknownRouteError
    with pytest.raises(UnknownRouteError):
        configured_routes('catalog-missing', 'missing', environ={})
    raw = document()
    with pytest.raises(InvalidPolicyError):
        propose(raw, [{'op': [], 'path': ['version']}], compile_catalog(raw).sha256)


def test_digest_does_not_depend_on_credentials():
    from subllm.resolver import available_routes
    env = {'SUBLLM_PROVIDER_ORDER': 'openrouter'}
    first = available_routes('subactor-proxy', 'chat', environ=env, credentials={'openrouter': 'redacted'})
    second = available_routes('subactor-proxy', 'chat', environ=env, credentials={'openrouter': 'redacted-other'})
    assert first and second
    assert [r.policy_sha256 for r in first] == [r.policy_sha256 for r in second]
    assert all('api_key' not in r.public_dict() for r in first)


@pytest.mark.parametrize('missing', ['SUBLLM_CATALOG_FILE', 'SUBLLM_CATALOG_SHA256'])
def test_partial_activation_never_falls_back_to_legacy_defaults(tmp_path, missing):
    file = tmp_path / 'catalog.json'
    file.write_text(json.dumps(document()))
    env = {**os.environ, 'SUBLLM_CATALOG_FILE': str(file),
           'SUBLLM_CATALOG_SHA256': hashlib.sha256(file.read_bytes()).hexdigest()}
    env.pop(missing)
    result = subprocess.run([sys.executable, '-c', 'import subllm.policy'], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and 'InvalidPolicyError' in result.stderr


def test_data_limits_and_code_forbidden_wire_cannot_be_aliased(tmp_path):
    oversized = tmp_path / 'oversized.json'
    oversized.write_bytes(b' ' * 65)
    with pytest.raises(InvalidPolicyError):
        read_document(oversized, maximum=64)
    with pytest.raises(InvalidPolicyError):
        read_document(tmp_path)
    raw = document()
    banned = next(v for v in raw['models'].values() if v['forbidden'])
    raw['models']['alias-forbidden'] = {**copy.deepcopy(banned), 'forbidden': False}
    with pytest.raises(InvalidPolicyError):
        compile_catalog(raw)
