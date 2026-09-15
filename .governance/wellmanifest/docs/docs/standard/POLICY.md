# Standard informacji i planów refaktoryzacji — wellmanifest/docs 0.5.0

Słowa MUSI, NIE WOLNO i POWINIEN określają odpowiednio wymaganie, zakaz i zalecenie. `policy.json` jest kanonicznym katalogiem ścieżek, metadanych i sekcji; ten dokument opisuje ich znaczenie. HOME standardu: wellmanifest; projekty Subactor ADOPT ten pakiet i pozostają właścicielami swojego kodu oraz informacji.

Nowe krótkie dokumenty POWINNY używać profilu kompaktowego v2 (DOCS-009).
Reguły metadanych, ścieżek i sekcji DOCS-002/004/005 opisują format v1;
dla v2 zastępuje je DOCS-009. Zasady właściciela, dowodów i uprawnień są wspólne.

## DOCS-010 — Opcjonalny kontrakt zmiany

Profil `wellmanifest.docs/change/v1` reużywa gramatykę i zamknięty Policy IR
`wellmanifest.policy/v1`. Nie tworzy nowego języka. W kompaktowym FEATURE
lub BUGFIX można umieścić jeden pełny blok z etykietą dokładnie `dsl`.
Każdy taki blok podlega walidacji; nieznanej składni NIE WOLNO ignorować.
Ilustracje poza kontraktem oznaczać `text`. Zewnętrzne ogrodzenie kodu
zachowuje zagnieżdżony przykład jako tekst. Dokumenty v1 nie są reinterpretowane.

Kontrakt MUSI deklarować `DOCUMENT DOCS_FEATURE` albo `DOCS_BUGFIX`,
`VERSION` równą wersji metadanych, `MODE STRICT` oraz
`POLICY "wellmanifest.docs/change/v1"`. Obowiązkowe wiązania:

- `SUBJECT = "..."`: dokładny identyfikator dokumentu.
- `COMPATIBILITY = "..."`: wpływ na zgodność lub uzasadniony brak wpływu.
- `INPUTS IN ["NAME", ...]`: 1–16 unikalnych nazw obserwacji UPPER_SNAKE_CASE.
- W BUGFIX dodatkowo `REPRODUCTION`, `BEFORE` i `AFTER`: niepuste opisy.

Innych wiązań, środowiska, sekretów, stanów, przejść i globalnych asercji
NIE WOLNO dodawać. Teksty mają najwyżej 400 znaków. Kontrakt zawiera 1–12
unikalnych `RULE AC-NN TYPE REQUIRED`, każda z warunkiem `WHEN`,
co najmniej jedną `ASSERT` i odwołaniem `DO VALIDATE "tests/file.py"`.
Każda asercja odwołuje się do zadeklarowanej obserwacji; same stałe nie
stanowią kryterium. Dozwolone są wyrażenia skalarne i listy Policy IR,
bez sekwencji i nierozwiązanych placeholderów. Nazwy obserwacji są jawne;
checker nie pobiera ich wartości z procesu ani repozytorium.

`DO VALIDATE` jest odwołaniem, nie poleceniem. Cel MUSI być śledzonym plikiem
wewnątrz katalogu `tests` lub `test` w tym repozytorium, bez dowiązań,
wyjścia poza root, fragmentów i selektorów typu `::test_name`. Inne dyrektywy,
warunkowe dyrektywy, `FORBID` i `NEXT` nie należą do tego profilu.

Blok ma limit 8 KiB; nadal obowiązują całkowite limity dokumentu v2.
Checker potwierdza strukturę i referencje, NIE wyniki testów, prawdziwość
obserwacji ani kompletność pokrycia. Nie ocenia asercji i niczego nie wykonuje.
Ticket i `intent.json` pozostają źródłem zakresu realizacji; review, wykonanie
i merge zachowują odrębne granice uprawnień.

### Przypięcie i uruchomienie parsera

Zaufany operator/CI dostarcza `--policy-dsl-root`, wskazujący checkout
z rewizji zapisanej w `policy-dsl.lock.json`. Standard sprawdza SHA-256
parsera, EBNF i schematu przed użyciem dokładnie zweryfikowanych bajtów
parsera. Ścieżki z dowiązaniami i różniące się artefakty są odrzucane.
Nie ma automatycznego pobierania, kopiowania parsera ani konfiguracji runtime
w dokumencie kandydata. Zaufany pin całego pakietu docs obejmuje także lock;
sam kandydat nie może go zastąpić.

