from django.urls import path
from . import views

urlpatterns = [
    path("",              views.index,      name="index"),
    path("api/klines/",   views.api_klines, name="api_klines"),
    path("api/signal/",   views.api_signal, name="api_signal"),
    path("api/trades/",   views.api_trades, name="api_trades"),
    path("api/liq/",          views.api_liq,         name="api_liq"),
    path("api/cvd-history/",  views.api_cvd_history, name="api_cvd_history"),
]
