"use strict";
const $ = id => document.getElementById(id);
let credential = "", loading = false, detailText = "", detailVersion = 0;
function clearCopy() { detailText = ""; detailVersion++; $("copy-detail").disabled = true; $("copy-status").textContent = ""; }
$("day").value = new Date().toISOString().slice(0,10);
async function api(params) {
  const response = await fetch(`/v1/interactions?${params}`, {headers:{Authorization:`Bearer ${credential}`},cache:"no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data.data;
}
function cell(row, value, className) {
  const td=document.createElement("td"); td.textContent=value ?? "—";
  if(className) td.className=className; row.append(td); return td;
}
async function detail(day,id) {
  clearCopy();
  const version = detailVersion;
  try {
    const data=await api(new URLSearchParams({day,id}));
    if(version !== detailVersion || !credential) return;
    if(!data) throw new Error("Brak wpisu lub brak uprawnień.");
    detailText=JSON.stringify(data,null,2);
    $("copy-detail").disabled=false;
    $("detail").hidden=false;
    $("request").textContent=JSON.stringify(data.request,null,2);
    $("response").textContent=JSON.stringify(data.response,null,2);
    const {request,response,...metadata}=data;
    $("metadata").textContent=JSON.stringify(metadata,null,2);
    const d=data.diagnostic;
    $("diagnostic").textContent=d ? `${d.code} · ${d.meaning}. Następny krok: ${d.remediation} Przyczyna źródłowa: ${d.root_cause}` : "Brak zarejestrowanego błędu.";
    if(data.metadata?.error_detail) $("diagnostic").textContent += ` Szczegóły: ${data.metadata.error_detail}`;
    $("detail").scrollIntoView({behavior:"smooth",block:"start"});
  } catch(e) { $("notice").textContent=e.message; }
}
async function refresh() {
  if(!credential || loading) return;
  loading=true;
  try {
    const params=new URLSearchParams({day:$("day").value,limit:"100"});
    for(const field of ["kind","status"]) if($(field).value) params.set(field,$(field).value);
    const records=await api(params);
    $("rows").replaceChildren();
    for(const record of records) {
      const tr=document.createElement("tr");
      const date=cell(tr,""); const time=document.createElement("time");
      time.dateTime=record.started_at; time.textContent=record.started_at.replace("T"," ").replace("Z"," UTC"); date.append(time);
      cell(tr,record.caller); cell(tr,`${({llm:"LLM",llm_attempt:"Próba LLM",mcp:"MCP"})[record.kind] || record.kind} · ${record.direction === "server_to_client" ? "serwer → klient" : "klient → serwer"}`);
      cell(tr,record.metadata?.provider ? `${record.metadata.provider} / ${record.metadata.model}` : record.target);
      const status=cell(tr,""); const badge=document.createElement("span"); badge.className=`badge ${record.status}`; badge.textContent=record.status; status.append(badge);
      cell(tr,record.duration_ms == null ? "—" : `${record.duration_ms.toLocaleString()} ms`);
      const target=cell(tr,""); const link=document.createElement("a");
      link.href=`#${record.day}/${record.id}`;link.textContent=record.diagnostic?.code || "Żądanie i odpowiedź";
      target.append(link);$("rows").append(tr);
    }
    $("connection").textContent="Połączony · odświeżanie co 5 s";
    $("notice").textContent=records.length ? `${records.length} ostatnich wpisów z wybranego dnia UTC.` : "Brak wpisów dla tych filtrów.";
  } catch(e) { $("notice").textContent=e.message;$("connection").textContent="Błąd odczytu"; }
  finally { loading=false; }
}
function openHash(){const match=location.hash.match(/^#(\d{4}-\d{2}-\d{2})\/([a-f0-9]{32})$/);if(match && credential) detail(match[1],match[2]);}
$("connect").onclick=()=>{credential=$("credential").value;$("credential").value="";refresh();openHash();};
$("disconnect").onclick=()=>{clearCopy();credential="";$("rows").replaceChildren();$("detail").hidden=true;for(const id of ["request","response","metadata"])$(id).textContent="";$("connection").textContent="Rozłączony";};
$("refresh").onclick=refresh;$("close").onclick=()=>{clearCopy();$("detail").hidden=true;history.replaceState(null,"",location.pathname);};
for(const name of ["day","kind","status"])$(name).onchange=refresh;
window.addEventListener("hashchange",openHash);setInterval(refresh,5000);

$("copy-detail").onclick=async()=>{
  if(!detailText) return;
  const version=detailVersion;
  try {
    await navigator.clipboard.writeText(detailText);
    if(version===detailVersion) $("copy-status").textContent="Skopiowano całe wywołanie do schowka.";
  } catch {
    if(version===detailVersion) $("copy-status").textContent="Nie udało się skopiować. Zezwól przeglądarce na dostęp do schowka lub zaznacz i skopiuj tekst ręcznie.";
  }
};
