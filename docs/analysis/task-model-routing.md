---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "task-model-routing",
  "kind": "analysis",
  "version": 1,
  "title": "Dobór modeli do zadań i bezpośredni ZAI Flash",
  "status": "accepted",
  "owner": "subactor/subllm",
  "scope": "repository",
  "created": "2026-10-30",
  "updated": "2026-10-30",
  "review_after": "2026-11-06",
  "source_revision": "664734a09a52dbc2c41902ec372aa3f7999ea08e",
  "affected_repositories": ["subactor/subllm"],
  "evidence": [
    "receipt:sha256:e59e3c0c3850d6090cf24f8b6466b46eb204d49c6b17768e5e07f1562b51829c",
    "receipt:sha256:f763d1265a263d1e47b2f89852e657162a3ac0e8f4becdfa3a1b544df4363490",
    "https://docs.z.ai/guides/vlm/glm-5.3-flash",
    "https://docs.z.ai/devpack/overview"
  ]
}
---

# Dobór modeli do zadań i bezpośredni ZAI Flash

<!-- docs:section question -->
## Question

Czy ograniczone zadania korzystają z odpowiedniego modelu i czy wystarcza bezpośredni `zai/glm-5.3-flash`?

<!-- docs:section scope -->
## Scope

Audyt SubLLM na rewizji wskazanej w metadanych: konfiguracja tras, resolver, wykonawca i dziennik prób. Zmiana aplikacyjna: ticket-177. Ten dokument nie potwierdza wdrożenia tej zmiany w konsumentach.

<!-- docs:section method -->
## Method

Odczyt metadanych prób z 30.10.2026, 05:30–10:15 UTC, dla czterech aplikacji wskazanych przez operatora. To szersze okno niż tabela w rozmowie. Porównanie obu modeli przez ten sam klient i endpoint Coding Plan, z `reasoning_effort=low`, JSON mode i budżetem 30 s: wybór identyfikatora zadania oraz dwie komendy Koru. Sprawdzano treść pól, nie tylko poprawność JSON; żadnej zwróconej komendy nie wykonano. Prywatne obserwacje są związane skrótami w metadanych i sidecarze.

<!-- docs:section evidence -->
## Evidence

| Obserwacja | Wynik |
| --- | --- |
| Koru, pełny ZAI 5.3 | 13 sukcesów, średnio 23,00 s; 11 błędów unavailable, średnio 30,28 s; 8 rate-limit |
| Supervisor, pełny ZAI 5.3 | 5 sukcesów, średnio 22,02 s; 44 rate-limit |
| Proxy completion, pełny ZAI 5.3 | 3 sukcesy, średnio 21,52 s |
| Sparowane canary Flash / pełny 5.3 | oba 3/3 poprawne; średnio 5,281 / 4,824 s |
| Tokeny trzech canary Flash / pełny 5.3 | wejście 216 / 216; wyjście 438 / 339, wraz z reasoning |

Oddzielna próba przez działający proxy zwróciła poprawne `ids=[T1]` w 3,66 s; nagłówki potwierdziły dostawcę `zai` i model `glm-5.3-flash`.

<!-- docs:section facts -->
## Facts

Wspólne `_DEFAULT` oraz `_KORU` preferują pełny 5.3 przed Flash. Samo ustawienie `providers.zai.default_model` nie zmienia kandydatów mających jawny model. Supervisor miał już niskie reasoning; pozostałe badane trasy nie ograniczały go. Nie ma tu oceny trudności promptu ani miernika jakości wyniku.

Wykonawca pomija dalsze modele dostawcy po błędzie `provider_level`; dotyczy to także timeoutu i 429. Pełny model pozostaje osiągalnym fallbackiem po błędzie dotyczącym pojedynczego modelu, np. 404. Sama obecność Flash dalej na liście nie zapewnia wywołania go po timeoutcie pełnego modelu.

[Dokumentacja ZAI](https://docs.z.ai/guides/vlm/glm-5.3-flash) potwierdza bezpośredni identyfikator i dostępność w Coding Plan. Reasoning pozostaje włączone. [Współczynniki Coding Plan](https://docs.z.ai/devpack/overview) wynoszą dla wejścia/wyjścia 2,3/8 dla Flash oraz 6,9/24 dla pełnego 5.3. Przy liczbie tokenów z canary daje to 0,40008 wobec 0,96264 punktu przed wspólną zniżką off-peak: około 58% mniej, a nie gwarantowane 67% mniej na każde zadanie.

<!-- docs:section hypotheses -->
## Hypotheses

Niski wysiłek rozumowania powinien ograniczyć zbędną generację przy prostych konwersjach. Zbieżność błędów z 30 s sugeruje wyczerpanie budżetu wywołującego; sam kod unavailable nie dowodzi awarii ZAI. Należy obserwować wynik po stronie konsumenta.

<!-- docs:section limitations -->
## Limitations

Trzy małe przykłady nie mierzą jakości produkcyjnej, percentyli ani oceny Supervisora z wejściem około 32 tys. tokenów. Flash nie był w tej próbie szybszy średnio. Sukces transportu w dzienniku nie potwierdza poprawności zadania. Próby Ollama miały inne rozmiary kontekstu; ich czasów nie traktujemy jako porównania tych samych wejść. Błędy OpenRouter Flash nie opisują dostępności bezpośredniego ZAI Flash.

<!-- docs:section recommendations -->
## Recommendations

Preferować bezpośredni Flash z low reasoning dla `todo2code/semantic`, `supervisor/assessment`, obu aliasów Koru NL→DSL i `subactor-proxy/completion`. Zachować pełny 5.3 dla planowania, kodowania, napraw i review. Nadal respektować jawny model, kolejność dostawców, walidację konsumenta oraz cooldown konta. Kandydat ticket-177 przechodzi 218 testów obejmujących resolver i wykonawcę, lint i gate governance. Publikacja źródła, niezależna walidacja i wdrożenie to odrębne etapy; po wdrożeniu porównać poprawność, odsetek timeoutów i punkty na zadanie. W razie regresji przywrócić poprzednią politykę tras.
