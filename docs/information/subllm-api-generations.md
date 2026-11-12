---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "subllm-api-generations",
  "kind": "information",
  "version": 2,
  "title": "Generacje API SubLLM i profile migracji",
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
    "https://pypi.org/project/subactor-subllm/1.4.2/",
    "repo://subactor/subllm/pyproject.toml",
    "repo://subactor/subllm/src/subllm/client_routes.py",
    "https://github.com/subactor/subllm/issues/20",
    "https://github.com/subactor/subllm/pull/216",
    "https://github.com/subactor/subllm/actions/runs/43282789586"
  ]
}
---

# Generacje API SubLLM

<!-- docs:section purpose -->
## Cel

Rozróżnić opublikowany pakiet, źródła Git i izolowany profil konsumenta. Wersja i zakres zależności nie dowodzą zgodności API.

<!-- docs:section scope -->
## Zakres

Publiczne API i wydawanie subactor/subllm. Profile konsumentów są wymaganiami migracji; dokument nie aktualizuje ich locków ani operatorowych instalacji.

<!-- docs:section evidence -->
## Dowody

Odczyt PyPI z 2026-11-12: najnowsze 1.4.2. Wheel `subactor_subllm-1.4.2-py3-none-any.whl`, SHA-256 `6ef26c9612a8d51d5c41a65d8ff2ab0e8fa6e8edae6ef68536786c1fdf66744a`. Zweryfikowano digest i AST bez wykonywania pobranego kodu. Jego `complete()` ma application, function, messages, timeout_seconds, request_id, environ, credentials.

Baza Git wskazana w metadanych ma 1.14.0 zarówno w pyproject.toml, jak i VERSION. Synchronizację tych pól dostarczył ticket-206; S1 jest scalone w [PR #216](https://github.com/subactor/subllm/pull/216). Zgodność pól wersji nie zamyka luki PyPI/API.

<!-- docs:section content -->
## Macierz i migracja

| Możliwość | PyPI 1.4.2 | Git 1.14.0 w badanej bazie |
|---|---|---|
| Podstawowe complete() | Dostępne | Dostępne |
| quality_gate / quality_schema | Brak w sygnaturze | Dostępne |
| model / response_format / cwd | Brak w sygnaturze | Dostępne |
| Per-call generation_limits | Brak | Brak; S3 |
| Publiczny immutable audit receipt | Brak wymaganego kontraktu | Brak; S4 |
| Exact-request completion cache | Nie kwalifikowano | Propozycja S5 |
| Publiczny iterator zdarzeń generacji | Nie kwalifikowano | Propozycja S6 |

| Profil | Zależność i granica |
|---|---|
| Scanner optional | Zachować zgodny lock narzędzia; wymagać tylko API rzeczywiście używanego przez scanner. |
| Worker | Osobny interpreter i zweryfikowany artefakt z wymaganym API oraz ograniczeniami HTTP. Nie nadpisywać wspólnego środowiska scannera. |
| Publikacja | Istniejący tag-bound OIDC workflow i weryfikator artefaktów; kwalifikacja przeszła, bramka dostępności zależności pozostaje otwarta. |

Dostarczony profil Forge rozdziela lock scannera i worker z lokalnym wheel 1.14.0+forge.1. Deklaracja code2logic `subactor-subllm>=0.1.0` nie wyklucza 1.14; problem dotyczy wybranego locka i wymaganego API. Nie usuwać lokalnej poprawki przed kwalifikacją upstream.

<!-- docs:section limitations -->
## Ograniczenia

Finalne źródło `986a99b58ad19152c1fdad76c7eed3711386e754` przeszło [kwalifikację istniejącym workflow, run 43282789586](https://github.com/subactor/subllm/actions/runs/43282789586): build wheel/sdist, metadane i routing pakietu. Pobrany artefakt bez przebudowy zainstalowano offline w pustych venv Python 3.11/3.12. Pip check oraz **90 testów na każdym interpreterze PASS**, w tym publiczne complete() z rzeczywistym subprocess, lokalnym HTTP i odczytem native archive. Sprawdzono import z site-packages i zgodność zainstalowanych modułów z wheel.

| Artefakt 1.14.0 | SHA-256 |
|---|---|
| subactor_subllm-1.14.0-py3-none-any.whl | `5e51c0434cbdbcecf7439ab5cd7ca36b98c33638714ef83cfb6df9fffa520025` |
| subactor_subllm-1.14.0.tar.gz | `b14507eaf51277ea7638ffd93c50e3fa57fa175756d9be534d6bcb95f7f2bad0` |

Nowego release PyPI nie opublikowano. Run wykonano w trybie dry-run; upload OIDC i GitHub Release pominięto zgodnie z trybem. Weryfikator indeksu zgłasza PROCACHE_INDEX_UNAVAILABLE: subactor-procache==0.1.0 zwraca HTTP 404. Istniejący ticket publikacji zależności wymaga niezależnego potwierdzenia Trusted Publisher; nie obchodzono tej bramki. Odbiór migracji scannera i równoległych profili pozostaje NOT_RUN.

<!-- docs:section next_actions -->
## Następne kroki

Zapewnić zweryfikowaną publikację wymaganej zależności, ponowić preflight indeksu i uruchomić chronione wydanie. Porównać hashe artefaktów budowanych i opublikowanych; dopiero po odbiorze API zmieniać profile konsumentów. Śledzenie: [S2 #20](https://github.com/subactor/subllm/issues/20).
