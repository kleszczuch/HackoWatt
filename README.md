# eko-dziki – Scenariusz 4 „Dom pełen pokoleń”

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
uv run python manage.py prepare_data
uv run python manage.py runserver 127.0.0.1:8000
```

Otwórz `http://127.0.0.1:8000/`. Komenda `prepare_data` generuje dane dla pięciu
scenariuszy i wymaga dostępu do Open-Meteo przy pierwszym uruchomieniu.
Wygenerowane pliki w `data/` są lokalne i nie są śledzone przez Git.
Komenda `prepare_data --scenario 4` odświeża tylko scenariusz Kopenhagi.

## Strony

- `/` – zwarty pulpit: wybór ostatnich 1 / 3 / 5 / 7 / 14 / 31 dni
  symulowanej historii i prognozy 24 h / 3 / 7 dni, sumy kWh, trendy
  zużycia i temperatury, godziny szczytu oraz błąd modelu wobec baseline'u.
- `/godziny/` – szczegółowy wykres i tabela godzinowa z kategoriami,
  filtrem dat, stronicowaniem i eksportem dokładnych wartości do CSV.
- `/symulator-pv/` – wybór mocy kWp, tabela porównawcza wariantów, roczna
  produkcja z realnego promieniowania, pokrycie zapotrzebowania, mniej energii
  z sieci, oszczędności i czas zwrotu: A (obecne nawyki) i B (po przesunięciu
  zmywarki, pralki i suszarki w godziny 9–15), wspólny wykres tygodniowy
  oraz policzony efekt zmiany godziny pracy urządzeń w kWh i €. Przyciski automatycznie dobierają moc
  do możliwie pełnego pokrycia w zakresie 1–150 kWp lub najkrótszego zwrotu
  wariantu B w zakresie 1–15 kWp, co 0,1 kWp. Opcjonalny magazyn ma wpisywaną pojemność [kWh],
  moc [kW] i cenę zakupu [EUR]. Godzinowy bilans uwzględnia 90% sprawności
  obiegu, a zwrot dolicza koszt magazynu. Widok pokazuje średnie dzienne
  zużycie budynku i bilans każdego dnia wybranego tygodnia. Gdy 100% pokrycia
  nie jest osiągalne przy zadanym magazynie, aplikacja pokazuje pozostały zakup
  z sieci. W pełnym roku stan magazynu na granicy lat ustala się po powtórzeniu
  roku modelowego; duże moce i magazyny są wariantami teoretycznymi, których
  wykonalność montażową i cenę trzeba sprawdzić osobno.
- Interfejs korzysta z palety Charcoal, Slate Grey, Sage Green, Radioactive Grass
  i Chartreuse oraz tła `energy/static/energy/Background.webp`.
- `/export.csv` – eksport historii i prognozy dla wybranego zakresu.

## REST API dla aplikacji mobilnej (`/api/v1/`)

### ABY REST API ZADZIAŁAŁO KONIECZNIE USTAW ZMIENNE ŚRODOWISKOWE
Utwórz plik .env wewnątrz głównego katalogu i dodaj zmienną API_KEY przechowującą kod secret, ten sam sposób utwórz klucz api po stronie aplikacji mobilnej.


Aplikacja udostępnia otwarty, bezstanowy zestaw endpointów JSON REST API pod przedrostkiem
`/api/v1/`, służący wyłącznie do odczytu danych (bez konieczności logowania, haseł
i tokenów). API podaje stawki godzinowe, zużycie i wyniki modelu. Pola dotyczące
urządzeń opisują zarejestrowane cykle i policzone różnice, bez gotowych poleceń.

### Format odpowiedzi

- **Sukces:** `{"status": "success", "data": { ... }}`
- **Błąd:** `{"status": "error", "error": {"code": "...", "message": "...", "details": ...}}`

### Dostępne endpointy

