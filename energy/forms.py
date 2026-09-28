"""Formularze: zakres dat, horyzont prognozy i parametry symulatora PV."""

from decimal import Decimal

from django import forms

HORIZON_CHOICES = (("24", "24 godziny"), ("72", "3 dni"), ("168", "7 dni"))
MONTH_CHOICES = tuple(
    (str(number), name)
    for number, name in enumerate(
        (
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
        ),
        start=1,
    )
)


class DateRangeForm(forms.Form):
    start = forms.DateField(label="Od", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="Do", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start")
        end = cleaned.get("end")
        if start and end and end < start:
            raise forms.ValidationError("Data końcowa nie może być wcześniejsza niż początkowa.")
        return cleaned


class HorizonForm(forms.Form):
    horyzont = forms.ChoiceField(
        label="Horyzont prognozy",
        choices=HORIZON_CHOICES,
        widget=forms.Select(),
    )


class PvForm(forms.Form):
    kwp = forms.DecimalField(
        label="Moc instalacji [kWp]",
        min_value=1,
        max_value=150,
        max_digits=4,
        decimal_places=1,
    )
    miesiac = forms.ChoiceField(label="Miesiąc wykresu", choices=MONTH_CHOICES)
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

    def clean(self):
        cleaned = super().clean()
        capacity = cleaned.get("magazyn_kwh")
        cost = cleaned.get("magazyn_koszt_eur")
        if capacity is not None and cost is not None:
            if capacity > 0 and cost <= 0:
                self.add_error("magazyn_koszt_eur", "Podaj dodatnią cenę zakupu magazynu.")
            elif capacity == 0 and cost > 0:
                self.add_error("magazyn_koszt_eur", "Przy pojemności 0 kWh cena musi wynosić 0.")
        return cleaned
