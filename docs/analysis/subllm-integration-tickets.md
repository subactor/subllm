---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "subllm-integration-tickets",
  "kind": "analysis",
  "version": 2,
  "title": "Realizacja zadań integracyjnych SubLLM S1–S7",
  "status": "proposed",
  "owner": "subactor/subllm",
  "scope": "repository",
  "created": "2026-11-12",
  "updated": "2026-11-12",
  "review_after": "2026-12-12",
  "source_revision": "986a99b58ad19152c1fdad76c7eed3711386e754",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "https://github.com/subactor/subllm/issues/208",
    "https://github.com/subactor/subllm/issues/20",
    "https://github.com/subactor/subllm/pull/216",
    "https://github.com/subactor/subllm/actions/runs/43282789586",
    "repo://subactor/subllm/docs/information/subllm-api-generations.md"
  ]
}
---

# Realizacja zadań SubLLM

<!-- docs:section question -->
## Pytanie

Które zadania z dostarczonego SUBLLM_TICKETS.md mają dowody wykonania, a które wymagają dalszej implementacji lub uzgodnienia własności?

<!-- docs:section scope -->
## Zakres

Upstream subactor/subllm po scaleniu [PR #216](https://github.com/subactor/subllm/pull/216). Oryginalny plik wejściowy zachowano. Raport nie zmienia instalacji operatora ani locków konsumentów.

<!-- docs:section method -->
## Metoda

Sprawdzono źródła, PyPI i dostarczone archiwum. Wyszukiwanie semcod/search wskazało istniejący HOME native_http do ponownego użycia. Natywny allocator rozdzielił zakresy; zachowano cudzą zmianę resolver.py. Odbiór obejmuje niezależne CI, chroniony merge, kwalifikację dystrybucji i kontrolę indeksu PyPI.

<!-- docs:section evidence -->
## Dowody

| Zadanie | Zgłoszenie | Bieżący wynik |
|---|---|---|
| S1 HTTP | [#208](https://github.com/subactor/subllm/issues/208) | Scalony PR #216; issue zamknięte. Fixture gateway/client scalone w [#219](https://github.com/subactor/subllm/pull/219) i [#220](https://github.com/subactor/subllm/pull/220). |
| S2 release | [#20](https://github.com/subactor/subllm/issues/20) | Finalne wheel/sdist zakwalifikowane; offline i pip check PASS. Publikacja oczekuje na zależność PyPI; [macierz migracji](../information/subllm-api-generations.md). |
| S3 budżet | [#209](https://github.com/subactor/subllm/issues/209) | Backlog; brak publicznego generation_limits. |
| S4 receipt | [#210](https://github.com/subactor/subllm/issues/210) | Backlog; zachować obecny native archive/journal. |
| S5 cache | [#211](https://github.com/subactor/subllm/issues/211) | Propozycja opt-in; bez deklaracji wdrożenia. |
| S6 stream | [#212](https://github.com/subactor/subllm/issues/212) | Propozycja iteratora i terminal receipt. |
| S7 snapshot | [#213](https://github.com/subactor/subllm/issues/213) | Fault test potwierdził przeżycie workera po śmierci rodzica; implementacja pozostaje otwarta. |

<!-- docs:section facts -->
## Fakty

S1 blokuje redirect/proxy, ogranicza body do 1 MB dla OpenAI-worker i 4 MB dla native HTTP, odrzuca JSON głębszy niż 64 poziomy i wymaga skończonych timeoutów. Nie ponawia HTTP po TypeError. Lokalny TLS potwierdza pojedynczy attempt/usage bez ruchu do redirect targetu.

Merge `986a99b58ad19152c1fdad76c7eed3711386e754` zaakceptował niezależny Validator. Pełny zestaw CI: **1408 PASS, 2 SKIP na każdym Pythonie 3.11, 3.12 i 3.13**; sześć lokalnych bramek OneDev PASS. Lokalnie 182 testy transportu/klientów/usage PASS. Poprawki sygnatur fixture zachowują asercje; stary konflikt rezerwacji ticket-199 rozwiązano za zgodą użytkownika i przez kontroler przejęcia.

[Istniejący workflow](https://github.com/subactor/subllm/actions/runs/43282789586) zakwalifikował dystrybucje dokładnie z tego merge. Instalacja offline w pustych venv, pip check i **90 testów na każdym Pythonie 3.11/3.12** przeszły dla pobranego wheel. Publiczne complete() uruchamia rzeczywisty subprocess i lokalne HTTP, a odpowiedź jest odczytywana z native archive. Hashe zapisano w macierzy API.

[Fault test S7](https://github.com/subactor/subllm/issues/213#issuecomment-6831094844) po SIGTERM i SIGKILL rodzica wykazał działający subprocess po 200 ms. Każdą własną grupę procesów zakończono po obserwacji; nie dowodzi to osierocenia bez limitu czasu.

<!-- docs:section hypotheses -->
## Hipotezy

Migawka rozwiązanej polityki i jawne powiązanie życia dziecka z rodzicem wymagają implementacji oraz osobnej kwalifikacji; fault test nie dowodzi gotowego rozwiązania.

<!-- docs:section limitations -->
## Ograniczenia

Nowego wydania PyPI nie opublikowano: wymagane subactor-procache==0.1.0 nie występuje w indeksie (HTTP 404). Test wyścigu polityki i odbiór równoległych profili konsumentów: NOT_RUN. S3–S7 pozostają otwarte. Nie wykonywano płatnych wywołań providerów.

<!-- docs:section recommendations -->
## Następny krok

Spełnić warunek dostępności zależności i niezależnej weryfikacji jej Trusted Publisher, następnie użyć istniejącej ścieżki S2 i porównać opublikowane hashe. Kontynuować S3–S7 z natywnym audytem, budżetem wszystkich prób i testami fault.
