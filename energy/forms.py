"""Formularze: zakres dat, horyzont prognozy i parametry symulatora PV."""

from decimal import Decimal

from django import forms

HORIZON_CHOICES = (("24", "24 hours"), ("72", "3 days"), ("168", "7 days"))
MONTH_CHOICES = tuple(
    (str(number), name)
    for number, name in enumerate(
        (
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
        ),
        start=1,
    )
)


class DateRangeForm(forms.Form):
    start = forms.DateField(label="From", widget=forms.DateInput(attrs={"type": "date"}))
    end = forms.DateField(label="To", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start")
        end = cleaned.get("end")
        if start and end and end < start:
            raise forms.ValidationError("The end date cannot be earlier than the start date.")
        return cleaned


class HorizonForm(forms.Form):
    horyzont = forms.ChoiceField(
        label="Forecast horizon",
        choices=HORIZON_CHOICES,
        widget=forms.Select(),
    )


class PvForm(forms.Form):
    kwp = forms.DecimalField(
        label="PV capacity [kWp]",
        min_value=1,
        max_value=150,
        max_digits=4,
        decimal_places=1,
    )
    miesiac = forms.ChoiceField(label="Chart month", choices=MONTH_CHOICES)
    magazyn_kwh = forms.DecimalField(
        label="Battery capacity [kWh]",
        min_value=0,
        max_value=5000,
        max_digits=5,
        decimal_places=1,
    )
    magazyn_moc_kw = forms.DecimalField(
        label="Battery power [kW]",
        min_value=Decimal("0.1"),
        max_value=150,
        max_digits=4,
        decimal_places=1,
    )
    magazyn_koszt_eur = forms.DecimalField(
        label="Battery price [EUR]",
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
                self.add_error("magazyn_koszt_eur", "Enter a battery purchase price above zero.")
            elif capacity == 0 and cost > 0:
                self.add_error("magazyn_koszt_eur", "With 0 kWh capacity, the price must be zero.")
        return cleaned
