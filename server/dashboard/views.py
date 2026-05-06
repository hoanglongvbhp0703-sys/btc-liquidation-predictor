import math
import json
from django.http import JsonResponse
from django.shortcuts import render
from .data_reader import (
    load_klines_chart, load_liquidations,
    load_trades, load_signal_state,
)


def _sanitize(obj):
    """Đệ quy thay NaN/Inf → None để JSON hợp lệ."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def index(request):
    return render(request, "dashboard/index.html")


def test_page(request):
    from django.http import HttpResponse
    return HttpResponse("""<!DOCTYPE html>
<html><body style="font:16px sans-serif;padding:20px;background:#111;color:#eee">
<div id="r">Testing JS...</div>
<script>
document.getElementById('r').innerHTML = '✅ JS OK<br>';
fetch('/api/signal/')
  .then(r=>r.json())
  .then(d=>{ document.getElementById('r').innerHTML += '✅ API OK: price=' + d.current_price + '<br>'; })
  .catch(e=>{ document.getElementById('r').innerHTML += '❌ API fail: ' + e + '<br>'; });
fetch('/api/klines/?hours=2')
  .then(r=>r.json())
  .then(d=>{ document.getElementById('r').innerHTML += '✅ Klines: ' + d.length + ' rows<br>'; })
  .catch(e=>{ document.getElementById('r').innerHTML += '❌ Klines fail: ' + e + '<br>'; });
</script></body></html>""")


def api_klines(request):
    hours = int(request.GET.get("hours", 2))
    hours = max(1, min(hours, 24))
    data  = load_klines_chart(hours=hours)
    return JsonResponse(data, safe=False)


def api_signal(request):
    data = _sanitize(load_signal_state())
    return JsonResponse(data)


def api_trades(request):
    limit = int(request.GET.get("limit", 30))
    data  = load_trades(limit=limit)
    return JsonResponse(data, safe=False)


def api_liq(request):
    hours = int(request.GET.get("hours", 4))
    data  = load_liquidations(hours=hours)
    return JsonResponse(data, safe=False)
