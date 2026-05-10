// signal.js — Signal panel + prob bar (LONG & SHORT) + prob curve + countdown + alert

const SignalModule = (() => {
  let _lastSignalTs  = null;
  let _lastShortTs   = null;
  let _countdownTimer = null;

  let _cvdChart   = null;
  let _curveChart = null;
  const _cvdHistory = [];
  const CVD_MAX = 40;
  let _cvdBase = null;

  const CURVE_LABELS  = ['+5m', '+10m', '+15m', '+20m', '+25m', '+30m'];
  const CURVE_HORIZONS = [5, 10, 15, 20, 25, 30];

  function _initCvdChart() {
    const ctx = document.getElementById('cvd-chart').getContext('2d');
    _cvdChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: [],
        datasets: [{
          data: [],
          borderWidth: 1.5,
          borderColor: 'rgba(63,185,80,0.85)',
          backgroundColor: 'rgba(63,185,80,0.08)',
          fill: true,
          tension: 0.35,
          pointRadius: 0,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { display: false },
          y: { display: false, grid: { display: false } },
        },
      },
    });
  }

  function _initCurveChart() {
    const canvas = document.getElementById('curve-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    _curveChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: CURVE_LABELS,
        datasets: [
          {
            label: 'LONG',
            data: [null, null, null, null, null, null],
            borderColor: 'rgba(63,185,80,0.9)',
            backgroundColor: 'rgba(63,185,80,0.08)',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: 'rgba(63,185,80,0.9)',
            fill: false,
            tension: 0.35,
            spanGaps: true,
          },
          {
            label: 'SHORT',
            data: [null, null, null, null, null, null],
            borderColor: 'rgba(248,81,73,0.9)',
            backgroundColor: 'rgba(248,81,73,0.08)',
            borderWidth: 2,
            pointRadius: 3,
            pointBackgroundColor: 'rgba(248,81,73,0.9)',
            fill: false,
            tension: 0.35,
            spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: true,
            mode: 'index',
            intersect: false,
            backgroundColor: '#161b22',
            borderColor: '#21262d',
            borderWidth: 1,
            titleColor: '#8b949e',
            bodyColor: '#c9d1d9',
            callbacks: {
              label: (item) => {
                const v = item.raw;
                if (v === null || v === undefined) return null;
                const color = item.datasetIndex === 0 ? '▲' : '▼';
                return `${color} ${(v * 100).toFixed(1)}%`;
              },
            },
          },
        },
        scales: {
          x: {
            display: false,
          },
          y: {
            display: true,
            min: 0,
            max: 1,
            grid: { color: 'rgba(33,38,45,0.8)', drawTicks: false },
            border: { display: false },
            ticks: {
              color: '#8b949e',
              font: { size: 9 },
              maxTicksLimit: 3,
              callback: (v) => Math.round(v * 100) + '%',
              padding: 2,
            },
          },
        },
        layout: { padding: { left: 2, right: 4, top: 4, bottom: 0 } },
      },
    });
  }

  function _updateCurveChart(curveLong, curveShort) {
    if (!_curveChart) return;

    const toArr = (curve) =>
      CURVE_HORIZONS.map(h => (curve && curve[h] !== undefined ? curve[h] : null));

    _curveChart.data.datasets[0].data = toArr(curveLong);
    _curveChart.data.datasets[1].data = toArr(curveShort);
    _curveChart.update('none');
  }

  function _updateCvdChart(cvd) {
    if (cvd === null || cvd === undefined) return;

    if (_cvdBase === null) _cvdBase = 0;
    _cvdBase += cvd;
    _cvdHistory.push(_cvdBase);
    if (_cvdHistory.length > CVD_MAX) _cvdHistory.shift();

    const trend = _cvdHistory[_cvdHistory.length - 1] - _cvdHistory[0];
    const col = trend >= 0 ? 'rgba(63,185,80,0.85)' : 'rgba(248,81,73,0.85)';
    const bg  = trend >= 0 ? 'rgba(63,185,80,0.08)' : 'rgba(248,81,73,0.08)';
    _cvdChart.data.datasets[0].borderColor     = col;
    _cvdChart.data.datasets[0].backgroundColor = bg;
    _cvdChart.data.labels                      = _cvdHistory.map((_, i) => i);
    _cvdChart.data.datasets[0].data            = _cvdHistory;
    _cvdChart.update('none');

    const el = document.getElementById('cvd-value');
    el.textContent = cvd >= 0 ? `+${cvd.toFixed(1)}` : cvd.toFixed(1);
    el.className   = 'cvd-value ' + (cvd >= 0 ? 'pos' : 'neg');
  }

  function _updateImbalance(imb) {
    if (imb === null || imb === undefined) return;
    const pct = Math.round(imb * 100);
    document.getElementById('imb-pct').textContent     = pct + '%';
    document.getElementById('imbalance').textContent   = pct + '%';
    document.getElementById('imb-marker').style.left   = pct + '%';
  }

  function _updateMiniStats(tick) {
    if (tick.dist_upper_pct !== undefined && tick.dist_upper_pct !== null) {
      document.getElementById('dist-upper').textContent =
        (tick.dist_upper_pct * 100).toFixed(2) + '%';
    }
    if (tick.funding_rate !== undefined && tick.funding_rate !== null) {
      const f  = (tick.funding_rate * 100).toFixed(4);
      const el = document.getElementById('funding');
      el.textContent = f + '%';
      el.style.color = tick.funding_rate > 0 ? 'var(--green)' : 'var(--red)';
    }
    if (tick.delta_oi_5m !== undefined && tick.delta_oi_5m !== null) {
      const d  = (tick.delta_oi_5m * 100).toFixed(3);
      const el = document.getElementById('delta-oi');
      el.textContent = (tick.delta_oi_5m >= 0 ? '+' : '') + d + '%';
      el.style.color = tick.delta_oi_5m >= 0 ? 'var(--green)' : 'var(--red)';
    }
  }

  function _updateProbBar(elBar, elVal, prob, isShort, hasSignal) {
    const pct = prob !== null && prob !== undefined ? Math.round(prob * 100) : 0;
    elBar.style.width = pct + '%';
    elVal.textContent = prob !== null && prob !== undefined ? pct + '%' : '---%';

    if (isShort) {
      elBar.className = 'prob-bar prob-bar-short';
      if (hasSignal)   elBar.classList.add('signal');
      else if (pct>=60) elBar.classList.add('high');
    } else {
      elBar.className = 'prob-bar';
      if (hasSignal)   elBar.classList.add('signal');
      else if (pct>=60) elBar.classList.add('high');
    }
  }

  function _formatPrice(p) {
    if (p === null || p === undefined) return '---';
    return '$' + Number(p).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function _startCountdown(openedAt) {
    if (_countdownTimer) clearInterval(_countdownTimer);
    const endTime = new Date(openedAt).getTime() + 30 * 60 * 1000;

    _countdownTimer = setInterval(() => {
      const left = Math.max(0, endTime - Date.now());
      const mm   = Math.floor(left / 60000);
      const ss   = Math.floor((left % 60000) / 1000);
      const el   = document.getElementById('countdown-timer');
      if (el) el.textContent = `${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;
      if (left === 0) clearInterval(_countdownTimer);
    }, 1000);
  }

  function _signalRows(signal) {
    const isLong  = !signal.signal || signal.signal === 'LONG';
    const color   = isLong ? 'var(--green)' : 'var(--red)';
    const arrow   = isLong ? '▲' : '▼';
    const label   = isLong ? 'LONG' : 'SHORT';

    return `
      <div class="signal-active">
        <div class="sig-row">
          <span class="sig-lbl">Signal</span>
          <span class="sig-val" style="color:${color}">${arrow} ${label}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">Entry</span>
          <span class="sig-val sig-entry">${_formatPrice(signal.entry)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">TP <span style="font-size:10px;color:var(--muted)">(Liq ${isLong ? 'Upper' : 'Lower'})</span></span>
          <span class="sig-val sig-tp">${_formatPrice(signal.tp)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">SL <span style="font-size:10px;color:var(--muted)">(Liq ${isLong ? 'Lower' : 'Upper'})</span></span>
          <span class="sig-val sig-sl">${_formatPrice(signal.sl)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">R:R</span>
          <span class="sig-val sig-rr">${Number(signal.rr).toFixed(2)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">Prob</span>
          <span class="sig-val sig-prob">${Math.round(signal.prob * 100)}%</span>
        </div>
        <div class="countdown" style="${isLong ? '' : 'border-color:rgba(248,81,73,.3);background:rgba(248,81,73,.08);color:var(--red)'}">
          Đóng sau <span class="timer" id="countdown-timer">30:00</span>
        </div>
      </div>`;
  }

  function _renderSignalPanel(sigLong, sigShort) {
    const el = document.getElementById('signal-info');

    const activeSig  = sigLong || sigShort;
    const isNewLong  = sigLong  && sigLong.opened_at  !== _lastSignalTs;
    const isNewShort = sigShort && sigShort.opened_at !== _lastShortTs;

    if (!activeSig) {
      el.innerHTML = '<div class="no-signal">Chưa có signal</div>';
      if (_countdownTimer) { clearInterval(_countdownTimer); _countdownTimer = null; }
      return;
    }

    el.innerHTML = _signalRows(activeSig);
    _startCountdown(activeSig.opened_at || new Date().toISOString());

    if (isNewLong) {
      _lastSignalTs = sigLong.opened_at;
      _showAlert(sigLong);
      _browserNotify(sigLong);
    }
    if (isNewShort) {
      _lastShortTs = sigShort.opened_at;
      _showAlert(sigShort);
      _browserNotify(sigShort);
    }
  }

  function _showAlert(signal) {
    const isLong = !signal.signal || signal.signal === 'LONG';
    const popup  = document.getElementById('alert-popup');
    const icon   = document.querySelector('.alert-icon');
    const title  = document.querySelector('.alert-title');

    if (icon)  icon.textContent  = isLong ? '🚀' : '🔻';
    if (title) title.textContent = `BTC ${isLong ? 'LONG' : 'SHORT'} SIGNAL`;

    document.getElementById('alert-detail').innerHTML =
      `Entry <b>${_formatPrice(signal.entry)}</b> → TP <b>${_formatPrice(signal.tp)}</b><br>` +
      `SL ${_formatPrice(signal.sl)} | R:R ${Number(signal.rr).toFixed(2)} | Prob ${Math.round(signal.prob*100)}%`;
    popup.classList.add('show');
    setTimeout(() => popup.classList.remove('show'), 10000);
  }

  function _browserNotify(signal) {
    if (!('Notification' in window)) return;
    const isLong = !signal.signal || signal.signal === 'LONG';
    const title  = isLong ? '🚀 BTC LONG Signal!' : '🔻 BTC SHORT Signal!';
    if (Notification.permission === 'granted') {
      new Notification(title, {
        body: `Entry: ${_formatPrice(signal.entry)}  TP: ${_formatPrice(signal.tp)}  R:R ${Number(signal.rr).toFixed(2)}`,
      });
    } else if (Notification.permission !== 'denied') {
      Notification.requestPermission().then(p => {
        if (p === 'granted') _browserNotify(signal);
      });
    }
  }

  function onTick(tick) {
    const probLong  = tick.prob_long  ?? tick.prob ?? null;
    const probShort = tick.prob_short ?? null;
    const sigLong   = tick.signal_long  ?? tick.signal ?? null;
    const sigShort  = tick.signal_short ?? null;

    // Prob bars (30m snapshot)
    const barLong = document.getElementById('prob-bar-long');
    const valLong = document.getElementById('prob-value-long');
    if (barLong && valLong) _updateProbBar(barLong, valLong, probLong, false, !!sigLong);

    const barShort = document.getElementById('prob-bar-short');
    const valShort = document.getElementById('prob-value-short');
    if (barShort && valShort) _updateProbBar(barShort, valShort, probShort, true, !!sigShort);

    // Prob curve chart
    _updateCurveChart(tick.prob_curve_long ?? null, tick.prob_curve_short ?? null);

    _updateImbalance(tick.imbalance);
    _updateMiniStats(tick);
    if (tick.cvd_5m !== undefined) _updateCvdChart(tick.cvd_5m);
    _renderSignalPanel(sigLong, sigShort);
  }

  function _ensureProbBars() {
    if (document.getElementById('prob-bar-long')) return;

    const oldBlock = document.querySelector('.prob-block');
    if (!oldBlock) return;

    oldBlock.outerHTML = `
      <div class="prob-block">
        <div class="prob-label">
          <span style="color:var(--green)">▲ LONG</span>
          — chạm Liq Upper <span class="prob-window">30p</span>
        </div>
        <div class="prob-bar-wrap">
          <div class="prob-bar" id="prob-bar-long"></div>
        </div>
        <div class="prob-value" id="prob-value-long">---%</div>
      </div>
      <div class="prob-block" style="margin-top:4px">
        <div class="prob-label">
          <span style="color:var(--red)">▼ SHORT</span>
          — chạm Liq Lower <span class="prob-window">30p</span>
        </div>
        <div class="prob-bar-wrap">
          <div class="prob-bar prob-bar-short" id="prob-bar-short"></div>
        </div>
        <div class="prob-value" id="prob-value-short">---%</div>
      </div>`;
  }

  function init() {
    _ensureProbBars();
    _initCvdChart();
    _initCurveChart();
    document.addEventListener('click', () => {
      if (Notification.permission === 'default') Notification.requestPermission();
    }, { once: true });
  }

  return { init, onTick };
})();