| Metoda | Ścieżka | Opis | Główne parametry |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/smart-schedule/today/` | Stawki każdej godziny i godziny najtańszej oraz najdroższej taryfy | brak |
| `GET` | `/api/v1/devices/guidance/` | Roczne liczby cykli i energii urządzeń w danych modelowych | brak |
| `GET` | `/api/v1/dashboard/summary/` | Bieżący pulpit (odczyt, prosta ocena taryfy, 24 h, najbliższy szczyt) | brak |
| `GET` | `/api/v1/devices/shift-simulation/` | Kalkulator przesunięcia pracy urządzenia (dostępny przez prosty GET) | `device`, `original_hour`, `target_hour`, `energy_kwh` |
| `GET` | `/api/v1/tariffs/` | Strefy taryfowe (€/kWh) i bieżąca stawka | brak |
| `GET` | `/api/v1/consumption/history/` | Historia zużycia z paginacją i filtrem dat | `start`, `end`, `page`, `page_size` |
| `GET` | `/api/v1/consumption/forecast/` | Prognoza zapotrzebowania i wyjaśnienia szczytów | `horizon` (24, 72, 168) |
| `GET` | `/api/v1/pv/simulate/` | Symulator PV (wariant A vs B, oszczędności, zwrot) | `kwp`, `month`, `magazyn_kwh`, `magazyn_moc_kw`, `magazyn_koszt_eur`, `include_week_profile` |
| `GET` | `/api/v1/pv/variants/` | Zestawienie typowych mocy instalacji PV (2–10 kWp) | brak |
| `GET` | `/api/v1/devices/flexible-events/` | Lista zarejestrowanych cykli elastycznych urządzeń | `device`, `page`, `page_size` |
| `GET` | `/api/v1/system/assumptions/` | Parametry urządzeń, domu i instalacji | brak |
| `GET` | `/api/v1/system/metrics/` | Metryki dokładności prognozy (MAE, MAPE) | brak |

## Dane w `data/`

Każdy scenariusz ma osobny katalog `data/scenario_1/`–`data/scenario_5/`.
Komenda `prepare_data` zapisuje w nich `historia_zuzycie.csv` (840 h),
`prognoza_zuzycie.csv` (168 h),
`pogoda_historia.csv`, `pogoda_prognoza.csv`, `pogoda_roczna.csv` (8760 h),
`roczne_zuzycie.csv`, `zdarzenia_elastyczne.csv`, `roczne_zdarzenia.csv`,
`backtest.csv` i `metryki.json`.

## Sprawdzenie

```powershell
uv run python manage.py test
uv run python manage.py check
uv run ruff check .
uv run ruff format --check .
openspec validate magazyn-energii-pv --strict
```

## Zakres i uczciwość wyliczeń

Historia jest **symulacją** zdarzeń (posiłki, pranie, praca zdalna, goście,
wyjazdy) warunkowaną temperaturą z Open-Meteo – nie odczytem licznika. Roczne
zużycie szacuje ten sam generator uruchomiony na 12 miesiącach realnej pogody;
sezonowość ogrzewania wynika z temperatury, a produkcji PV z promieniowania.
Koszty w EUR według załącznika „Common Challenge Assumptions” (taryfa
0,18/0,28/0,40 €/kWh, PV 1300 €/kWp, eksport 0,08 €/kWh, OPEX 1% kosztu PV)
są szacunkami, nie rozliczeniem. Cena magazynu pochodzi z wpisanej oferty;
symulacja nie uwzględnia jego degradacji, wymiany ani utrzymania. Magazyn
przesuwa energię między godzinami, lecz sam jej nie produkuje.

Aktywna [zmiana OpenSpec](openspec/changes/magazyn-energii-pv/proposal.md)
opisuje magazyn energii. [Wcześniejszy plan](openspec/changes/domowa-optymalizacja-energii/proposal.md)
dotyczący importu realnych odczytów i taryf pozostaje osobnym, niewdrożonym
zakresem.
