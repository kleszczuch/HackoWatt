# HackoWatt

Lokalny dashboard Django pokazujący **syntetyczne** godzinowe zużycie energii
w 2026 roku oraz 90-dniową prognozę z modelu XGBoost. Wykres roczny pokazuje
sumy dzienne, sześć wykresów szczegółowych pokazuje kategorie godzinowe,
a tabela zawiera dokładne wartości z wygenerowanych plików CSV.

## Uruchomienie

Wymagany jest Python 3.14 i [uv](https://docs.astral.sh/uv/). W katalogu
głównym projektu uruchom:

```powershell
uv sync
uv run python manage.py migrate
uv run python manage.py prepare_demo_data
uv run python manage.py runserver 127.0.0.1:8000
```

Otwórz `http://127.0.0.1:8000/`. Komenda `prepare_demo_data` tworzy
`data/zuzycie_energii_barbara_jan.csv` (8760 godzin) i
`data/prognoza_energii_barbara_jan.csv` (2160 godzin). Przy kolejnych
uruchomieniach serwera nie trzeba jej powtarzać. Powtórne wykonanie nadpisuje
oba pliki powtarzalnymi danymi i ponownie trenuje sześć modeli.

Wybierz daty **Od** i **Do**, aby zawęzić wykresy godzinowe i tabelę. Domyślny
zakres obejmuje koniec symulacji i początek prognozy. Tabela pokazuje 48
rekordów na stronie; przycisk **Pobierz CSV** eksportuje wszystkie rekordy
wybranego zakresu z dokładnością zapisaną w plikach. Wykresy działają
lokalnie bez połączenia z CDN.

## Sprawdzenie

```powershell
uv run python manage.py test
uv run python manage.py check
uv run ruff check .
uv run ruff format --check .
openspec validate dashboard-danych-demo --strict
```

Sprawdzone lokalnie: 7 testów przechodzi; kontrole Django i Ruff przechodzą.
Żądanie strony głównej zwraca HTTP 200, a eksport dla 31 grudnia 2026 i
1 stycznia 2027 zawiera 48 godzin danych.

## Zakres

Dane są wygenerowane przez dostarczony `generuj_zuzycie.py`. Prognozę wylicza
adaptacja `chart_generator.py`; model służy wyłącznie do demonstracji.
Znaczniki czasu są etykietami godzin syntetycznych i nie uwzględniają zmian
czasu letniego. To nie są rzeczywiste odczyty licznika ani wyliczenie rachunku.

Aktywna [zmiana OpenSpec](openspec/changes/dashboard-danych-demo/proposal.md)
opisuje dashboard. [Wcześniejszy plan](openspec/changes/domowa-optymalizacja-energii/proposal.md)
dotyczący importu realnych odczytów, taryf i rekomendacji pozostaje osobnym,
niewdrożonym zakresem.