`DOCS_DSL_RUNTIME` oznacza brak lub niezgodność zależności;
`DOCS_DSL_FENCE` niepoprawne ogrodzenie; `DOCS_DSL_SYNTAX` odmowę
kanonicznego parsera; `DOCS_DSL_CONTRACT` odmowę profilu;
`DOCS_DSL_TEST` błędny cel testu. Każdy błąd zatrzymuje kontrolę.
Bez bloku DSL zależność nie jest potrzebna. Istniejące ilustracje `dsl`
w v2 wymagają migracji do `text` albo prawidłowego kontraktu.

Przykłady: [FEATURE](../FEATURE/CHANGE_CONTRACTS.md) oraz
[BUGFIX](../BUGFIX/DUPLICATE_DSL_CONTRACT.md). Pełna adopcja w CI konsumenta
wymaga osobnego przypięcia i dowodu, że brama odrzuca błędny kontrakt.

## DOCS-009 — Profil kompaktowy v2

Jeden plik opisuje jeden problem, zmianę, decyzję albo procedurę. Nazwa MUSI
określać temat i rezultat: `PROVIDER_DNS_CHANGE_DETECTION.md`, a nie
`REPORT.md`, `SUMMARY_FINAL_V2.md` czy `URGENT_FIX.md`. Używamy ASCII
`UPPER_SNAKE_CASE.md`: wielkie litery w nazwie, podkreślniki, rozszerzenie
małe `.md`. Stabilne `id: provider-dns-change-detection` daje tę samą nazwę
przez zamianę myślników na podkreślniki i wielkie litery; id zaczyna się literą.
Wersja, data i priorytet nie należą do nazwy.

| kind | Katalog | Zawartość |
| --- | --- | --- |
| bugfix | docs/BUGFIX/ | Objaw, przyczyna, poprawka, dowód regresji |
| feature | docs/FEATURE/ | Nowe zachowanie, zakres, użycie i odbiór |
| service | docs/SERVICE/ | Utrzymanie, obsługa lub procedura operacyjna |
| information | docs/INFORMATION/ | Trwała instrukcja lub opis kontraktu |
| analysis | docs/ANALYSIS/ | Pytanie, metoda, ustalenia i ograniczenia |
| refactoring-plan | docs/REFACTORING/ | Mała zmiana struktury, zgodność i migracja |
| decision | docs/DECISION/ | Wybór, alternatywy i konsekwencje |

Obowiązuje istniejący wyjątek układu `subactor/docs` z prefiksem
`architecture/` i indeksem `README.md`. Raport organizacyjny nadal należy do
`org/report`. Profil można adoptować w dowolnym repo. Domyślny `--fleet`
wybiera Subactor; jawny `--namespace` rozszerza audyt zgodnie z DOCS-011.

Nie tworzymy katalogu URGENT. Pilność to `priority: P0|P1|P2|P3`;
P0/P1 oznaczają pilne prace zgodnie z klasyfikacją projektu. Poprawka pozostaje
w BUGFIX po obniżeniu priorytetu. Rodzaj opisuje dokument, nie nadaje uprawnień
i nie zastępuje klasyfikacji ticketu. Nie tworzymy pustych katalogów na zapas.

[Szablon COMPACT.md](templates/COMPACT.md) ma 12 wymaganych pól JSON
i cztery sekcje: `summary`, `details`, `validation`, `risks`.
Tytuł nazywa rezultat; summary w 1–3 zdaniach podaje cel i stan.
Details mieści zakres, przyczynę lub decyzję; analysis odróżnia fakty od hipotez.
Validation podaje kryterium, metodę i wynik lub jawną lukę.
Risks podaje zgodność, rollback, odpowiedzialnego i następny krok, o ile dotyczą.
Refaktoryzacja zachowuje zależności etapów i warunek zatrzymania; bugfix
wskazuje odtwarzalny objaw i test regresji. Sekcje nie mogą być puste.

Limity MUSZĄ być spełnione jednocześnie: **120 linii, 600 słów, 12288 bajtów
UTF-8** całego pliku, również JSON, tabel i kodu. Słowo to token oddzielony
białymi znakami. Docelowo 40–80 linii i 150–400 słów. Limity są początkowym
budżetem redakcyjnym; nie gwarantują jakości. Nie wolno usuwać istotnych
ograniczeń ani dowodów, by zmieścić tekst. Podzielić go na samodzielne tematy,
połączyć linkami i dodać krótkie opisy do indeksu. Logi i pełne wyniki testów
pozostają artefaktami; procedury błędów należą do runbooków `errors/{CODE}.md`
standardu logs i są linkowane.

