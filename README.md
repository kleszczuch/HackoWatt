# Eko-dziki

**Eko-dziki** to lokalna aplikacja do analizy i optymalizacji zużycia energii w domu. Łączy symulację zużycia energii, dane pogodowe, prognozowanie zapotrzebowania, analizę taryf oraz symulator instalacji fotowoltaicznej i magazynu energii.

Aplikacja działa lokalnie jako projekt **Django** i udostępnia również REST API przeznaczone do komunikacji z aplikacją mobilną.

**! dane dotyczące zużycia energii są danymi symulowanymi. Nie są to bezpośrednie odczyty z rzeczywistego licznika energii.**

---

## Najważniejsze funkcje

### Dashboard

Główny pulpit pozwala analizować:

* zużycie energii w wybranym okresie,
* trendy zużycia i temperatury,
* godziny największego zapotrzebowania,
* prognozę zużycia na **24 h, 3 dni i 7 dni**,
* sumaryczne zużycie w kWh,
* dokładność modelu prognostycznego względem baseline'u.

Dostępne zakresy historii:

`1 / 3 / 5 / 7 / 14 / 31 dni`

---

### Analiza godzinowa

Widok `|godziny|` prezentuje szczegółowe dane godzinowe:

* wykres zużycia,
* tabelę danych,
* kategorie zużycia,
* filtrowanie po zakresie dat,
* stronicowanie,
* eksport danych do CSV.

---

### Symulator fotowoltaiki

Widok `|symulator-pv|` pozwala sprawdzić wpływ instalacji PV na bilans energetyczny domu.

Można analizować m.in.:

* moc instalacji w kWp,
* roczną produkcję energii,
* pokrycie zapotrzebowania,
* ilość energii pobieranej z sieci,
* szacowane oszczędności,
* czas zwrotu inwestycji,
* wpływ zmiany godzin pracy urządzeń.

Symulator porównuje dwa scenariusze:

| Wariant                      | Opis                                                                         |
| ---------------------------- | ---------------------------------------------------------------------------- |
| **A — obecne nawyki**        | Urządzenia działają według obecnego modelu zużycia                           |
| **B — przesunięcie zużycia** | Praca zmywarki, pralki i suszarki jest przesunięta na godziny **9:00–15:00** |

System może również uwzględniać magazyn energii poprzez podanie:

* pojemności `[kWh]`,
* mocy `[kW]`,
* ceny zakupu `[EUR]`.

W bilansie magazynu uwzględniana jest sprawność obiegu na poziomie **90%**.

---

## Dane pogodowe

Do generowania scenariusza wykorzystywane są rzeczywiste dane pogodowe z **Open-Meteo**.

Pogoda wpływa m.in. na:

* symulowane zużycie energii,
* sezonowość zapotrzebowania,
* produkcję energii z PV.

Dane obejmują historię, prognozę oraz pełny rok modelowy.

Jeżeli pobranie danych z Open-Meteo nie powiedzie się, aplikacja może wykorzystać wcześniej zapisane dane pogodowe.

---

## Prognozowanie zużycia

Projekt wykorzystuje modele uczenia maszynowego do prognozowania zapotrzebowania energetycznego.

W repozytorium znajdują się m.in. biblioteki:

* `scikit-learn`
* `xgboost`
* `numpy`
* `pandas`

Model może generować prognozy dla:

* **24 godzin**,
* **72 godzin**,
* **168 godzin**.

Dostępne są również metryki oceny modelu, m.in. **MAE** i **MAPE**.

---

## Aplikacja mobilna

Repozytorium zawiera aplikację mobilną jako **Git submodule**:

```text
mobile_app
```

Submodule wskazuje na:

`https://github.com/allt3rr/HackoWattMobileApp`

Po sklonowaniu repozytorium razem z submodułami:

```bash
git clone --recurse-submodules https://github.com/kleszczuch/HackoWatt.git
```

Jeżeli repozytorium zostało już sklonowane bez submodułów:

```bash
git submodule update --init --recursive
```

---

# Uruchomienie

## Wymagania

Projekt wymaga:

* **Python 3.14**
* **uv**
* dostępu do sieci podczas pierwszego przygotowania danych pogodowych

Wersja Pythona jest określona bezpośrednio w `pyproject.toml`:

```text
>=3.14,<3.15
```

---

## Sklonuj repozytorium

```bash
git clone --recurse-submodules https://github.com/kleszczuch/HackoWatt.git
cd HackoWatt
```

Następnie jedną komendą możesz włączyć serwer z pobranymi danymi:

```bash
uv run manage.py all
```

Jest możliwość konfiguracji powyższej komendy, jeżeli wymagane jest pominięcie jakiegoś kroku:

```bash
uv run manage.py all --no-server  #wykonuje tylko synchronizację i przygotowanie danych bez uruchamiania serwera.
uv run manage.py all --no-sync  #pomija krok uv sync.
uv run manage.py all --no-tariffs  #pomija pobieranie cen RCE.
uv run manage.py all --no-data  #pomija generowanie symulacji scenariuszy.
uv run manage.py all --addrport 127.0.0.1:8000  #pozwala zmienić adres lub port serwera.
```

Poniżej znajduje się krok po kroku, możliwość ręcznego pobrania danych i włączenia serwera

---

## 1. Zainstaluj zależności

Projekt wykorzystuje `uv` do zarządzania środowiskiem i zależnościami:

```bash
uv sync
```

---

## 2. Wykonaj migracje Django

```bash
uv run python manage.py migrate
```
---

## 3. Pobierz ceny dla taryfy dynamicznej

```bash
uv run python manage.py fetch_tariff_prices
```

---

## 4. Przygotuj dane demonstracyjne

