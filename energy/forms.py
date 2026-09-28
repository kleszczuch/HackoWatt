"""Formularze: zakres dat, horyzont prognozy i parametry symulatora PV."""

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
        max_value=15,
        max_digits=4,
        decimal_places=1,
    )
    miesiac = forms.ChoiceField(label="Miesiąc wykresu", choices=MONTH_CHOICES)