V2 usuwa duplikowane created/review_after/affected_repositories; historię dat
zapewnia Git, datę obserwacji updated, właściciela owner i zakres scope.
source_revision nadal wiąże pełny SHA badanego źródła, evidence podaje konkretne
referencje. Zmiana ustaleń zwiększa version; updated musi opisywać rzeczywisty
przegląd. Wymóg aktualności pozostaje merytoryczny: v2 nie emituje automatycznego
ostrzeżenia review_after. Status dokumentu nie jest statusem wdrożenia.

### Changelog i migracja

Changelog POWINIEN zawierać jedno zdanie o skutku dla użytkownika i względny
link do dokumentu, np.:

```markdown
- Wykrywanie zmiany adresu providera — [opis](docs/FEATURE/PROVIDER_DNS_CHANGE_DETECTION.md).
```

Szczegóły, polecenia i dowody należą do dokumentu. Nie tworzymy dokumentu dla
każdej literówki; samodzielny opis ma być użyteczny poza historią commitu.
Indeks `docs/README.md` zawiera temat i krótkie objaśnienie, bez kopii treści.
Preferowane są linki do całych plików. Checker weryfikuje lokalne cele Markdown
w śledzonym CHANGELOG.md (inline i definicje referencyjne), również usunięte
lub nieśledzone pliki i dowiązania. Nie sprawdza sieci ani kotwic renderera;
nie ocenia długości zdań i trafności opisu. Przykłady w fenced code są pomijane.

Format v1 i jego dotychczasowe ścieżki pozostają obsługiwane. Brama nie wymusza
masowej konwersji ani nie uznaje v1 za dowód adopcji v2. Migrację planujemy przy
merytorycznej zmianie: spis linków, podział tematów, aktualizacja indeksu
i changelogu w jednym diffie, kontrola odnośników. Zachować dawny plik jako
mapę do nowych tematów i dotychczasowe kotwice dla starszych linków; nie
przepisywać opublikowanej historii wydań. W razie zmiany rodzaju utrzymać
stare wejście na czas migracji. Nie kopiować pełnej treści do dwóch katalogów.

Preflight dla v2 jawnie wybiera format:

```bash
python3 "$DOCS_STANDARD_ROOT/docs/standard/check.py" \
  --root . --standard-revision "$DOCS_STANDARD_REVISION" --prepare --format v2 \
  --scope repository --kind feature --id provider-dns-change-detection \
  --deliverable docs/FEATURE/PROVIDER_DNS_CHANGE_DETECTION.md
```

Po zapisaniu i git add uruchomić checker z zaufanym `--base` i
`--deliverable`. Przygotowanie bez `--format` zachowuje v1 dla dotychczasowych
generatorów. Nowy pin i ustawienie v2 w generatorze wymagają adopcji konsumenta;
wdrożenie źródła standardu nie oznacza wdrożenia na flocie.

### Sprawdzalna mapa dawnej ścieżki

Stary plik może stać się mapą `wellmanifest.docs/redirect/v1`. Nagłówek JSON
ma dokładnie pola `schema`, `owner` (repozytorium), `version` (dodatnia
liczba), `updated` (data) i `targets` (1–16 ścieżek od korzenia repo).
Zachować dotychczasowe nagłówki, a pod nimi umieścić wyłącznie linki do
zadeklarowanych plików. Bez kopii treści, łańcuchów przekierowań i URL sieciowych.
Mapy nie zajmują identyfikatora dokumentu kanonicznego. Każdy cel musi być
śledzonym dokumentem v1/v2 we właściwej lokalizacji, wpisanym do indeksu.
Treść mapy ma najwyżej 120 linii i 12 KiB.

Przy zaufanym `--base` checker potwierdza istnienie starej ścieżki oraz wzrost
version względem poprzednich zarządzanych metadanych. Audyt bez bazy i preflight
sprawdzają strukturę mapy, nie jej pochodzenie. Nowy plik z mapą nie może
udawać historycznej ścieżki w bramie publikacji.

## DOCS-011 — Jawne pokrycie pilotażu i floty

