# HackoWatt — Scenariusz 4 „Dom pełen pokoleń”

Lokalna aplikacja Django dla konkursowego scenariusza trzypokoleniowego domu
w Kopenhadze: **35 dni godzinowej historii** zużycia z generatora zdarzeń
domowników na **realnej pogodzie Open-Meteo**, **prognoza 24 h / 3 / 7 dni**
z oceną błędu wobec baseline'u oraz **symulator fotowoltaiki** z dwoma
wariantami zwrotu inwestycji.

## Uruchomienie

Wymagany jest Python 3.14 i [uv](https://docs.astral.sh/uv/). W katalogu
głównym projektu uruchom:

```powershell
uv sync
uv run python manage.py migrate
uv run python manage.py prepare_demo_data
uv run python manage.py runserver 127.0.0.1:8000
```

Otwórz `http://127.0.0.1:8000/`. Komenda `prepare_demo_data` wymaga jednorazowo
dostępu do sieci (Open-Meteo); przy jej błędzie używa wcześniej zapisanych
plików pogody, więc aplikacja działa offline na gotowej migawce CSV.
Powtórne wykonanie odświeża pogodę i wszystkie dane.

## Strony

- `/` — pulpit: wykres historii zużycia i temperatury (35 dni), wybór zakresu
  dat i horyzontu prognozy (24 h / 3 / 7 dni), sumy kWh, godziny szczytu
  z prostymi wyjaśnieniami oraz panel „model kontra baseline tydzień temu”
  (MAE i MAPE na ostatnich 7 dniach historii).
- `/symulator-pv/` — wybór mocy kWp, tabela porównawcza wariantów, roczna
  produkcja z realnego promieniowania, pokrycie zapotrzebowania, mniej energii
  z sieci, oszczędności i czas zwrotu: A (obecne nawyki) i B (po przesunięciu
  zmywarki, pralki i suszarki w godziny 9–15), wspólny wykres tygodniowy
  oraz rekomendacje z efektem w kWh i €.
- `/zalozenia/` — harmonogram mieszkańców, parametry urządzeń, sposób tworzenia
  historii, taryfa, założenia PV i metodologia szacunku rocznego.
- `/export.csv` — eksport historii i prognozy dla wybranego zakresu.

## REST API dla aplikacji mobilnej (`/api/v1/`)

Aplikacja udostępnia otwarty, bezstanowy zestaw endpointów JSON REST API pod przedrostkiem
`/api/v1/`, służący wyłącznie do odczytu danych (bez konieczności logowania, haseł
i tokenów). Interfejs został zaprojektowany z myślą o osobach starszych (dziadkach
obecnych w domu przed południem) oraz młodszych (dzieciach i młodzieży wracających
ze szkoły), ułatwiając natychmiastowe sprawdzenie, w jakich godzinach najrozsądniej
uruchomić urządzenia elektryczne.

### Format odpowiedzi

- **Sukces:** `{"status": "success", "data": { ... }}`
- **Błąd:** `{"status": "error", "error": {"code": "...", "message": "...", "details": ...}}`

### Dostępne endpointy

| Metoda | Ścieżka | Opis | Główne parametry |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/smart-schedule/today/` | **Główny harmonogram dnia:** 24 h z kolorami (zielony/żółty/czerwony) i poradami dla seniorów i młodzieży | brak |
| `GET` | `/api/v1/devices/guidance/` | **Przewodnik po urządzeniach:** kiedy uruchamiać zmywarkę, pralkę, suszarkę, piekarnik i konsolę | brak |
| `GET` | `/api/v1/dashboard/summary/` | Bieżący pulpit (odczyt, prosta ocena taryfy, 24 h, najbliższy szczyt) | brak |
| `GET` | `/api/v1/devices/shift-simulation/` | Kalkulator przesunięcia pracy urządzenia (dostępny przez prosty GET) | `device`, `original_hour`, `target_hour`, `energy_kwh` |
| `GET` | `/api/v1/tariffs/` | Strefy taryfowe (€/kWh), bieżąca stawka i optymalne okna | brak |
| `GET` | `/api/v1/consumption/history/` | Historia zużycia z paginacją i filtrem dat | `start`, `end`, `page`, `page_size` |
| `GET` | `/api/v1/consumption/forecast/` | Prognoza zapotrzebowania i wyjaśnienia szczytów | `horizon` (24, 72, 168) |
| `GET` | `/api/v1/pv/simulate/` | Symulator PV (wariant A vs B, oszczędności, zwrot) | `kwp`, `month`, `include_week_profile` |
| `GET` | `/api/v1/pv/variants/` | Zestawienie typowych mocy instalacji PV (2–10 kWp) | brak |
| `GET` | `/api/v1/devices/flexible-events/` | Lista zarejestrowanych cykli elastycznych urządzeń | `device`, `page`, `page_size` |
| `GET` | `/api/v1/system/assumptions/` | Parametry urządzeń, domu i instalacji | brak |
| `GET` | `/api/v1/system/metrics/` | Metryki dokładności modelu AI (MAE, MAPE) | brak |

## Dane w `data/`

`historia_zuzycie.csv` (840 h), `prognoza_zuzycie.csv` (168 h),
`pogoda_historia.csv`, `pogoda_prognoza.csv`, `pogoda_roczna.csv` (8760 h),
`roczne_zuzycie.csv`, `zdarzenia_elastyczne.csv`, `roczne_zdarzenia.csv`,
`backtest.csv` i `metryki.json`.

## Sprawdzenie

```powershell
uv run python manage.py test
uv run python manage.py check
uv run ruff check .
uv run ruff format --check .
openspec validate scenariusz-4-dom-pokolen --strict
```

## Zakres i uczciwość wyliczeń

Historia jest **symulacją** zdarzeń (posiłki, pranie, praca zdalna, goście,
wyjazdy) warunkowaną temperaturą z Open-Meteo — nie odczytem licznika. Roczne
zużycie szacuje ten sam generator uruchomiony na 12 miesiącach realnej pogody;
sezonowość ogrzewania wynika z temperatury, a produkcji PV z promieniowania.
Koszty w EUR według załącznika „Common Challenge Assumptions” (taryfa
0,18/0,28/0,40 €/kWh, PV 1300 €/kWp, eksport 0,08 €/kWh, OPEX 1%) są
szacunkami, nie rozliczeniem.

Aktywna [zmiana OpenSpec](openspec/changes/scenariusz-4-dom-pokolen/proposal.md)
opisuje rozwiązanie scenariusza. [Wcześniejszy plan](openspec/changes/domowa-optymalizacja-energii/proposal.md)
dotyczący importu realnych odczytów i taryf pozostaje osobnym, niewdrożonym
zakresem.
