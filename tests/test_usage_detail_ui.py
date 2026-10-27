"""Execute the shipped browser detail handlers with controlled network ordering."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'src/subllm/assets/usage.js'
HARNESS = r"""
const assert = require('node:assert/strict');
class Element {
  constructor() {
    this.handlers = {}; this.children = []; this.options = [{}]; this.style = {};
    this.value = ''; this.textContent = ''; this.hidden = false;
    this.classList = {add() {}, remove() {}};
  }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  append(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = children; }
  scrollIntoView() {}
}
const elements = new Map();
globalThis.document = {
  getElementById(id) { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
  createElement() { return new Element(); }, hidden:false
};
globalThis.setInterval = () => 0;
const pending = [], alerts = [], clipboard = [];
globalThis.alert = text => alerts.push(text);
Object.defineProperty(globalThis, 'navigator', {value:{clipboard:{async writeText(text) { clipboard.push(text); }}}});
globalThis.fetch = url => {
  if (!url.startsWith('/v1/usage/detail?')) return new Promise(() => {});
  return new Promise((resolve, reject) => pending.push({url, resolve, reject}));
};
const flush = () => new Promise(resolve => setImmediate(resolve));
const answer = (request, body, ok=true) => request.resolve({ok, json:async () => body});
"""


def run_js(scenario):
    result = subprocess.run(['node', '-'], input=HARNESS + '\n' + SOURCE.read_text() +
                            '\n(async () => {\n' + scenario +
                            '\n})().catch(error => {console.error(error); process.exitCode=1;});',
                            text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('legacy', [False, True])
def test_numeric_journal_selection_fetches_details_and_explains_unlinked_capture(legacy):
    run_js('const legacy = ' + str(legacy).lower() + ';\n' + r"""
const row = {id:42, request_id:'correlation'};
showDetail(row);
assert.equal(pending.length, 1);
assert.equal(pending[0].url, '/v1/usage/detail?id=42');
assert.match($('detail-prompt').textContent, /Wczytywanie/);
const detail = {request:null, response:null};
if (!legacy) detail.payload_capture = {state:'unlinked', source:'usage-journal'};
answer(pending[0], detail);
await flush();
assert.match($('detail-prompt').textContent, /Brak jednoznacznego powiązania/);
assert.match($('detail-response').textContent, /treść może być zapisana osobno/);
assert.equal(JSON.parse($('detail-meta').textContent).payload_capture.state, 'unlinked');
""")


def test_out_of_order_details_cannot_replace_selected_record_or_mutate_its_task():
    run_js(r"""
const first = {id:1}, second = {id:2};
showDetail(first); showDetail(second);
answer(pending[1], {request:{messages:[{role:'user',content:'second'}]}, response:{content:'second answer'}});
await flush();
answer(pending[0], {request:{messages:[{role:'user',content:'first PLF-999'}]}, response:{content:'first answer'}});
await flush();
assert.equal($('detail-id').textContent, 2);
assert.match($('detail-prompt').textContent, /second/);
assert.equal($('detail-response').textContent, 'second answer');
assert.equal($('detail-planfile').hidden, true);
assert.equal(first.request, undefined);
""")


def test_closed_detail_ignores_pending_response_and_late_error_of_another_selection():
    run_js(r"""
showDetail({id:1});
$('close-detail').handlers.click();
answer(pending[0], {request:{messages:[]}, response:{content:'late'}});
await flush();
assert.equal($('detail').hidden, true);
assert.equal(currentSelectedAttempt, null);
showDetail({id:2}); showDetail({id:3});
answer(pending[2], {request:{messages:[]}, response:{content:'current'}});
await flush();
pending[1].reject(new Error('stale failure'));
await flush();
assert.equal($('detail-response').textContent, 'current');
""")


def test_detail_failure_is_visible_and_never_replaced_with_raw_server_text():
    run_js(r"""
showDetail({id:1});
answer(pending[0], {error:{message:'PRIVATE_SERVER_DETAIL'}}, false);
await flush();
assert.match($('detail-prompt').textContent, /Nie udało się odczytać/);
assert.match($('detail-response').textContent, /Spróbuj ponownie/);
assert.equal(JSON.parse($('detail-meta').textContent).payload_capture.state, 'unavailable');
assert.ok(!$('detail-meta').textContent.includes('PRIVATE_SERVER_DETAIL'));
""")


def test_export_reports_actual_payload_coverage_instead_of_claiming_complete_content():
    run_js(r"""
currentVisibleAttempts = [{id:1}, {id:2, request:{messages:[]}, response:{content:'recorded'}}];
const exporting = $('copy-table-all').handlers.click();
assert.equal(pending.length, 1);
answer(pending[0], {request:null, response:null, payload_capture:{state:'unlinked'}});
await exporting;
assert.equal(clipboard.length, 1);
const exported = JSON.parse(clipboard[0]);
assert.equal(exported[0].payload_capture.state, 'unlinked');
assert.equal(exported[0].request, null);
assert.match(alerts[0], /2 wpisów: 1 z pełną treścią, 1 bez pełnej treści/);
""")