`--fleet` audytuje bezpośrednie checkouty pod wskazanym katalogiem. Opcję
można powtarzać dla kilku katalogów, także kontenerów zagnieżdżonych.
Nie ma rekursji do `.worktrees`, archiwów ani repozytoriów organizacji w sieci.
`--namespace semcod --namespace autogrammar` zastępuje domyślne `subactor`;
wartości są dokładnymi nazwami właścicieli GitHub, bez `/` i wildcardów.
Porównanie nazw organizacji nie zależy od wielkości liter. Filtr nie zmienia
właściciela dokumentu, zakresu, przypięcia ani granic uprawnień.

Raport MUSI pokazywać `namespace_counts`, pominięte wpisy z przyczynami oraz
ścieżkę, HEAD i dirty state każdego badanego checkoutu. Brak obserwowalnego
commitu lub statusu checkoutu jest błędem. Brak choć jednej żądanej organizacji,
nieosiągalny lub dowiązany root oraz nierozpoznany origin checkoutu oznaczają
błąd, a nie zgodność. Rozpoznajemy dokładnie host GitHub przez HTTPS lub SSH;
nie wypisujemy URL z ewentualnymi danymi uwierzytelnienia.

`repositories_checked` zachowuje historyczne znaczenie liczby checkoutów;
`unique_repositories_checked` liczy różne deklarowane origin. Powtórzenie tej
samej ścieżki nie powiela kontroli. Różne checkouty tego samego origin są
sprawdzane wszystkie: czysta kopia nie może ukryć niezgodnej. `duplicates`
jest obserwacją tożsamości, NIE dowodem zbędności danych ani zgodą na usunięcie.
Lokalny origin nie dowodzi aktualnej tożsamości zdalnej; przekierowania GitHub
wymagają osobnego uzgodnienia. Checker nie pobiera repozytoriów ani nie zmienia
Issues, plików, historii, pinów lub chronionego CI.

Pilotaż rozdziela: odkrycie checkoutów, zgodność dokumentów, integrację
generatora, rzeczywiste egzekwowanie CI i publikację. `ok: true` dotyczy tylko
wybranego lokalnego zakresu; nie dowodzi migracji wszystkich historycznych
Markdownów. Przed masową adopcją wymagane są canary negatywne w procesie
konsumenta: brak adopcji, rozbieżny pin, brak indeksu, błędny cel oraz błędny
kontrakt DSL MUSZĄ zatrzymać odpowiedni etap. Zmiany chronionej konfiguracji
przechodzą odrębny zaufany proces. Wynik lokalnego testu go nie zastępuje.

## DOCS-001 — Zakres

Profil Subactor obowiązuje każde repozytorium `subactor/*`, obecne i przyszłe: usługi, biblioteki, CLI, agentów, standardy produktowe i repozytoria dokumentacji. Obejmuje nowe i zmieniane informacje trwałe, analizy, decyzje i plany refaktoryzacji. Istniejącej historii nie przepisuje się masowo; migracja dokumentu następuje przy jego następnej merytorycznej zmianie. Obowiązywanie wytycznej i potwierdzona adopcja w CI to dwa odrębne stany.

## DOCS-002 — Miejsce dokumentu ustala się przed pracą

Przed badaniem albo pisaniem agent/operator MUSI wskazać repozytorium właściciela, rodzaj dokumentu i docelową ścieżkę, np. `subactor/core:docs/refactoring/publication-controller.md`. Jeśli istnieje rejestr artefaktów, najpierw rozwiązuje w nim dokument i jego źródło wersji. Nie tworzy drugiego rejestru ani kopii istniejącego dokumentu.

Domyślne lokalizacje wewnątrz repozytorium:

| Rodzaj | Ścieżka |
| --- | --- |
| Informacja trwała | `docs/information/<id>.md` |
| Analiza i raport badania | `docs/analysis/<id>.md` |
| Plan refaktoryzacji | `docs/refactoring/<id>.md` |
| Decyzja architektoniczna | `docs/decisions/<id>.md` |
| Indeks | `docs/README.md` |

Identyfikator jest stabilny; poprawki aktualizują wersję dokumentu zamiast tworzyć REPORT-final-v2-new.md. Zmiana znaczenia lub aktualizacja ustaleń MUSI zwiększyć `version` i zaktualizować `updated`; historyczny stan pozostaje w Git. Repozytorium może mieć wcześniejszy system wersjonowania append-only — zachowuje go i wskazuje kanoniczny dokument, bez przepisywania starych wersji.

