"""Walidacja zakresu dat używanego przez wykresy, tabelę i eksport."""

from django import forms


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
