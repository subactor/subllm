'use strict';
const $ = id => document.getElementById(id);
let next = null, before = null, busy = false, applied = new URLSearchParams();
const number = value => value == null ? '—' : Number(value).toLocaleString('pl-PL');
function choices(id, values) {
  const select = $(id), selected = select.value;
  select.replaceChildren(select.options[0]);
  for (const value of values) select.add(new Option(value, value));
  if (selected && !values.includes(selected)) select.add(new Option(selected, selected));
  select.value = selected;
}
function cell(row, main, detail) {
  const td = document.createElement('td'); td.textContent = main;
  if (detail) { const small = document.createElement('small'); small.textContent = detail; td.append(small); }
  row.append(td); return td;
}
async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const params = new URLSearchParams(applied);
    if (before) params.set('before', before);
    const response = await fetch('/v1/usage?' + params, {cache:'no-store', signal:AbortSignal.timeout(10000)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || 'Nie można odczytać historii');
    const s = data.summary;
    $('requests').textContent = number(s.requests); $('attempts').textContent = number(s.attempts);
    $('errors').textContent = number(s.errors);
    $('tokens').textContent = `${number(s.input_tokens)} / ${number(s.output_tokens)}`;
    $('coverage').textContent = `Pełne dane o tokenach: ${number(s.usage_known)} z ${number(s.attempts)} prób`;
    choices('application', data.applications); choices('provider', data.providers);
    $('rows').replaceChildren();
    for (const attempt of data.attempts) {
      const tr = document.createElement('tr');
      cell(tr, new Date(attempt.timestamp).toLocaleString('pl-PL'));
      cell(tr, attempt.application, attempt.function); cell(tr, attempt.provider, attempt.model);
      const td = cell(tr, ''); const badge = document.createElement('span');
      badge.className = 'badge' + (attempt.status === 'error' ? ' error' : '');
      badge.textContent = attempt.status === 'success' ? 'Sukces' : 'Błąd'; td.append(badge);
      if(attempt.diagnostic_code) { const small=document.createElement('small'); small.textContent=attempt.diagnostic_code; td.append(small); }
      cell(tr, number(attempt.duration_ms) + ' ms');
      cell(tr, `${number(attempt.input_tokens)} / ${number(attempt.output_tokens)}`);
      const request = cell(tr, ''); const code = document.createElement('code'); code.textContent=attempt.request_id; request.append(code);
      $('rows').append(tr);
    }
    next = data.next_before; $('older').disabled = !next;
    $('empty').hidden = data.attempts.length > 0;
    $('notice').hidden = true; $('dot').className='ready';
    $('connection').textContent = data.storage === 'empty' ? 'Oczekiwanie na pierwsze wywołanie' : 'Połączono z historią';
    $('page-info').textContent = `Widoczne: ${data.attempts.length} · ${before ? 'starsza strona' : 'najnowsza strona'}`;
    $('updated').textContent = 'Odczyt: ' + new Date().toLocaleTimeString('pl-PL');
  } catch (error) {
    $('notice').hidden=false; $('notice').textContent='Odczyt nie powiódł się. Widoczne dane mogą być nieaktualne. ' + error.message;
    $('connection').textContent='Brak aktualnych danych'; $('dot').className=''; $('older').disabled=true;
  } finally { busy=false; }
}
$('filters').addEventListener('submit', event => {
  event.preventDefault(); if (busy) return;
  const params=new URLSearchParams();
  for(const [key,value] of new FormData(event.target)) if(value) params.set(key, ['since','until'].includes(key) ? new Date(value).toISOString() : value);
  applied=params; before=null; refresh();
});
$('clear-filters').addEventListener('click', () => { if(busy)return; $('filters').reset(); applied=new URLSearchParams(); before=null; refresh(); });
$('latest').addEventListener('click', () => { if(busy)return; before=null; refresh(); });
$('older').addEventListener('click', () => { if(busy||!next)return; before=next; refresh(); });
setInterval(() => { if($('auto').checked && !before && !document.hidden) refresh(); },5000);
refresh();