Nowy lub merytorycznie zmieniany wynik MUSI deklarować `scope` i dokładny `owner` w postaci `org/repo`. Dla `scope: repository` właścicielem pozostaje konkretne repozytorium, również gdy analiza wskazuje zależności z innych repo. Dla `scope: organization` właścicielem jest `[org]/report`, np. `subactor/report:docs/analysis/subactor-fleet-audit-2026-09-13.md`. Liczba `affected_repositories` nie zastępuje decyzji o odpowiedzialności. Raport kilku organizacji musi mieć wskazaną organizację odpowiedzialną; nie wolno zgadywać właściciela ani powielać całego raportu.

Przed utworzeniem repozytorium operator MUSI sprawdzić jego istnienie i rejestr artefaktów. Błąd dostępu lub sieci nie jest dowodem nieistnienia. Jeśli `[org]/report` naprawdę nie istnieje, tworzy je wyłącznie uprawniony proces w zaakceptowanej widoczności, z wymaganym seedem standardów i chronioną publikacją. Checker nie tworzy repozytoriów. Brak uprawnienia, nieustalony właściciel albo brak adopcji zatrzymuje generowanie trwałego wyniku; nie uprawnia do publikowania go w `/tmp`.

Historyczne dokumenty przekrojowe w `subactor/docs` zachowują dotychczasowe ścieżki `architecture/{information,analysis,refactoring,decisions}/<id>.md` i indeks `README.md`. Brak `scope` jest tolerowany wyłącznie przy audycie lub dla dokumentu niezmienionego względem zaufanej bazy. Przy zmianie trzeba ustalić aktualnego właściciela: dokument repozytorium wiedzy może pozostać lokalny, raport całej organizacji trafia do `org/report` z odnośnikiem migracyjnym. Nie kasuje się historii ani nie wykonuje masowej migracji archiwów.

## DOCS-003 — Dokumentacja a dane robocze

Końcowy raport lub plan NIE MOŻE istnieć wyłącznie w `$HOME/.local/state`, `/tmp`, katalogu sesji agenta, czacie ani `project/ticket-*`. Te miejsca nie zastępują wersjonowanego rezultatu. Ticket przechowuje bounded intent i odnośnik do dokumentacji, nie drugi plan.

Surowe logi, pełne transkrypcje, sekrety, bazy robocze, backupy i Git bundle NIE SĄ dokumentacją do publikacji. Pozostają w prywatnym, ignorowanym magazynie zgodnym z przyjętym standardem recovery/continuity. Dokument może wskazać bezpieczny identyfikator receiptu i digest; nie przenosi się całego magazynu do `docs/` tylko po to, by był blisko repozytorium. Ścieżka lokalna nie jest trwałym dowodem dostępnym całemu zespołowi.

## DOCS-004 — Metadane i jakość informacji

Dokument MUSI mieć nagłówek JSON pomiędzy separatorami `---`, zgodny z szablonem. Zawiera właściciela, wersję, status, zakres repozytoriów, dokładną rewizję źródła, daty i referencje dowodowe. `review_after` oznacza termin ponownego sprawdzenia, nie automatyczną utratę historii. Przeterminowany dokument nie może być przedstawiany jako świeża obserwacja.

Fakty, hipotezy i rekomendacje MUSZĄ być odróżnione. Pomiary podają zakres, metodę, wykluczenia, rewizje i ograniczenia. Liczba linii lub podobieństwo tekstowe nie dowodzą błędu ani szkodliwej duplikacji. Celowe kopie zarządzanych standardów oraz projekcje jednego źródła oznacza się jako adopcję/projekcję.

Dowód MUSI być konkretną referencją do kodu w rewizji, testu, obserwacji lub receiptu. Nie wolno wymyślać wyników testów, utożsamiać exit code z osiągniętym celem ani traktować starego raportu jako bieżącego stanu wdrożenia. Brak dowodu oznacza jawnie opisaną lukę.

## DOCS-005 — Plan refaktoryzacji

Plan MUSI wyjaśniać problem i mierzalny cel, stan obecny, zakres i non-goals, dowody, odpowiedzialności docelowe, kolejność małych zmian, kompatybilność, kryteria odbioru, testy, rollback, ryzyka oraz właściciela każdej części. Nie wolno zastępować go listą poleceń dla agenta ani postulatem „przepisać całość”.

