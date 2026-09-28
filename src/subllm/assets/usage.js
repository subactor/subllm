'use strict';
const $ = id => document.getElementById(id);
let next = null, before = null, busy = false, applied = new URLSearchParams();
let currentVisibleAttempts = [];
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
function timeoutLimit(attempt) {
  const value = Number(attempt.request?.timeout_seconds);
  return Number.isFinite(value) && value > 0 ? value : null;
}
function latencySeverity(durationMs, limitSeconds) {
  if (!Number.isFinite(durationMs) || limitSeconds == null) return '';
  if (durationMs >= limitSeconds * 1000) return 'latency-exceeded';
  if (durationMs >= limitSeconds * 800) return 'latency-near-limit';
  return '';
}
function extractPlanfileInfo(attempt) {
  let content = '';
  if (attempt.request && Array.isArray(attempt.request.messages)) {
    for (const m of attempt.request.messages) content += ' ' + (m.content || '');
  } else if (typeof attempt.request === 'string') {
    content = attempt.request;
  }
  if (attempt.response && typeof attempt.response.content === 'string') {
    content += ' ' + attempt.response.content;
  }
  let ticketId = null;
  const plfMatch = content.match(/\b(PLF-[0-9]+)\b/i);
  if (plfMatch) {
    ticketId = plfMatch[1].toUpperCase();
  } else {
    const tktMatch = content.match(/\b(ticket-[0-9]+)\b/i);
    if (tktMatch) {
      ticketId = tktMatch[1].toLowerCase();
    } else {
      const ghMatch = content.match(/\b(GITHUB-[0-9]+)\b/i);
      if (ghMatch) ticketId = ghMatch[1].toUpperCase();
    }
  }
  if (!ticketId) return null;
  let project = null, repoShort = null;
  const cLower = content.toLowerCase();
  if (cLower.includes('src/koru') || cLower.includes('semcod/koru') || cLower.includes(' koru ')) {
    project = 'semcod/koru'; repoShort = 'koru';
  } else if (cLower.includes('src/nxdo') || cLower.includes('semcod/nxdo') || cLower.includes(' nxdo ')) {
    project = 'semcod/nxdo'; repoShort = 'nxdo';
  } else if (cLower.includes('src/prefact') || cLower.includes('semcod/prefact') || cLower.includes(' prefact ')) {
    project = 'semcod/prefact'; repoShort = 'prefact';
  } else if (cLower.includes('src/repatch') || cLower.includes('repatch/') || cLower.includes('semcod/repatch') || cLower.includes(' repatch ')) {
    project = 'semcod/repatch'; repoShort = 'repatch';
  } else if (cLower.includes('src/tagi') || cLower.includes('semcod/tagi') || cLower.includes(' tagi ')) {
    project = 'semcod/tagi'; repoShort = 'tagi';
  } else if (cLower.includes('maskservice/c2004') || cLower.includes('c2004') || cLower.includes('displaynet') || cLower.includes('stacknet')) {
    project = 'maskservice/c2004'; repoShort = 'c2004';
  } else if (cLower.includes('subactor') || cLower.includes('subllm')) {
    project = 'subactor/subllm'; repoShort = 'subllm';
  }
  let title = '';
  const titleMatch = content.match(/Title:\s*([^\n\r]+)/i);
  if (titleMatch) {
    title = titleMatch[1].trim();
  } else {
    const promptMatch = content.match(/Driven prompt:\s*code2llm reports `([^`]+)`/i);
    if (promptMatch) {
      title = promptMatch[1].trim();
    } else {
      const smellMatch = content.match(/Address code smell:\s*([^\n\r.]+)/i);
      if (smellMatch) title = 'Address code smell: ' + smellMatch[1].trim();
    }
  }
  const githubUrl = project ? `https://github.com/${project}/issues?q=${encodeURIComponent(ticketId)}` : null;
  return { ticketId, project, repoShort, title, githubUrl };
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
    currentVisibleAttempts = Array.isArray(data.attempts) ? data.attempts : [];
    $('rows').replaceChildren();
    for (const attempt of data.attempts) {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.title = 'Kliknij, aby wyświetlić prompt i odpowiedź';
      tr.addEventListener('click', () => showDetail(attempt, tr));
      cell(tr, new Date(attempt.timestamp).toLocaleString('pl-PL'));
      cell(tr, attempt.application, attempt.function);
      const planfileTd = cell(tr, '');
      const taskInfo = extractPlanfileInfo(attempt);
      if (taskInfo) {
        const badge = document.createElement('span');
        badge.className = 'ticket-badge';
        badge.textContent = taskInfo.ticketId;
        badge.title = `Filtruj po zadaniu ${taskInfo.ticketId}`;
        badge.addEventListener('click', (e) => {
          e.stopPropagation();
          $('search').value = taskInfo.ticketId;
          applied = new URLSearchParams({ search: taskInfo.ticketId });
          before = null;
          refresh();
        });
        planfileTd.append(badge);
        if (taskInfo.githubUrl) {
          const a = document.createElement('a');
          a.href = taskInfo.githubUrl;
          a.target = '_blank';
          a.rel = 'noopener';
          a.className = 'ticket-ext-link';
          a.title = `Otwórz na GitHub (${taskInfo.project || ''})`;
          a.innerHTML = '<svg class="ui-icon ui-icon-xs" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>';
          a.addEventListener('click', (e) => e.stopPropagation());
          planfileTd.append(a);
        }
        if (taskInfo.repoShort) {
          const proj = document.createElement('small');
          proj.className = 'project-tag';
          proj.textContent = taskInfo.repoShort;
          planfileTd.append(proj);
        }
      } else {
        planfileTd.textContent = '—';
      }
      cell(tr, attempt.provider, attempt.model);
      const td = cell(tr, ''); const badge = document.createElement('span');
      badge.className = 'badge' + (attempt.status === 'error' ? ' error' : '');
      badge.textContent = attempt.status === 'success' ? 'Sukces' : 'Błąd'; td.append(badge);
      if(attempt.diagnostic_code) { const small=document.createElement('small'); small.textContent=attempt.diagnostic_code; td.append(small); }
      const limit = timeoutLimit(attempt);
      const durationCell = cell(tr, number(attempt.duration_ms) + ' ms');
      durationCell.className = latencySeverity(Number(attempt.duration_ms), limit);
      cell(tr, limit == null ? '—' : number(limit) + ' s');
      cell(tr, `${number(attempt.input_tokens)} / ${number(attempt.output_tokens)}`);
      const request = cell(tr, ''); const code = document.createElement('code'); code.textContent=attempt.request_id; request.append(code);
      $('rows').append(tr);
    }
    next = data.next_before; $('older').disabled = !next;
    $('empty').hidden = data.attempts.length > 0;
    $('notice').hidden = true; $('dot').className='ready';
    $('connection').textContent = data.storage === 'empty' ? 'Oczekiwanie na pierwsze wywołanie' : (data.storage === 'postgres' ? 'Połączono z PostgreSQL' : 'Połączono z historią');
    const searchQ = applied.get('search');
    $('page-info').textContent = `Widoczne: ${data.attempts.length}${searchQ ? ` · Szukaj: "${searchQ}"` : ''} · ${before ? 'starsza strona' : 'najnowsza strona'}`;
    $('updated').textContent = 'Odczyt: ' + new Date().toLocaleTimeString('pl-PL');
  } catch (error) {
    $('notice').hidden=false; $('notice').textContent='Odczyt nie powiódł się. Widoczne dane mogą być nieaktualne. ' + error.message;
    $('connection').textContent='Brak aktualnych danych'; $('dot').className=''; $('older').disabled=true;
  } finally { busy=false; }
}
let currentSelectedAttempt = null;
function formatMessages(req) {
  if (!req) return 'Brak zarejestrowanego promptu (wywołanie bez przechwytywania payloadu).';
  if (Array.isArray(req.messages)) {
    return req.messages.map(m => `--- [${(m.role || 'user').toUpperCase()}] ---\n${m.content || ''}`).join('\n\n');
  }
  return typeof req === 'string' ? req : JSON.stringify(req, null, 2);
}
function formatResponse(resp) {
  if (!resp) return 'Brak zarejestrowanej odpowiedzi.';
  if (typeof resp.content === 'string') return resp.content;
  if (resp.choices && resp.choices[0]?.message?.content) return resp.choices[0].message.content;
  return typeof resp === 'string' ? resp : JSON.stringify(resp, null, 2);
}
function renderDetailPlanfile(attempt) {
  const taskInfo = extractPlanfileInfo(attempt);
  const planfileWrap = $('detail-planfile');
  if (taskInfo && planfileWrap) {
    planfileWrap.hidden = false;
    $('detail-planfile-id').textContent = taskInfo.ticketId;
    $('detail-planfile-project').textContent = taskInfo.project ? `Projekt: ${taskInfo.project}` : '';
    const ghLink = $('detail-planfile-gh');
    if (taskInfo.githubUrl) {
      ghLink.hidden = false;
      ghLink.href = taskInfo.githubUrl;
      ghLink.textContent = `Zobacz ${taskInfo.ticketId} na GitHub ↗`;
    } else {
      ghLink.hidden = true;
    }
    $('detail-planfile-title').textContent = taskInfo.title ? `Tytuł / cel: ${taskInfo.title}` : '';
    $('detail-planfile-cmd').textContent = `planfile ticket show ${taskInfo.ticketId}`;
  } else if (planfileWrap) {
    planfileWrap.hidden = true;
  }
}
function showDetail(attempt, tr) {
  currentSelectedAttempt = attempt;
  $('detail').hidden = false;
  $('detail-id').textContent = attempt.request_id || attempt.id;
  renderDetailPlanfile(attempt);
  $('detail-prompt').textContent = formatMessages(attempt.request);
  $('detail-response').textContent = formatResponse(attempt.response);
  const metaObj = {
    id: attempt.id,
    timestamp: attempt.timestamp,
    request_id: attempt.request_id,
    application: attempt.application,
    function: attempt.function,
    provider: attempt.provider,
    model: attempt.model,
    status: attempt.status,
    duration_ms: attempt.duration_ms,
    timeout_limit_seconds: attempt.request?.timeout_seconds ? `${attempt.request.timeout_seconds}s` : '—',
    tokens: { input: attempt.input_tokens, output: attempt.output_tokens },
    diagnostic_code: attempt.diagnostic_code
  };
  $('detail-meta').textContent = JSON.stringify(metaObj, null, 2);

  if ((!attempt.request || !attempt.response) && attempt.id) {
    fetch('/v1/usage/detail?id=' + encodeURIComponent(attempt.id))
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) {
          if (d.request) {
            attempt.request = d.request;
            $('detail-prompt').textContent = formatMessages(d.request);
            if (d.request.timeout_seconds) {
              metaObj.timeout_limit_seconds = `${d.request.timeout_seconds}s`;
              $('detail-meta').textContent = JSON.stringify(metaObj, null, 2);
            }
          }
          if (d.response) {
            attempt.response = d.response;
            $('detail-response').textContent = formatResponse(d.response);
          }
          renderDetailPlanfile(attempt);
        }
      })
      .catch(() => {});
  }

  for (const r of $('rows').children) r.classList.remove('selected');
  if (tr) tr.classList.add('selected');
  $('detail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
$('close-detail')?.addEventListener('click', () => {
  $('detail').hidden = true;
  for (const r of $('rows').children) r.classList.remove('selected');
});
$('copy-detail')?.addEventListener('click', () => {
  if (!currentSelectedAttempt) return;
  const payload = {
    prompt: $('detail-prompt').textContent,
    response: $('detail-response').textContent,
    meta: currentSelectedAttempt
  };
  navigator.clipboard.writeText(JSON.stringify(payload, null, 2))
    .then(() => alert('Skopiowano szczegóły do schowka'))
    .catch(() => {});
});
$('copy-table-tsv')?.addEventListener('click', () => {
  const rows = $('rows').querySelectorAll('tr');
  if (!rows || rows.length === 0) {
    alert('Brak danych w tabeli do skopiowania');
    return;
  }
  const headers = ['Czas', 'Aplikacja / funkcja', 'Zadanie (Planfile)', 'Dostawca / model', 'Wynik', 'Czas trwania', 'Tokeny wej. / wyj.', 'Żądanie'];
  const lines = [headers.join('\t')];
  for (const tr of rows) {
    const cols = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.replace(/[\t\r\n]+/g, ' ').trim());
    lines.push(cols.join('\t'));
  }
  navigator.clipboard.writeText(lines.join('\n'))
    .then(() => alert(`Skopiowano ${rows.length} wierszy tabeli (TSV) do schowka.`))
    .catch(e => alert('Błąd kopiowania: ' + e));
});
$('copy-table-all')?.addEventListener('click', async () => {
  if (!currentVisibleAttempts || currentVisibleAttempts.length === 0) {
    alert('Brak prób w tabeli do skopiowania');
    return;
  }
  const btn = $('copy-table-all');
  const originalHtml = btn.innerHTML;
  btn.innerHTML = '<svg class="ui-icon spinning" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9" stroke-dasharray="30" stroke-dashoffset="10"></circle></svg> <span>Pobieranie…</span>';
  btn.disabled = true;

  try {
    const exportData = [];
    for (const attempt of currentVisibleAttempts) {
      const item = {
        id: attempt.id,
        timestamp: attempt.timestamp,
        request_id: attempt.request_id,
        application: attempt.application,
        function: attempt.function,
        provider: attempt.provider,
        model: attempt.model,
        status: attempt.status,
        duration_ms: attempt.duration_ms,
        tokens: { input: attempt.input_tokens, output: attempt.output_tokens },
        diagnostic_code: attempt.diagnostic_code,
        task: extractPlanfileInfo(attempt),
        request: attempt.request || null,
        response: attempt.response || null
      };

      if ((!item.request || !item.response) && attempt.id) {
        try {
          const res = await fetch('/v1/usage/detail?id=' + encodeURIComponent(attempt.id));
          if (res.ok) {
            const detail = await res.json();
            if (detail) {
              if (detail.request) item.request = detail.request;
              if (detail.response) item.response = detail.response;
            }
          }
        } catch (_) {}
      }
      exportData.push(item);
    }

    await navigator.clipboard.writeText(JSON.stringify(exportData, null, 2));
    alert(`Skopiowano pełne dane diagnostyczne (${exportData.length} żądań z promptami i odpowiedziami) do schowka.`);
  } catch (err) {
    alert('Błąd eksportu do schowka: ' + err);
  } finally {
    btn.innerHTML = originalHtml;
    btn.disabled = false;
  }
});
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
