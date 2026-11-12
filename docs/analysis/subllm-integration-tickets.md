---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "subllm-integration-tickets",
  "kind": "analysis",
  "version": 1,
  "title": "Realizacja zadań integracyjnych SubLLM S1–S7",
  "status": "proposed",
  "owner": "subactor/subllm",
  "scope": "repository",
  "created": "2026-11-12",
  "updated": "2026-11-12",
  "review_after": "2026-12-12",
  "source_revision": "ec62460de362dc19e407a7dce0f3e9c720850f14",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "https://github.com/subactor/subllm/issues/208",
    "https://github.com/subactor/subllm/issues/20",
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

Wyłącznie upstream subactor/subllm. S1 jest kandydatem ticket-204 w roboczym [PR #216](https://github.com/subactor/subllm/pull/216); ticket-207 dostarcza macierz API i ten raport. Oryginalny plik wejściowy zachowano. Nie aktywowano zmian w usługach operatora ani konsumentach.

<!-- docs:section method -->
## Metoda

Sprawdzono obecne źródła, PyPI i archiwum projektu dostarczające pierwotną łatę. Użyto semcod/search oraz istniejącego HOME native_http zamiast kopiować transport. Native allocator 0.20.147 wydzielił zakresy przy zachowaniu cudzej zmiany resolver.py i istniejących worktree. Metadane, własność, testy i publikacja pozostają oddzielnymi dowodami.

<!-- docs:section evidence -->
## Dowody

| Zadanie | Zgłoszenie | Bieżący wynik |
|---|---|---|
| S1 HTTP | [#208](https://github.com/subactor/subllm/issues/208) | Roboczy PR #216; 88 testów transportu PASS, Ruff i governance PASS; odbiór klientów otwarty. |
| S2 release | [#20](https://github.com/subactor/subllm/issues/20) | Kandydat: wheel/sdist, offline venv, pip check i testy na Pythonie 3.11/3.12 PASS; [macierz migracji](../information/subllm-api-generations.md); brak nowego release. |
| S3 budżet | [#209](https://github.com/subactor/subllm/issues/209) | Backlog; brak publicznego generation_limits. |
| S4 receipt | [#210](https://github.com/subactor/subllm/issues/210) | Backlog; zachować obecny native archive/journal. |
| S5 cache | [#211](https://github.com/subactor/subllm/issues/211) | Propozycja opt-in; bez deklaracji wdrożenia. |
| S6 stream | [#212](https://github.com/subactor/subllm/issues/212) | Propozycja iteratora i terminal receipt. |
| S7 snapshot | [#213](https://github.com/subactor/subllm/issues/213) | Przegląd źródła; fault test i implementacja niewykonane. |

<!-- docs:section facts -->
## Fakty

Kandydat S1 blokuje redirect/proxy, ogranicza body do 1 MB dla OpenAI-worker i 4 MB dla native HTTP, odrzuca JSON głębszy niż 64 poziomy oraz wymaga skończonych timeoutów obsługiwanych przez platformę. Nie ponawia HTTP po TypeError. Fixture TLS potwierdza jeden native attempt i jeden wpis usage, bez ruchu do redirect targetu.

Head PR #216 `c5fd4dfc9553797dd3a988e0efc1bec11739c865` zawiera obecną bazę main. Zestaw transportu i klientów/usage uruchomiony przez przypięty Wellman 0.23.0: 179 PASS i 3 FAIL. Przypadek czasowy Cursor przeszedł wcześniej osobno i na bazie. Dwa deterministyczne błędy dotyczą starych sygnatur atrap w tests/test_client.py, zarezerwowanym przez ticket-199. Minimalna poprawka atrap przechodzi oba testy w izolowanej kopii; asercji nie osłabiono, pliku rezerwowanego nie zmieniono.

Wheel z commitu `8e0ca7720f8789f5add793be164468f925b9ca91` zaliczył po 87 testów transportu i dodatkowy fixture publicznego complete() na Pythonie 3.11 i 3.12. Fixture nie zastępuje workera atrapą: lokalne HTTP uruchamia rzeczywisty subprocess, a zapisany wynik jest odczytywany z native archive. Artefakty i ich hashe są opisane w macierzy API.

<!-- docs:section hypotheses -->
## Hipotezy

Udany test izolowany sugeruje zależność przypadku Cursor od czasu startu procesu; nie stanowi rozstrzygnięcia przyczyny ani powodu do usunięcia testu.

<!-- docs:section limitations -->
## Ograniczenia

Pełny odbiór S1 i niezależna publikacja pozostają otwarte. Aktualny kontroler dopuszcza przejęcie bezczynnych zadań, lecz klasyfikuje ticket-199 jako INVALID_LEASE: historyczny repositoryRef nie spełnia kontraktu kanonicznego. Wymaga to naprawy przez kontroler; samego lease nie nadpisano. Lokalny PASS, utworzenie issue i zmiana statusu dokumentu nie oznaczają merge, wydania PyPI ani realizacji S3–S7. Nie wykonywano płatnych wywołań providerów.

<!-- docs:section recommendations -->
## Następny krok

Uzgodnić testowe fixture z właścicielem ticket-199, zachowując cel wcześniejszej pracy, oraz wykonać oryginalny zestaw testów i chronioną walidację dokładnego head/base. Następnie opublikować kwalifikowany release przez istniejącą ścieżkę S2. Realizować S3–S7 z natywnym audytem, budżetem wszystkich prób i wymaganymi testami fault, bez nowych wrapperów omijających politykę.
