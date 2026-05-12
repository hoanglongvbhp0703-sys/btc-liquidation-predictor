// chart.js — Lightweight Charts: nến + liq zone lines + liq markers + click tooltip

const ChartModule = (() => {
  let _chart, _candleSeries;
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
        barSpacing:     6,
        minBarSpacing:  3,
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

  let _historyStart = null;  // Unix seconds của nến đầu tiên

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

    _historyStart  = bars[0].time;
    _lastBar       = { ...bars[bars.length - 1] };
    _currentMinute = bars[bars.length - 1].time;

    // Cập nhật label timeframe
    const tfLabel = document.getElementById('tf-label');
    if (tfLabel && klines[0] && klines[0].tf) {
      const tfMap = { '1min': '1M', '5min': '5M', '15min': '15M' };
      tfLabel.textContent = tfMap[klines[0].tf] || klines[0].tf;
    }

    _chart.timeScale().fitContent();
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

    _liqData = liqs;

    // Gộp theo phút (trùng timestamp trong cùng 1 phút → lấy USD lớn nhất)
    const buckets = {};
    for (const l of liqs) {
      const tMin = Math.floor(new Date(l.ts).getTime() / 60000) * 60;
      const key  = `${tMin}_${l.side}`;
      if (!buckets[key] || l.usd_value > buckets[key].usd) {
        buckets[key] = { time: tMin, side: l.side, usd: l.usd_value, ts: l.ts };
      }
    }

    const markers = Object.values(buckets).map(b => {
      const isLong = b.side === 'SELL'; // SELL = long bị quét → đỏ, từ trên xuống
      return {
        time:     b.time,
        position: isLong ? 'aboveBar' : 'belowBar',
        color:    isLong ? '#f85149' : '#3fb950',
        shape:    'circle',
        size:     b.usd >= 500000 ? 1.2 : b.usd >= 100000 ? 0.7 : 0.3,
        text:     '',
      };
    });
    markers.sort((a, b) => a.time - b.time);
    _candleSeries.setMarkers(markers);
  }

  return { init, loadHistory, updateTick, addLiqMarkers };
})();
