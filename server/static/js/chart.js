// chart.js — Lightweight Charts: nến 1m + liq zone lines + liq event markers

const ChartModule = (() => {
  let _chart, _candleSeries, _upperLine, _lowerLine;
  let _lastBar = null;    // bar đang update real-time (chưa confirmed)
  let _currentMinute = null;

  function init() {
    const el = document.getElementById('chart');
    _chart = LightweightCharts.createChart(el, {
      layout: {
        background:  { color: '#0d1117' },
        textColor:   '#8b949e',
      },
      grid: {
        vertLines:  { color: '#21262d' },
        horzLines:  { color: '#21262d' },
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: '#21262d',
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor:    '#21262d',
        timeVisible:    true,
        secondsVisible: false,
      },
      handleScroll:    true,
      handleScale:     true,
    });

    _candleSeries = _chart.addCandlestickSeries({
      upColor:          '#3fb950',
      downColor:        '#f85149',
      borderUpColor:    '#3fb950',
      borderDownColor:  '#f85149',
      wickUpColor:      '#3fb950',
      wickDownColor:    '#f85149',
    });

    // Liq zone lines
    _upperLine = _chart.addLineSeries({
      color:       '#f85149',
      lineWidth:   1,
      lineStyle:   LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    _lowerLine = _chart.addLineSeries({
      color:       '#3fb950',
      lineWidth:   1,
      lineStyle:   LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Resize observer
    const ro = new ResizeObserver(() => {
      _chart.resize(el.offsetWidth, el.offsetHeight);
    });
    ro.observe(el);
  }

  function loadHistory(klines) {
    if (!klines || klines.length === 0) return;

    const bars = klines.map(k => ({
      time:  Math.floor(new Date(k.ts).getTime() / 1000),
      open:  k.open,
      high:  k.high,
      low:   k.low,
      close: k.close,
    }));
    bars.sort((a, b) => a.time - b.time);
    _candleSeries.setData(bars);

    // Set last bar state
    if (bars.length > 0) {
      _lastBar = { ...bars[bars.length - 1] };
      _currentMinute = bars[bars.length - 1].time;
    }
    _chart.timeScale().scrollToRealTime();
  }

  function updateZones(upper, lower) {
    if (!upper && !lower) return;
    const now  = Math.floor(Date.now() / 1000);
    const past = now - 4 * 3600;  // 4 giờ trước

    if (upper) {
      _upperLine.setData([{ time: past, value: upper }, { time: now, value: upper }]);
    }
    if (lower) {
      _lowerLine.setData([{ time: past, value: lower }, { time: lower }]);
      _lowerLine.setData([{ time: past, value: lower }, { time: now, value: lower }]);
    }
  }

  function updateTick(tick) {
    if (!tick || !tick.price || !tick.ts) return;

    const ts    = new Date(tick.ts);
    const tSec  = Math.floor(ts.getTime() / 1000);
    // Làm tròn xuống phút
    const tMin  = Math.floor(tSec / 60) * 60;
    const price = tick.price;

    if (_currentMinute !== tMin) {
      // Phút mới → confirm bar cũ, tạo bar mới
      _currentMinute = tMin;
      _lastBar = {
        time:  tMin,
        open:  price,
        high:  price,
        low:   price,
        close: price,
      };
    } else if (_lastBar) {
      // Cùng phút → update high/low/close
      _lastBar.close = price;
      _lastBar.high  = Math.max(_lastBar.high, price);
      _lastBar.low   = Math.min(_lastBar.low,  price);
    } else {
      _lastBar = { time: tMin, open: price, high: price, low: price, close: price };
    }

    _candleSeries.update(_lastBar);
  }

  function addLiqMarkers(liqs) {
    if (!liqs || liqs.length === 0) return;
    const markers = liqs.map(l => ({
      time:     Math.floor(new Date(l.ts).getTime() / 1000),
      position: l.side === 'BUY' ? 'belowBar' : 'aboveBar',
      color:    l.side === 'BUY' ? '#3fb950' : '#f85149',
      shape:    'circle',
      size:     Math.min(3, Math.max(1, Math.log10(l.usd_value / 10000))),
      text:     '',
    }));
    markers.sort((a, b) => a.time - b.time);
    _candleSeries.setMarkers(markers);
  }

  return { init, loadHistory, updateZones, updateTick, addLiqMarkers };
})();
