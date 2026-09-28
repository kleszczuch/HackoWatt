'''Plik definiuje konfigurację aplikacji Django dla modułu energy.'''

from django.apps import AppConfig


class EnergyConfig(AppConfig):
    '''
    Klasa EnergyConfig dziedziczy po AppConfig i pełni rolę rejestracji aplikacji
    w systemie Django. Dzięki temu projekt wie, że aplikacja o nazwie "energy"
    istnieje i ma być uwzględniona w INSTALLED_APPS w ustawieniach projektu.
    '''
    default_auto_field = "django.db.models.BigAutoField"
    name = "energy"
