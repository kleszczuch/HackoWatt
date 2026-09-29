# Eko-dziki

**Eko-dziki** to lokalna aplikacja do analizy i optymalizacji zużycia energii w domu. Łączy symulację zużycia energii, dane pogodowe, prognozowanie zapotrzebowania, analizę taryf oraz symulator instalacji fotowoltaicznej i magazynu energii.

Aplikacja działa lokalnie jako projekt **Django** i udostępnia również REST API przeznaczone do komunikacji z aplikacją mobilną.

**! dane dotyczące zużycia energii są danymi symulowanymi. Nie są to bezpośrednie odczyty z rzeczywistego licznika energii.**

---

## Najważniejsze funkcje

### Dashboard

![Strona główna aplikacji](static\energy\glowna_strona.png)

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

![Podstrona analizy godzinowej](static\energy\godziny.png)

Widok `|godziny|` prezentuje szczegółowe dane godzinowe:

* wykres zużycia,
* tabelę danych,
* kategorie zużycia,
* filtrowanie po zakresie dat,
* stronicowanie,
* eksport danych do CSV.

---

### Symulator fotowoltaiki

![Podstrona symulatora fotowoltaiki](static\energy\symulator.png)

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

Sekcja **Plan pracy urządzeń na jutro** korzysta z 35 dni historii cykli,
jutrzejszej prognozy, taryfy, PV i magazynu. Python liczy dopuszczalne godziny
i kwoty, a lokalny Qwen3 wybiera godzinę z listy i pisze uzasadnienie.
Model dostaje tylko warianty, które po zaokrągleniu dają widoczną oszczędność;
każda propozycja jest ponownie liczona po przesunięciu pozostałych cykli.
Gdy tańszej godziny nie ma, karta zaleca pozostawienie obecnej bez kwoty.
Szacunek roczny jest ekstrapolacją częstotliwości cykli z 35 dni historii przy
jutrzejszych warunkach, nie prognozą przyszłorocznych cen.
Karty pokazują również liczbę dni z cyklem. Obok nich znajdują się wszystkie
typy zdarzeń zapisane w historii wybranego scenariusza (np. praca zdalna,
goście, wyjazd, opieka nad psem, pompa basenu, sauna, ładowanie EV). Dla
pompy basenu aplikacja wykrywa cykl z aktualnej historii i proponuje
przesunięcie wyłącznie wtedy, gdy obniża ono policzony koszt całego domu.
Gdy tańszej godziny nie ma, pokazuje zalecenie pozostawienia obecnej.
Ładowanie EV przechodzi przez północ, więc do wiarygodnej wyceny jego pełnego
cyklu potrzebna byłaby prognoza dłuższa niż obecne 24 godziny. Pozostałe
zdarzenia są obserwacjami historycznymi, bez wymyślonych kwot.

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

# Uruchomienie na Windows (PowerShell)

Wykonuj poniższe kroki w PowerShellu. Potrzebne są Git, połączenie z internetem
przy pierwszej instalacji i pobieraniu danych oraz miejsce na model Qwen3 1.7B
(około 1,4 GB). Projekt wymaga Pythona `>=3.14,<3.15`; `uv` może go zainstalować.

### Całość w jednej linii

W katalogu sklonowanego projektu uruchom poniższą linię w PowerShellu. Instaluje
uv i Ollamę, odświeża `PATH`, pobiera Pythona i model, przygotowuje dane oraz
uruchamia stronę. Pierwsze wykonanie wymaga internetu; jeśli instalator Ollamy
poprosi o dokończenie instalacji, wykonaj to przed ponownym uruchomieniem linii.

```powershell
$ErrorActionPreference='Stop'; irm https://astral.sh/uv/install.ps1 | iex; irm https://ollama.com/install.ps1 | iex; $env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User')+";$HOME\.local\bin"; uv python install 3.14; if($LASTEXITCODE){throw 'Instalacja Pythona nie powiodła się'}; ollama pull qwen3:1.7b; if($LASTEXITCODE){throw 'Pobranie modelu nie powiodło się'}; if(!(Test-Path .env)){ @("API_KEY=$([guid]::NewGuid().ToString('N'))",'OLLAMA_MODEL=qwen3:1.7b','OLLAMA_HOST=http://localhost:11434') | Set-Content -Encoding ascii .env }; uv sync; if($LASTEXITCODE){throw 'Instalacja zależności nie powiodła się'}; uv run python manage.py migrate; if($LASTEXITCODE){throw 'Migracje nie powiodły się'}; uv run python manage.py fetch_tariff_prices; if($LASTEXITCODE){throw 'Pobranie cen nie powiodło się'}; uv run python manage.py prepare_data; if($LASTEXITCODE){throw 'Przygotowanie danych nie powiodło się'}; uv run python manage.py prepare_recommendations; if($LASTEXITCODE){throw 'Przygotowanie rekomendacji nie powiodło się'}; uv run python manage.py runserver 127.0.0.1:8000
```

