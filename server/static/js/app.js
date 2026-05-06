// app.js — Entry point: init modules, kết nối WebSocket, dispatch tick

(async () => {

  // ── Init modules ──────────────────────────────────────────────
  ChartModule.init();
  SignalModule.init();

  // ── Load historical data ──────────────────────────────────────
  try {
    const [klinesRes, liqRes] = await Promise.all([
      fetch('/api/klines/?hours=2'),
      fetch('/api/liq/?hours=4'),
    ]);
    const klines = await klinesRes.json();
    const liqs   = await liqRes.json();

    ChartModule.loadHistory(klines);
    ChartModule.addLiqMarkers(liqs);
  } catch (e) {
    console.error('Initial load error:', e);
  }

  // Load trades (bảng + mini stats)
  await TradesModule.load();

  // ── WebSocket ─────────────────────────────────────────────────
  const wsStatus  = document.getElementById('ws-status');
  const liveDot   = document.getElementById('live-dot');
  let   ws        = null;
  let   reconnect = 0;

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws/tick/`);

    ws.onopen = () => {
      reconnect = 0;
      wsStatus.textContent  = 'Live';
      liveDot.className     = 'live-dot';
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

      // ── Giá header ───────────────────────────────────────────
      if (tick.price !== null) {
        const priceEl  = document.getElementById('price');
        const changeEl = document.getElementById('price-change');
        const prev     = parseFloat(priceEl.dataset.raw || tick.price);

        priceEl.textContent  = '$' + Number(tick.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        priceEl.dataset.raw  = tick.price;

        if (tick.price_change_pct !== null) {
          const pct = tick.price_change_pct;
          changeEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(3) + '%';
          changeEl.className   = 'change ' + (pct > 0 ? 'up' : pct < 0 ? 'down' : 'neutral');
        }
      }

      // ── Liq zones header + chart ─────────────────────────────
      if (tick.liq_upper) {
        document.getElementById('liq-upper').textContent =
          '$' + Number(tick.liq_upper).toLocaleString('en-US', { maximumFractionDigits: 0 });
      }
      if (tick.liq_lower) {
        document.getElementById('liq-lower').textContent =
          '$' + Number(tick.liq_lower).toLocaleString('en-US', { maximumFractionDigits: 0 });
      }
      ChartModule.updateZones(tick.liq_upper, tick.liq_lower);

      // ── Chart tick ───────────────────────────────────────────
      ChartModule.updateTick(tick);

      // ── Signal panel ─────────────────────────────────────────
      SignalModule.onTick(tick);
    };
  }

  connect();

  // ── Reload trades mỗi 30s ────────────────────────────────────
  setInterval(() => TradesModule.load(), 30000);

})();
