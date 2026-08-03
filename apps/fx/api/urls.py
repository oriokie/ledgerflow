from django.urls import path

from .views import ConvertView, CurrencyListView, RatesView

urlpatterns = [
    path("currencies/", CurrencyListView.as_view(), name="fx-currencies"),
    path("rates/", RatesView.as_view(), name="fx-rates"),
    path("convert/", ConvertView.as_view(), name="fx-convert"),
]