Migracja obejmuje zależności między etapami i warunek zatrzymania. Kryteria odbioru opisują zachowanie, np. „równoległe żądania tego samego efektu dają jeden efekt”, a nie wyłącznie liczbę nowych plików. Przy zmianie stanów, serializacji, hashy, schematów lub authority wymagane są testy zgodności starych i nowych konsumentów oraz strategia odczytu historycznych danych.

Usuwanie duplikatów zaczyna się od ustalenia właściciela i kontraktu. Współdzieli się równoważne reguły, nie funkcje tylko dlatego, że podobnie wyglądają. Jedno źródło może mieć adaptery dla różnych języków i wspólne wektory testowe. Rozdzielenie uprawnień CI, Review i Merge musi zostać zachowane.

## DOCS-006 — Status nie jest uprawnieniem

`draft`, `proposed`, `accepted`, `implemented` i `superseded` opisują dokument. Nawet `accepted` nie jest zgodą na deploy, odczyt sekretów, usunięcie gałęzi ani merge. Właściwy proces wymaga własnego, aktualnego uprawnienia i dowodu. Raport analizy nie zamyka automatycznie ticketów i nie generuje commitów zamykających.

## DOCS-007 — Odkrywalność i odbiór

Dokument MUSI być śledzony przez Git i podlinkowany w indeksie dokumentacji. Końcowa odpowiedź agenta wskazuje ścieżkę w repozytorium oraz stan publikacji: lokalny plik, commit, PR, merged. Nie wolno przedstawiać pliku lokalnego jako opublikowanej dokumentacji.

Sekcje szablonów mają stabilne znaczniki `<!-- docs:section ... -->`, dlatego tytuły mogą być po polsku lub w języku projektu. Każda wymagana sekcja zawiera treść; nieadekwatność wymaga krótkiego uzasadnienia. Szablon z niewypełnionymi `{{...}}` nie jest gotowym rezultatem.

## DOCS-008 — Adopcja i egzekwowanie

Każdy `subactor/*` MUSI posiadać przypięcie `.governance/docs.json` i odnośnik w instrukcjach agentów do opublikowanej rewizji pakietu. Istniejący proces CI/OneDev wywołuje checker z zaufanej instalacji standardu. Nie tworzy się dodatkowego workflow GitHub tylko dla tej bramy.

Przypięcie zawiera `schema`, `repository`, `standard`, `source_revision` i `policy_sha256`. Źródło to pełny SHA opublikowanego standardu; ruchomy `main`, skrócony SHA i samo słowo „latest” są niewystarczające. Checker porównuje hash polityki i rewizję ze swoim zaufanym wejściem. PR nie może sam wybrać słabszego standardu ani ustawić zaufanej rewizji w miejsce chronionej konfiguracji CI.

Adopcja przebiega: audyt read-only → wskazanie właściciela dokumentacji → bounded PR z manifestem, indeksem i podłączeniem istniejącej bramy → weryfikacja → chroniona publikacja. Nowe repo otrzymuje to w seedzie; istniejące w normalnej zmianie integracyjnej. Fleet audit raportuje brak adopcji jako brak, nie jako zgodność.

Checker obejmuje dokumenty tego profilu w Git oraz jawnie wskazane `--deliverable`. Nie widzi wszystkich plików zapisanych przez agenta poza repozytorium i nie dowodzi prawdziwości treści. Dlatego deklaracja ścieżki przed pracą, przegląd merytoryczny i sprawdzenie publikacji pozostają konieczne. Zachowanie historycznych formatów nie uprawnia do omijania profilu dla nowego rezultatu.

### Brama przed generowaniem i operacją

Generator lub agent MUSI najpierw rozwiązać obowiązujące standardy i istniejący artefakt w rejestrze, następnie wywołać zaufany checker z `--prepare --root ... --scope ... --kind ... --id ... --deliverable ...`. Wynik `ok: false` lub niezerowy kod zatrzymuje generator przed zapisem raportu. Kontrola wymaga przypięcia adopcji, właściwego repozytorium, śledzonego indeksu i bezpiecznej ścieżki bez dowiązań. Wynik `delivery-plan/v1` zawiera właściciela, ścieżkę, pin i digest polityki oraz digest planu.