```bash
uv run python manage.py prepare_data
```

Podczas tego kroku aplikacja może pobrać dane pogodowe z Open-Meteo i wygenerować dane potrzebne do działania dashboardu, prognoz oraz symulatora.

Ponowne uruchomienie tej komendy odświeża dane.

---

## 5. Uruchom aplikację

```bash
uv run python manage.py runserver 127.0.0.1:8000
```

Następnie otwórz:

```text
http://127.0.0.1:8000/
```

Dla użycia aplikacji mobilnej na telefonie użyj komendy:

```bash
uv run python manage.py runserver 0.0.0.0:8000
```

---

# REST API

API znajduje się pod prefiksem:

```text
/api/v1/
```

Udostępnia dane w formacie JSON i jest przeznaczone przede wszystkim do komunikacji z aplikacją mobilną.

## Konfiguracja

W katalogu głównym projektu należy utworzyć plik:

```text
.env
```

i skonfigurować klucz:

```env
API_KEY=your-secret-key
```

Klucz powinien być skonfigurowany również po stronie aplikacji mobilnej.

> Nie należy commitować rzeczywistego klucza API do repozytorium.

---

## Format odpowiedzi

### Sukces

```json
{
  "status": "success",
  "data": {}
}
```

### Błąd

```json
{
  "status": "error",
  "error": {
    "code": "...",
    "message": "...",
    "details": {}
  }
}
```

---

## Endpointy

| Metoda | Endpoint                            | Opis                                                 |
| ------ | ----------------------------------- | ---------------------------------------------------- |
| `GET`  | `/api/v1/smart-schedule/today/`     | Godzinowe stawki oraz najtańsza i najdroższa godzina |
| `GET`  | `/api/v1/devices/guidance/`         | Roczne dane dotyczące cykli i energii urządzeń       |
| `GET`  | `/api/v1/dashboard/summary/`        | Podsumowanie dashboardu                              |
| `GET`  | `/api/v1/devices/shift-simulation/` | Symulacja przesunięcia pracy urządzenia              |
| `GET`  | `/api/v1/tariffs/`                  | Strefy taryfowe i aktualna stawka                    |
| `GET`  | `/api/v1/consumption/history/`      | Historia zużycia                                     |
| `GET`  | `/api/v1/consumption/forecast/`     | Prognoza zapotrzebowania                             |
| `GET`  | `/api/v1/pv/simulate/`              | Symulacja instalacji PV                              |
| `GET`  | `/api/v1/pv/variants/`              | Przykładowe warianty mocy PV                         |
| `GET`  | `/api/v1/devices/flexible-events/`  | Historia elastycznych zdarzeń urządzeń               |
| `GET`  | `/api/v1/system/assumptions/`       | Założenia modelu                                     |
| `GET`  | `/api/v1/system/metrics/`           | Metryki jakości prognoz                              |

### Przykładowe parametry

Symulacja przesunięcia urządzenia:

```text
/api/v1/devices/shift-simulation/?device=dishwasher&original_hour=18&target_hour=12&energy_kwh=1.2
```

Prognoza:

```text
/api/v1/consumption/forecast/?horizon=24
```

Dostępne horyzonty:

```text
24
72
168
```

Symulacja PV:

```text
/api/v1/pv/simulate/?kwp=6&month=6
```

Symulator PV obsługuje również parametry magazynu energii oraz opcjonalny profil tygodniowy.

---

# Dane

Katalog `data/` zawiera przygotowane dane wykorzystywane przez aplikację, m.in.:

```text
historia_zuzycie.csv
prognoza_zuzycie.csv
pogoda_historia.csv
pogoda_prognoza.csv
pogoda_roczna.csv
roczne_zuzycie.csv
zdarzenia_elastyczne.csv
roczne_zdarzenia.csv
backtest.csv
metryki.json
```

Przykładowo:

* historia zużycia obejmuje **840 godzin**,
* prognoza obejmuje **168 godzin**,
* dane roczne obejmują **8760 godzin**.

---

# Testy i kontrola jakości

Testy Django:

```bash
uv run python manage.py test
```

Kontrola konfiguracji Django:

```bash
uv run python manage.py check
```

Lint:

```bash
uv run ruff check .
```

Sprawdzenie formatowania:

```bash
uv run ruff format --check .
```

Walidacja specyfikacji OpenSpec:

```bash
openspec validate magazyn-energii-pv --strict
```

---

# Ograniczenia

Wyniki symulacji należy traktować jako dane demonstracyjne.

Model:

* nie korzysta z rzeczywistych odczytów licznika,
* nie uwzględnia wszystkich możliwych zachowań mieszkańców,
* nie modeluje degradacji magazynu energii,
* nie uwzględnia kosztu wymiany magazynu,
* nie uwzględnia jego kosztów utrzymania,
* traktuje magazyn jako element przesuwający energię pomiędzy godzinami,
* nie uwzględnia ograniczeń montażowych dużych instalacji PV i magazynów.

W szczególności bardzo duże moce PV lub pojemności magazynów są **wariantami teoretycznymi** i przed rzeczywistą inwestycją wymagają osobnej weryfikacji technicznej i ekonomicznej.

---

# Technologie

Projekt wykorzystuje m.in.:

* **Python 3.14**
* **Django 5.2**
* **Pandas**
* **NumPy**
* **Plotly**
* **scikit-learn**
* **XGBoost**
* **django-cors-headers**
* **python-dotenv**
* **uv**
* **Ruff**

---

## Projekt

**Eko-dziki**

Autorzy:

**Marek Kleszcz, Adam Nowak, Bartosz Wiecha, Władysław Kobierski, Michał Przybyła**
