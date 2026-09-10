"""Real bridge projection keeps semantics and detects omitted-evidence conflicts."""
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from subllm.code_context import CodeContext, unique_records
from subllm.errors import CompletionError

MODULE = Path(__file__).parents[1] / 'src/subllm/code2dsl_projection.mjs'


def project(records):
    script = '''import {projectRecord} from MODULE;
let input = ''; for await (const chunk of process.stdin) input += chunk;
console.log(JSON.stringify(JSON.parse(input).map(record => projectRecord(record))));'''
    script = script.replace('MODULE', json.dumps(MODULE.as_uri()))
    result = subprocess.run(['node', '--input-type=module', '-e', script], input=json.dumps(records),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def record():
    return {'schemaVersion': 't2c.intent/v1', 'id': 'one',
            'statement': {'kind': 'fact', 'text': 'declare function'}, 'epistemic': {'class': 'fact'},
            'metadata': {'arguments': ['user'], 'generation': {'evidence': 'redundant' * 100000}},
            'source': {'path': 'a.py', 'lines': {'start': 1, 'end': 1}, 'symbol': 'a',
                       'extractor': 'test/v1', 'rawExcerpt': 'def a(): pass' * 100000}}


def test_projection_preserves_existing_model_input_and_binds_full_evidence():
    original = record()
    projected = project([original])[0]
    context = CodeContext([original], {'a.py': b'def a(): pass\n'}, {})
    assert context.projection(projected) == context.projection(original)
    assert len(json.dumps(projected)) < len(json.dumps(original)) / 100
    assert projected['record_digest'].startswith('sha256-')
    assert 'rawExcerpt' not in projected['source']
    assert 'generation' not in projected['metadata']


def test_conflict_in_omitted_evidence_still_rejected():
    original = record()
    conflicting = deepcopy(original)
    conflicting['source']['rawExcerpt'] = 'different'
    with pytest.raises(CompletionError, match='conflicting source identity'):
        unique_records(project([original, conflicting]))


def test_key_order_and_exact_duplicates_are_not_conflicts():
    original = record()
    reordered = dict(reversed(list(original.items())))
    reordered['source'] = dict(reversed(list(original['source'].items())))
    assert len(unique_records(project([original, reordered, original]))) == 1


def test_bounded_canonical_excerpt_remains_available_to_editing():
    original = record()
    original['source']['rawExcerpt'] = 'def a(): pass'
    projected = project([original])[0]
    from subllm.dsl_edit import editing_records
    from subllm.edit_contract import enrich_records
    context = CodeContext([projected], {'a.py': b'def a(): pass\n'}, {})
    selected = enrich_records(context, editing_records(context, [context.projection(projected)]))
    assert selected[0]['editable'] is True
    assert selected[0]['patchable'] is True
    assert selected[0]['patch_excerpt'] == original['source']['rawExcerpt']


@pytest.mark.parametrize('body', ['def a(): pass', 'x' * 2001])
def test_excerpt_reference_rejects_changed_or_oversized_local_source(body):
    from subllm.code_context import digest, restore_excerpt
    source = {'lines': {'start': 1, 'end': 1},
              'excerpt_sha256': digest((body if len(body) > 2000 else 'different').encode())}
    with pytest.raises(CompletionError, match='canonical excerpt digest mismatch'):
        restore_excerpt(source, body.split('\n'))
