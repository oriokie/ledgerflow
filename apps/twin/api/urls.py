from __future__ import annotations

from django.urls import path

from .views import AskView, CalibrationView, TwinView

urlpatterns = [
    path("", TwinView.as_view(), name="twin-detail"),
    path("calibration/", CalibrationView.as_view(), name="twin-calibration"),
    path("ask/", AskView.as_view(), name="twin-ask"),
]
