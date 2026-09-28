"""Formularze: zakres dat, horyzont prognozy i parametry symulatora PV.
Plik definiuje formularze Django używane w aplikacji do obsługi wejścia użytkownika i walidacji danych."""

from decimal import Decimal

from django import forms

HORIZON_CHOICES_PL = (("24", "24 godziny"), ("72", "3 dni"), ("168", "7 dni"))
HORIZON_CHOICES_EN = (("24", "24 hours"), ("72", "3 days"), ("168", "7 days"))

MONTH_NAMES_PL = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)
MONTH_NAMES_EN = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

MONTH_CHOICES_PL = tuple((str(num), name) for num, name in enumerate(MONTH_NAMES_PL, start=1))
MONTH_CHOICES_EN = tuple((str(num), name) for num, name in enumerate(MONTH_NAMES_EN, start=1))

HORIZON_CHOICES = HORIZON_CHOICES_EN
MONTH_CHOICES = MONTH_CHOICES_EN


class DateRangeForm(forms.Form):
    start = forms.DateField(label="Od", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Do", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, lang: str = "pl", **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        if lang == "en":
            self.fields["start"].label = "From"
            self.fields["end"].label = "To"
        else:
            self.fields["start"].label = "Od"
            self.fields["end"].label = "Do"

    def clean(self):
        """Sprawdza, czy data końcowa nie jest wcześniejsza od początkowej."""
        cleaned = super().clean()
        start = cleaned.get("start")
        end = cleaned.get("end")
        if start and end and end < start:
            msg = (
                "The end date cannot be earlier than the start date."
                if self.lang == "en"
                else "Data końcowa nie może być wcześniejsza niż początkowa."
            )
            raise forms.ValidationError(msg)
        return cleaned


class HorizonForm(forms.Form):
    """Formularz do wyboru długości horyzontu prognozy."""
    horyzont = forms.ChoiceField(
        label="Horyzont prognozy",
        choices=HORIZON_CHOICES_PL,
        widget=forms.Select(),
    )

    def __init__(self, *args, lang: str = "pl", **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        if lang == "en":
            self.fields["horyzont"].label = "Forecast horizon"
            self.fields["horyzont"].choices = HORIZON_CHOICES_EN
        else:
            self.fields["horyzont"].label = "Horyzont prognozy"
            self.fields["horyzont"].choices = HORIZON_CHOICES_PL


class PvForm(forms.Form):
    """Formularz parametrów symulatora PV i magazynu energii."""
    kwp = forms.DecimalField(
        label="Moc instalacji [kWp]",
        min_value=1,
        max_value=150,
        max_digits=4,
        decimal_places=1,
    )
    miesiac = forms.ChoiceField(label="Miesiąc wykresu", choices=MONTH_CHOICES_PL)
    magazyn_kwh = forms.DecimalField(
        label="Pojemność magazynu [kWh]",
        min_value=0,
        max_value=5000,
        max_digits=5,
        decimal_places=1,
    )
    magazyn_moc_kw = forms.DecimalField(
        label="Moc magazynu [kW]",
        min_value=Decimal("0.1"),
        max_value=150,
        max_digits=4,
        decimal_places=1,
    )
    magazyn_koszt_eur = forms.DecimalField(
        label="Cena magazynu [EUR]",
        min_value=0,
        max_value=10000000,
        max_digits=10,
        decimal_places=2,
    )

    def __init__(self, *args, lang: str = "pl", **kwargs):
        super().__init__(*args, **kwargs)
        self.lang = lang
        if lang == "en":
            self.fields["kwp"].label = "PV capacity [kWp]"
            self.fields["miesiac"].label = "Chart month"
            self.fields["miesiac"].choices = MONTH_CHOICES_EN
            self.fields["magazyn_kwh"].label = "Battery capacity [kWh]"
            self.fields["magazyn_moc_kw"].label = "Battery power [kW]"
            self.fields["magazyn_koszt_eur"].label = "Battery price [EUR]"
        else:
            self.fields["kwp"].label = "Moc instalacji [kWp]"
            self.fields["miesiac"].label = "Miesiąc wykresu"
            self.fields["miesiac"].choices = MONTH_CHOICES_PL
            self.fields["magazyn_kwh"].label = "Pojemność magazynu [kWh]"
            self.fields["magazyn_moc_kw"].label = "Moc magazynu [kW]"
            self.fields["magazyn_koszt_eur"].label = "Cena magazynu [EUR]"

    def clean(self):
        """Waliduje ceny i pojemność magazynu, aby zapobiec sprzecznym parametrom."""
        cleaned = super().clean()
        capacity = cleaned.get("magazyn_kwh")
        cost = cleaned.get("magazyn_koszt_eur")
        if capacity is not None and cost is not None:
            if capacity > 0 and cost <= 0:
                err = (
                    "Enter a battery purchase price above zero."
                    if self.lang == "en"
                    else "Podaj dodatnią cenę zakupu magazynu."
                )
                self.add_error("magazyn_koszt_eur", err)
            elif capacity == 0 and cost > 0:
                err = (
                    "With 0 kWh capacity, the price must be zero."
                    if self.lang == "en"
                    else "Przy pojemności 0 kWh cena musi wynosić 0."
                )
                self.add_error("magazyn_koszt_eur", err)
        return cleaned
