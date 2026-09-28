from django.db import models
from django.utils import timezone


class Scenario(models.Model):
    name = models.CharField(max_length=100, verbose_name="Nazwa scenariusza")
    location = models.CharField(max_length=100, default="Katowice, Poland", verbose_name="Lokalizacja")
    latitude = models.FloatField(default=50.2649, verbose_name="Szerokość geograficzna")
    longitude = models.FloatField(default=19.0238, verbose_name="Długość geograficzna")
    residents_count = models.IntegerField(default=4, verbose_name="Liczba mieszkańców")
    description = models.TextField(blank=True, verbose_name="Opis")

    def __str__(self):
        return f"{self.name} ({self.location})"


class HourlyEnergyRecord(models.Model):
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="energy_records")
    timestamp = models.DateTimeField(db_index=True, verbose_name="Data i Godzina")
    is_forecast = models.BooleanField(default=False, db_index=True, verbose_name="Czy to prognoza?")
    
    temperature = models.FloatField(null=True, blank=True, verbose_name="Temperatura [°C]")
    solar_radiation = models.FloatField(null=True, blank=True, verbose_name="Promieniowanie [W/m²]")

    base_kwh = models.DecimalField(max_digits=6, decimal_places=3, default=0.0)
    heating_kwh = models.DecimalField(max_digits=6, decimal_places=3, default=0.0)
    lighting_kwh = models.DecimalField(max_digits=6, decimal_places=3, default=0.0)
    cooking_kwh = models.DecimalField(max_digits=6, decimal_places=3, default=0.0)
    multimedia_kwh = models.DecimalField(max_digits=6, decimal_places=3, default=0.0)
    appliances_kwh = models.DecimalField(max_digits=6, decimal_places=3, default=0.0)
    special_kwh = models.DecimalField(max_digits=6, decimal_places=3, default=0.0)
    total_kwh = models.DecimalField(max_digits=7, decimal_places=3)
    events = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["scenario", "timestamp"]),
            models.Index(fields=["is_forecast", "timestamp"]),
        ]
        ordering = ["timestamp"]


class PVSimulationConfig(models.Model):
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="pv_simulations")
    created_at = models.DateTimeField(default=timezone.now)
    kwp = models.DecimalField(max_digits=5, decimal_places=2)
    battery_kwh = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    annual_production_kwh = models.FloatField()
    coverage_a_percent = models.FloatField()
    coverage_b_percent = models.FloatField()
    savings_a_eur = models.FloatField()
    savings_b_eur = models.FloatField()
    payback_a_years = models.FloatField(null=True, blank=True)
    payback_b_years = models.FloatField(null=True, blank=True)