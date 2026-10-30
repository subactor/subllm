---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "task-model-routing",
  "kind": "analysis",
  "version": 2,
  "title": "Dobór modeli do zadań i bramka jakości odpowiedzi",
  "status": "accepted",
  "owner": "subactor/subllm",
  "scope": "repository",
  "created": "2026-10-30",
  "updated": "2026-10-30",
  "review_after": "2026-11-06",
  "source_revision": "024b4fe5dd8bfd474ef09f3f7f663c59fa7a9bd1",
  "affected_repositories": ["subactor/subllm"],
  "evidence": [
    "receipt:sha256:e59e3c0c3850d6090cf24f8b6466b46eb204d49c6b17768e5e07f1562b51829c",
    "receipt:sha256:f763d1265a263d1e47b2f89852e657162a3ac0e8f4becdfa3a1b544df4363490",
    "https://docs.z.ai/guides/vlm/glm-5.3-flash",
    "https://docs.z.ai/devpack/overview",
    "https://github.com/subactor/subllm/pull/183"
  ]
}
---

# Dobór modeli do zadań i bramka jakości odpowiedzi

<!-- docs:section question -->
## Question

Czy ograniczone zadania korzystają z odpowiedniego modelu i czy wystarcza bezpośredni `zai/glm-5.3-flash`?

<!-- docs:section scope -->
## Scope

Audyt konfiguracji tras, resolvera, wykonawcy i dziennika prób SubLLM. Historyczne pomiary dotyczą ticket-177; bieżąca polityka i bramka jakości dotyczą zweryfikowanej rewizji ticket-179 z metadanych. PR #183 został niezależnie zatwierdzony i scalony jako `2a1e703221fe9b4bc66094203fb010db13e2b5c2`. Nie potwierdza to przeładowania wszystkich działających konsumentów ani przekazania przez nich walidatorów semantycznych.

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

Pełny `glm-5.3` jest ponownie pierwszy w badanych trasach ograniczonych: `todo2code/semantic`, `supervisor/assessment`, obu aliasach Koru NL→DSL i `subactor-proxy/completion`; Flash pozostaje dalej na liście. Oba modele używają tam `reasoning_effort=low`. Złożone role planowania, kodowania, napraw i review zachowują wcześniejsze ustawienia. Samo ustawienie `providers.zai.default_model` nie zmienia kandydatów mających jawny model. Polityka nie zawiera automatycznej oceny trudności promptu.

Wykonawca pomija dalsze modele dostawcy po błędzie `provider_level`; dotyczy to także timeoutu i 429. Flash pozostaje osiągalnym fallbackiem po odrzuceniu dotyczącym pojedynczego modelu, np. 404 lub bramce jakości. Sama obecność Flash dalej na liście nie zapewnia wywołania go po timeoutcie pełnego modelu.

Bramka wykonuje się przed uznaniem próby za sukces. Odrzuca pustą treść, odpowiedź oznaczoną jako ucięta lub filtrowana oraz niepoprawny JSON dla zadeklarowanych formatów JSON. Kosztowne odrzucone odpowiedzi zachowują zużycie tokenów w dzienniku, ze statusem błędu i kodem `SUBLLM-RESPONSE-QUALITY-REJECTED`.

Opcjonalny `complete(..., quality_gate=predicate)` przekazuje odpowiedź walidatorowi należącemu do zadania. Tylko literalne `True` akceptuje wynik; odrzucenie próbuje kolejnego dopuszczonego modelu. Dotyczy to także tras adaptacyjnych. Odrzucenie semantyczne jednego zadania nie zapisuje globalnej niedostępności tego modelu. Wyjątek w walidatorze przerywa żądanie jako `SUBLLM-QUALITY-VALIDATOR-ERROR`, bez opłacania kolejnych modeli. Jawny wybór modelu nadal ogranicza dostępne trasy.

Przykładowe kryterium dla wyboru zadań to lista istniejących identyfikatorów, dla DSL — poprawna komenda zgodna z gramatyką i dozwolonymi operacjami. Sam poprawny JSON nie potwierdza sensu odpowiedzi. Deklaracja `json_schema` sprawdza tutaj składnię JSON; pełną zgodność ze schematem trzeba dostarczyć w predykacie zadania.

[Dokumentacja ZAI](https://docs.z.ai/guides/vlm/glm-5.3-flash) potwierdza bezpośredni identyfikator i dostępność w Coding Plan. Reasoning pozostaje włączone. [Współczynniki Coding Plan](https://docs.z.ai/devpack/overview) wynoszą dla wejścia/wyjścia 2,3/8 dla Flash oraz 6,9/24 dla pełnego 5.3. Przy liczbie tokenów z canary daje to 0,40008 wobec 0,96264 punktu przed wspólną zniżką off-peak: około 58% mniej, a nie gwarantowane 67% mniej na każde zadanie.

<!-- docs:section hypotheses -->
## Hypotheses

Niski wysiłek rozumowania powinien ograniczyć zbędną generację przy prostych konwersjach. Zbieżność błędów z 30 s sugeruje wyczerpanie budżetu wywołującego; sam kod unavailable nie dowodzi awarii ZAI. Należy obserwować wynik po stronie konsumenta.

<!-- docs:section limitations -->
## Limitations

Trzy małe przykłady nie wykazały różnicy jakości między modelami, ale nie mierzą jakości produkcyjnej, percentyli ani oceny Supervisora z wejściem około 32 tys. tokenów. Bramka biblioteki nie ocenia dowolnego tekstu semantycznie; skuteczność domenowa wymaga dostarczonych kryteriów i reprezentatywnych testów konsumenta. Flash nie był w tej próbie szybszy średnio. Sukces transportu w dzienniku nie potwierdza poprawności zadania. Próby Ollama miały inne rozmiary kontekstu; ich czasów nie traktujemy jako porównania tych samych wejść. Błędy OpenRouter Flash nie opisują dostępności bezpośredniego ZAI Flash.

<!-- docs:section recommendations -->
## Recommendations

Utrzymać pełny GLM‑5.3 jako domyślny model do czasu uzyskania reprezentatywnych wyników jakości dla danego zadania. Małe canary uzasadniają dalsze porównania kosztu Flash, ale nie dowodzą jego równoważności produkcyjnej ani przewagi szybkości. Ewentualne przełączenie powinno zależeć od poprawności wyników, timeoutów i kosztu na zaakceptowane zadanie.

Konsumenci powinni przekazywać deklarowany format oraz własny predykat akceptacji do centralnego wykonawcy. Weryfikować regresje na tych samych wejściach i kryteriach, z kontrolą zużycia odrzuconych prób. PR #183 ma niezależne potwierdzenie wymaganych kontroli CI; lokalnie przechodziły 238 testy routingu/klienta, a następnie 54 testy jakości, tras zadań i adaptacji po dodatkowych regresjach. Nie zastępuje to replayu dużych kontekstów Supervisora ani obserwacji działających konsumentów.
