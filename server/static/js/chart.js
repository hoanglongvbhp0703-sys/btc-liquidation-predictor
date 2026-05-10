// chart.js — Lightweight Charts: nến 1m + liq zone lines + liq event markers + click tooltip

const ChartModule = (() => {
  let _chart, _candleSeries, _upperLine, _lowerLine;
  let _lastBar      = null;
  let _currentMinute = null;
  let _liqData      = [];   // raw liq events cho click lookup
  let _tooltip      = null; // tooltip DOM element

  function init() {
    const el = document.getElementById('chart');

    _chart = LightweightCharts.createChart(el, {
      layout: {
        background: { color: '#0d1117' },
        textColor:  '#8b949e',
      },
      grid: {
        vertLines: { color: '#21262d' },
        horzLines: { color: '#21262d' },
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: {
        borderColor:  '#21262d',
        scaleMargins: { top: 0.08, bottom: 0.08 },
      },
      timeScale: {
        borderColor:    '#21262d',
        timeVisible:    true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale:  true,
    });

    _candleSeries = _chart.addCandlestickSeries({
      upColor:         '#3fb950',
      downColor:       '#f85149',
      borderUpColor:   '#3fb950',
      borderDownColor: '#f85149',
      wickUpColor:     '#3fb950',
      wickDownColor:   '#f85149',
    });

    _upperLine = _chart.addLineSeries({
      color:            '#f85149',
      lineWidth:        1,
      lineStyle:        LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    _lowerLine = _chart.addLineSeries({
      color:            '#3fb950',
      lineWidth:        1,
      lineStyle:        LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    // Tạo tooltip DOM
    _tooltip = document.createElement('div');
    _tooltip.id = 'liq-tooltip';
    _tooltip.style.cssText = [
      'position:absolute', 'display:none', 'z-index:200',
      'background:#1c2128', 'border:1px solid #30363d',
      'border-radius:6px', 'padding:8px 12px',
      'font-size:12px', 'color:#c9d1d9',
      'pointer-events:none', 'line-height:1.6',
      'box-shadow:0 4px 16px rgba(0,0,0,.5)',
    ].join(';');
    el.style.position = 'relative';
    el.appendChild(_tooltip);

    // Click handler — tìm liq gần nhất theo time
    _chart.subscribeClick((param) => {
      if (!param.time || !_liqData.length) {
        _hideTooltip();
        return;
      }

      const clickedTime = param.time; // Unix seconds

      let best = null;
      let bestDist = Infinity;
      for (const liq of _liqData) {
        const liqTime = Math.floor(new Date(liq.ts).getTime() / 1000);
        const dist    = Math.abs(liqTime - clickedTime);
        if (dist < bestDist) { bestDist = dist; best = liq; }
      }

      // Chỉ show nếu click trong vòng 90 giây so với liq gần nhất
      if (bestDist <= 90 && best) {
        _showTooltip(best, param.point, el);
      } else {
        _hideTooltip();
      }
    });

    // Resize
    const ro = new ResizeObserver(() => {
      _chart.resize(el.offsetWidth, el.offsetHeight);
    });
    ro.observe(el);
  }

  function _showTooltip(liq, point, container) {
    const isLong  = liq.side === 'SELL'; // SELL = LONG bị quét
    const label   = isLong ? '🔴 LONG liquidated' : '🟢 SHORT liquidated';
    const pushed  = isLong ? '→ giá bị đẩy XUỐNG' : '→ giá bị đẩy LÊN';
    const usd     = Number(liq.usd_value).toLocaleString('en-US', { maximumFractionDigits: 0 });
    const price   = Number(liq.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const time    = new Date(liq.ts).toUTCString().slice(17, 25) + ' UTC';

    _tooltip.innerHTML = `
      <div style="font-weight:700;margin-bottom:4px">${label}</div>
      <div>Giá bị quét : <b>$${price}</b></div>
      <div>USD value   : <b>$${usd}</b></div>
      <div>Thời điểm   : ${time}</div>
      <div style="color:#8b949e;font-size:11px;margin-top:4px">${pushed}</div>`;

    // Đặt vị trí tooltip, tránh tràn ra ngoài container
    const cw = container.offsetWidth;
    const ch = container.offsetHeight;
    let x = (point ? point.x : 0) + 12;
    let y = (point ? point.y : 0) - 10;

    _tooltip.style.display = 'block';
    const tw = _tooltip.offsetWidth  || 220;
    const th = _tooltip.offsetHeight || 100;
    if (x + tw > cw - 8) x = (point ? point.x : 0) - tw - 12;
    if (y + th > ch - 8) y = ch - th - 8;
    if (y < 4) y = 4;

    _tooltip.style.left = x + 'px';
    _tooltip.style.top  = y + 'px';
  }

  function _hideTooltip() {
    if (_tooltip) _tooltip.style.display = 'none';
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

    if (bars.length > 0) {
      _lastBar       = { ...bars[bars.length - 1] };
      _currentMinute = bars[bars.length - 1].time;
    }
    _chart.timeScale().scrollToRealTime();
  }

  function updateZones(upper, lower) {
    if (!upper && !lower) return;
    const now  = Math.floor(Date.now() / 1000);
    const past = now - 4 * 3600;

    if (upper) {
      _upperLine.setData([{ time: past, value: upper }, { time: now, value: upper }]);
    }
    if (lower) {
      _lowerLine.setData([{ time: past, value: lower }, { time: now, value: lower }]);
    }
  }

  function updateTick(tick) {
    if (!tick || !tick.price || !tick.ts) return;

    const tSec  = Math.floor(new Date(tick.ts).getTime() / 1000);
    const tMin  = Math.floor(tSec / 60) * 60;
    const price = tick.price;

    if (_currentMinute !== tMin) {
      _currentMinute = tMin;
      _lastBar = { time: tMin, open: price, high: price, low: price, close: price };
    } else if (_lastBar) {
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

    _liqData = liqs; // lưu lại để click lookup

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