Plan jest dowodem wyboru miejsca, NIE uprawnieniem do operacji i NIE poświadczeniem niezmienności środowiska. Konsument wiąże go z bieżącym zadaniem, sprawdza ponownie przed zapisem po zmianie wejść, nie nadpisuje istniejącego raportu bez kontroli wersji i po generowaniu uruchamia pełny checker z zaufaną bazą i jawnym rezultatem. Odbiór wymaga osobno chronionej publikacji. Błąd późniejszej kontroli oznacza niedostarczony rezultat, nawet jeśli plik został zapisany lokalnie.

Operacje deploy, merge, czyszczenie, publikacja i generowanie artefaktów nietekstowych nadal wymagają właściwego standardu domenowego, intencji i uprawnienia. DOCS nie zastępuje tych bram. Instrukcja w AGENTS albo nowy parametr CLI nie jest dowodem wdrożenia: odbiór automatyzacji MUSI wykazać, że konsument odmawia zapisu po błędzie preflight i odmawia publikacji po błędzie kontroli końcowej. Raport adopcji odróżnia opublikowaną regułę, podłączony generator i chronioną bramę każdego konsumenta.


### Odkrywanie zmian względem bazy

Brama publikacji MUSI przekazać zaufany `--base`. Checker obejmuje również każdy nowy lub zmieniony, śledzony plik Markdown względem tej bazy, nawet bez metadanych. Niezmienione dokumenty historyczne pozostają poza migracją. Zastąpienie dokumentu dowiązaniem lub usunięcie metadanych nie usuwa go z kontroli.

`policy.json/discovery` jawnie wyłącza pliki organizacyjne: indeksy README, instrukcje agentów, changelog, TODO, konwencjonalne instrukcje współpracy i bezpieczeństwa, katalogi konfiguracji governance/CI/hostów oraz bezpośrednie pliki Markdown ticketów. Wyjątki dotyczą tylko automatycznego odkrywania: dokument rozpoznany jako zarządzany obecnie lub w bazie, albo wskazany przez `--deliverable`, nadal podlega pełnej kontroli. Nie wolno używać pliku organizacyjnego jako jedynego miejsca raportu końcowego. Kontrola bez bazy jest audytem istniejącego profilu, nie pełną bramą nowych rezultatów; nie wykrywa nieśledzonych plików bez jawnego `--deliverable`.

### Kontrola zakończenia z jawnym rezultatem

Konsument MUSI zachować udany wynik `--prepare`, a przed ogłoszeniem dostarczenia
wywołać `--complete --root REPO --base TRUSTED_BASE --deliverable PATH
--prepared-plan RECEIPT --standard-revision PIN`. Każdy dokument ma osobny plan.
Brak rezultatu lub planu, niezgodność tożsamości, digestu, ścieżki lub przypięcia
zatrzymuje kontrolę. Brama sprawdza plik w Git, indeks, metadane i wersję
oraz zwraca digests odczytanych bajtów. Zwykły audyt `check` bez rezultatu nie
zastępuje tej bramy; sukces audytu pustego zbioru nie oznacza ukończenia zadania.

Plan jest niesygnowanym dowodem deklaracji. Walidator nie dowodzi kolejności
czasowej przygotowania ani prawdziwości treści. Zaufany konsument wiąże plan
z zadaniem, wymaga tej kontroli w swojej ścieżce zakończenia i osobno sprawdza
publikację. `completion.ready` nie oznacza commitu, PR, merge ani uprawnienia.
Regresja konsumenta musi sprawdzić, że brak planu lub raport tylko w recovery
blokuje ogłoszenie zakończenia. Samo dodanie tej reguły do AGENTS nie stanowi
wdrożenia; audyt rozdziela instrukcję, pin, wywołanie i obserwowany wynik.

### Verified copies of external standard documentation

An adopter may pass `--managed-copies <trusted-json>`: a path-to-SHA256 map
selected by its trusted integration from an independently pinned, published
standard inventory. This input is not discovered in a report or inferred from
its owner field. Verify the owning standard's full inventory before supplying it.
Only tracked Markdown under `.governance/docs/` with matching actual bytes may
be separated from consumer document discovery. Explicit deliverables, product
documentation paths, symlinks and mismatched hashes always fail. Results enumerate
`managed_copies_verified`; this verifies copy integrity, not document conformance
or upstream publication. Preparation binds the same inventory into its plan;
completion revalidates it. This narrow integration boundary prevents an immutable
standard manual from being moved into the adopter's product documentation.
