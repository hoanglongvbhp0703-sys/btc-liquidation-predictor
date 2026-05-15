// app.js — Entry point: init modules, kết nối WebSocket, dispatch tick

(async () => {

  ChartModule.init();
  SignalModule.init();

  // ── Load historical data ──────────────────────────────────
  try {
    const [klinesRes, liqRes] = await Promise.all([
      fetch('/api/klines/'),
      fetch('/api/liq/?hours=9999'),
    ]);
    const klines = await klinesRes.json();
    const liqs   = await liqRes.json();

    ChartModule.loadHistory(klines);
    ChartModule.addLiqMarkers(liqs);
  } catch (e) {
    console.error('Initial load error:', e);
  }

  await TradesModule.load();

  // ── WebSocket ─────────────────────────────────────────────
  const wsStatus  = document.getElementById('ws-status');
  const liveDot   = document.getElementById('live-dot');
  let   ws        = null;
  let   reconnect = 0;

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/tick/`);

    ws.onopen = () => {
      reconnect = 0;
      wsStatus.textContent = 'Live';
      liveDot.className    = 'live-dot';
    };

    ws.onclose = () => {
      wsStatus.textContent = 'Reconnecting...';
      liveDot.className    = 'live-dot disconnected';
      const delay = Math.min(1000 * Math.pow(2, reconnect++), 30000);
      setTimeout(connect, delay);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = (evt) => {
      let tick;
      try { tick = JSON.parse(evt.data); } catch { return; }

      // ── Price header ─────────────────────────────────────
      if (tick.price !== null) {
        const priceEl  = document.getElementById('price');
        const changeEl = document.getElementById('price-change');

        priceEl.textContent = '$' + Number(tick.price).toLocaleString('en-US', {
          minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
        priceEl.dataset.raw = tick.price;

        if (tick.price_change_pct !== null) {
          const pct = tick.price_change_pct;
          changeEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(3) + '%';
          changeEl.className   = 'change ' + (pct > 0 ? 'up' : pct < 0 ? 'down' : 'neutral');
        }
      }

      // ── Chart tick ───────────────────────────────────────
      ChartModule.updateTick(tick);

      // ── Signal panel ─────────────────────────────────────
      SignalModule.onTick(tick);
    };
  }

  connect();

  setInterval(() => TradesModule.load(), 30000);

  // Refresh liq markers mỗi 5 phút — thêm liquidation mới + tránh mất markers
  setInterval(async () => {
    try {
      const r    = await fetch('/api/liq/?hours=9999');
      const liqs = await r.json();
      ChartModule.addLiqMarkers(liqs);
    } catch (e) {
      console.error('liq refresh error:', e);
    }
  }, 5 * 60 * 1000);

})();
