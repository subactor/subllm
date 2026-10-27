"""Execute the shipped browser detail handlers with controlled network ordering."""
from __future__ import annotations

import json
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
  click() { return this.handlers.click?.({target:this}); }
  add(option) { this.options.push(option); }
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
globalThis.Option = class { constructor(text, value) { this.text=text; this.value=value; } };
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


@pytest.mark.parametrize('cached', [11008, 0, None, True, -1, 20000])
def test_archive_details_use_exact_day_and_render_only_known_cache(cached):
    run_js('const cached = ' + json.dumps(cached) + ';\n' + r"""
const attempt = {id:'a'.repeat(32), day:'2026-10-27', input_tokens:14945, output_tokens:177};
showDetail(attempt);
const params = new URL(pending[0].url, 'http://localhost').searchParams;
assert.equal(params.get('day'), '2026-10-27');
answer(pending[0], {request:{messages:[]}, response:{content:'answer', usage:{prompt_tokens:14945,
  completion_tokens:177, prompt_tokens_details:{cached_tokens:cached}}}});
await flush();
const text = $('detail-token-summary').textContent.replace(/\s/g, '');
assert.match(text, /14945/); assert.match(text, /177/);
if (Number.isInteger(cached) && cached >= 0 && cached <=14945) assert.ok(text.includes(`${cached}zcache`));
else assert.ok(!text.includes('zcache'));
""")


def test_source_selection_preserves_journal_default_and_invalidates_old_details():
    run_js(r"""
assert.equal(applied.get('source'), 'journal');
showDetail({id:1});
const lists=[];
globalThis.fetch = url => new Promise(resolve => lists.push({url,resolve}));
globalThis.FormData = class {
  constructor(form) { this.values=form.values; }
  *[Symbol.iterator]() { yield* this.values; }
};
const form=$('filters'); form.values=[['source','archive']]; form.elements={since:{value:''}};
busy=false;
$('filters').handlers.submit({target:form,preventDefault(){}});
assert.equal($('detail').hidden, true);
assert.equal(currentSelectedAttempt, null);
let params=new URL(lists[0].url, 'http://localhost').searchParams;
assert.equal(params.get('source'), 'archive'); assert.ok(params.get('since'));
assert.ok(form.elements.since.value);
const empty = {source:'archive',summary:{attempts:0,requests:0,errors:0},
               applications:[],providers:[],attempts:[],next_before:null};
answer(lists[0], empty); await flush();
assert.equal($('source-current').textContent, 'Prywatne archiwum');
answer(pending[0], {request:{messages:[]},response:{content:'late old content'}}); await flush();
assert.equal($('detail').hidden,true);
form.reset=()=>{};
$('clear-filters').handlers.click();
params=new URL(lists[1].url, 'http://localhost').searchParams;
assert.equal(params.get('source'),'journal');
answer(lists[1], {...empty,source:'journal'}); await flush();
assert.equal($('source-current').textContent,'Dziennik użycia');
""")


def test_pending_archive_capture_is_visible_as_in_progress():
    run_js(r"""
showDetail({id:'b'.repeat(32),day:'2026-10-27',status:'pending'});
answer(pending[0], {status:'pending',request:{messages:[]},response:null,
                    payload_capture:{state:'stored',source:'private-archive'}});
await flush();
assert.match($('detail-response').textContent,/Wywołanie trwa/);
assert.equal(JSON.parse($('detail-meta').textContent).status,'pending');
""")
