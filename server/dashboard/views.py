import math
from django.http import JsonResponse
from django.shortcuts import render
from .data_reader import (
    load_klines_chart, load_liquidations,
    load_trades, load_signal_state,
)


def _sanitize(obj):
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def index(request):
    return render(request, "dashboard/index.html")


def api_klines(request):
    hours = max(0, int(request.GET.get("hours", 0)))
    return JsonResponse(load_klines_chart(hours=hours), safe=False)


def api_signal(request):
    return JsonResponse(_sanitize(load_signal_state()))


def api_trades(request):
    limit = int(request.GET.get("limit", 30))
    return JsonResponse(load_trades(limit=limit), safe=False)


def api_liq(request):
    hours = int(request.GET.get("hours", 4))
    return JsonResponse(load_liquidations(hours=hours), safe=False)