Adres strony: `http://127.0.0.1:8000/symulator-pv/`. Jeśli ceny PSE są
niedostępne, uruchom rozruch krok po kroku i pomiń samo
`fetch_tariff_prices`; plan użyje wtedy stawki taryfy stałej.

## 1. Zainstaluj uv i Python 3.14

Zainstaluj [uv](https://docs.astral.sh/uv/getting-started/installation/) oficjalnym
instalatorem i otwórz nowy PowerShell, aby odświeżyć `PATH`:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv --version
uv python install 3.14
```

Jeśli masz już `uv` i Python 3.14, wystarczy sprawdzić `uv --version`.

## 2. Zainstaluj Ollamę i pobierz model

Zainstaluj [Ollamę dla Windows](https://ollama.com/download/windows), a następnie
otwórz nowy PowerShell:

```powershell
irm https://ollama.com/install.ps1 | iex
ollama --version
ollama pull qwen3:1.7b
ollama list
```

Instalator Windows uruchamia serwer Ollamy w tle pod `http://localhost:11434`.
Sprawdź połączenie i uruchom model próbnie:

```powershell
Invoke-RestMethod http://localhost:11434/api/tags
ollama run qwen3:1.7b
```

Wpisz przykładowe pytanie; zakończ rozmowę poleceniem `/bye`. Po wyjściu
Ollama nadal obsługuje żądania aplikacji w tle. Jeśli `Invoke-RestMethod` nie
może się połączyć, uruchom `ollama serve` w osobnym oknie PowerShell i zostaw
je otwarte. Nie uruchamiaj drugiego serwera, jeśli port `11434` już działa.

## 3. Sklonuj repozytorium i ustaw środowisko

```powershell
git clone --recurse-submodules https://github.com/kleszczuch/HackoWatt.git
cd HackoWatt
uv sync
uv run python --version
```

Jeśli repozytorium zostało wcześniej sklonowane bez submodułu, wykonaj
`git submodule update --init --recursive`.

Utwórz lokalny plik `.env`. Klucz jest potrzebny do mobilnego API; strona
internetowa korzysta z sesji. Domyślny model to `qwen3:1.7b`, ale zapisanie
go w `.env` ułatwia zmianę konfiguracji:

```powershell
$apiKey = [guid]::NewGuid().ToString("N")
@("API_KEY=$apiKey", "OLLAMA_MODEL=qwen3:1.7b", "OLLAMA_HOST=http://localhost:11434") | Set-Content -Encoding ascii .env
```

`.env` jest ignorowany przez Git. Po zmianie `OLLAMA_MODEL` pobierz wskazany
model przez `ollama pull NAZWA_MODELU` i ponownie uruchom serwer Django.

## 4. Przygotuj bazę, ceny i dane

W katalogu projektu wykonaj komendy w tej kolejności:

```powershell
uv run python manage.py migrate
uv run python manage.py fetch_tariff_prices
uv run python manage.py prepare_data
uv run python manage.py prepare_recommendations
```

`fetch_tariff_prices` zapisuje dostępne ceny RCE w `data/tariff_prices.json`.
`prepare_data` pobiera pogodę z Open-Meteo i przygotowuje pięć scenariuszy.
`prepare_recommendations` tworzy plany na jutro dla tych scenariuszy przy
domyślnych ustawieniach i zapisuje je w ignorowanym przez Git
`data/recommendations/`. Pierwsze przeliczenie może potrwać, gdy model ładuje
się do pamięci. Jeśli Ollama nie działa, plan otrzyma źródło
`calculated_fallback` i godziny nadal zostaną wyliczone przez Python.

## 5. Uruchom stronę

```powershell
uv run python manage.py runserver 127.0.0.1:8000
```

Otwórz `http://127.0.0.1:8000/symulator-pv/` i rozwiń sekcję **Plan pracy
urządzeń na jutro**. Po zmianie taryfy w Ustawieniach wróć do symulatora;
po zmianie mocy PV lub magazynu karty pobiorą nowy plan automatycznie.

Gdy chcesz otworzyć lokalny serwer z telefonu w tej samej sieci, możesz użyć
`uv run python manage.py runserver 0.0.0.0:8000` i adresu komputera w sieci.

### Krótszy rozruch po instalacji

Po zainstalowaniu Ollamy, pobraniu modelu i wykonaniu migracji komenda
`all` uruchamia kolejno synchronizację zależności, pobranie cen,
`prepare_data`, `prepare_recommendations` oraz serwer:

```powershell
uv run python manage.py all --addrport 127.0.0.1:8000
```

Komenda `all` nie wykonuje migracji Django ani nie instaluje Ollamy.
Przydatne opcje: `--no-server` przygotowuje dane bez startu serwera,
`--no-sync`, `--no-tariffs`, `--no-data` i `--no-recommendations` pomijają
odpowiednie kroki, a `--noreload` wyłącza automatyczny restart serwera.

### Gdy brakuje cen taryfy dynamicznej

Plan wymaga pełnej prognozy zużycia i pogody na jutro. Jeśli plik RCE nie
zawiera ceny dla części lub wszystkich 24 godzin, aplikacja używa w tych
godzinach **stawek taryfy stałej** i pokazuje, ile godzin miało stawkę
zastępczą. Wykres taryfy oznacza brakujące ceny. Aby pobrać nowe ceny:

```powershell
uv run python manage.py fetch_tariff_prices
uv run python manage.py prepare_recommendations
```

Sprawdź zakres dat wypisany przez `fetch_tariff_prices`. Komunikat „Brak
pobierania” oznacza, że plik nie został zaktualizowany, np. z powodu braku
połączenia z PSE. Jeśli cen jutra nadal nie ma, plan nadal działa na stawkach
zastępczych; możesz ponowić pobieranie później. Przy braku prognozy zużycia lub pogody uruchom
ponownie `uv run python manage.py prepare_data`, a potem
`uv run python manage.py prepare_recommendations`.

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

Przykładowe wywołanie planu z PowerShella po uruchomieniu serwera:

```powershell
$apiKey = ((Get-Content .env | Where-Object { $_ -like 'API_KEY=*' }) -split '=', 2)[1]
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/v1/devices/ai-plan/ -Headers @{Authorization = "Bearer $apiKey"}
```

Endpoint strony `/rekomendacje/` używa sesji przeglądarki. Wynik API jest
opakowany w `{"status":"success","data":{...}}`; sam plan zawiera m.in.
`date`, `scenario_id`, `status`, `source`, `currency`, `recommendations`,
`observed_events` (w tym opcjonalne `advice` dla pompy basenu),
`tariff_fallback_hours` i `total_daily_saving`. Przy braku
prognozy lub historii ma `status: "no_data"`, pole `missing_data`
(`forecast`, `weather` lub `history`) i nie zawiera kwoty oszczędności.
Brak cen RCE powoduje użycie stawek stałych, nie `no_data`.
Domyślną walutą jest EUR; wybrana waluta jest
stosowana zarówno na stronie, jak i w API.

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
| `GET`  | `/api/v1/devices/ai-plan/`          | Plan pracy urządzeń na jutro z lokalnym AI             |
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

```powershell
uv run python manage.py test
```

Test z uruchomioną Ollamą i pobranym modelem:

```powershell
$env:OLLAMA_E2E = "1"
uv run python manage.py test energy.tests.RecommendationTests.test_e2e_real_ollama
Remove-Item Env:OLLAMA_E2E
```

Kontrola konfiguracji Django:

```powershell
uv run python manage.py check
```

Lint:

```powershell
uv run ruff check .
```

Sprawdzenie formatowania:

```powershell
uv run ruff format --check .
```

Sprawdzenie odświeżania kart po zmianie parametrów (wymaga Node.js):

```powershell
node energy/tests_recommendations.cjs
```

Walidacja specyfikacji OpenSpec:

```powershell
openspec validate lokalne-ai-planowanie-urzadzen --strict
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
* **Tailwind CSS 4 (django-tailwind)**
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
