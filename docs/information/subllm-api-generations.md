---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "subllm-api-generations",
  "kind": "information",
  "version": 1,
  "title": "Generacje API SubLLM i profile migracji",
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
    "https://pypi.org/project/subactor-subllm/1.4.2/",
    "repo://subactor/subllm/pyproject.toml",
    "repo://subactor/subllm/src/subllm/client_routes.py",
    "https://github.com/subactor/subllm/issues/20"
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

Baza Git wskazana w metadanych ma 1.14.0 zarówno w pyproject.toml, jak i VERSION. Pierwszy audyt bazy `89f81f99793120c45caa49bcaf632810541b85cb` wykrył VERSION 1.13.0; synchronizację dostarczył istniejący ticket-206. Zgodność tych pól nie zamyka luki PyPI/API.

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
| Publikacja | Przejść przez istniejący tag-bound OIDC workflow i weryfikator artefaktów, po niezależnym review poprawki S1. |

Dostarczony profil Forge rozdziela lock scannera i worker z lokalnym wheel 1.14.0+forge.1. Deklaracja code2logic `subactor-subllm>=0.1.0` nie wyklucza 1.14; problem dotyczy wybranego locka i wymaganego API. Nie usuwać lokalnej poprawki przed kwalifikacją upstream.

<!-- docs:section limitations -->
## Ograniczenia

Kandydat S1 z commitu `8e0ca7720f8789f5add793be164468f925b9ca91` przeszedł build wheel/sdist, kontrolę metadanych i routingu istniejącym weryfikatorem pakietu, instalację offline w pustych venv oraz pip check na Pythonie 3.11/3.12. Każdy interpreter zaliczył 87 testów transportu oraz dodatkowy fixture publicznego complete() z prawdziwym lokalnym HTTP, subprocess i odczytem zapisanej odpowiedzi z archiwum. SHA-256 wheel: `25449a133fffaf49fafa188a96d0f1531fcd0b182a0d1624279f08fb12aded6c`; sdist: `8f6ea4d2c7977d7acb75479a69669ce2fd0968d067f3d48f74c1fa26d815cdc9`.

Nowy release PyPI nie został opublikowany. Sam workflow nie dowodzi konfiguracji Trusted Publisher, uruchomienia ani zgodności opublikowanego artefaktu. Kandydat S1 nie zawiera jeszcze zmian z późniejszego main; po integracji wymaga ponownej kwalifikacji.

<!-- docs:section next_actions -->
## Następne kroki

Dokończyć [S1 w PR #216](https://github.com/subactor/subllm/pull/216) i kompatybilne fixture, następnie ponowić kwalifikację finalnego źródła. Porównać hash artefaktu budowanego i opublikowanego; dopiero wtedy zmieniać profile konsumentów. Śledzenie: [S2 #20](https://github.com/subactor/subllm/issues/20).
