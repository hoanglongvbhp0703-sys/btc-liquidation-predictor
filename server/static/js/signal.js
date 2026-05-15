// signal.js — Cascade Signal panel: prob bars, timing, curve chart, CVD, imbalance

const SignalModule = (() => {
  let _lastSignalTs   = null;
  let _countdownTimer = null;
  let _cvdChart       = null;
  let _curveChart     = null;

  const _cvdHistory = [];
  const CVD_MAX     = 40;
  let   _cvdBase    = null;

  const CURVE_LABELS   = ['+1m', '+2m', '+3m'];
  const CURVE_HORIZONS = [1, 2, 3];

  // ── CVD chart ─────────────────────────────────────────────

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
          fill: true, tension: 0.35, pointRadius: 0,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { display: false },
          y: { display: false, grid: { display: false } },
        },
      },
    });
  }

  function _updateCvdChart(cvd) {
    if (cvd === null || cvd === undefined) return;
    if (_cvdBase === null) _cvdBase = 0;
    _cvdBase += cvd;
    _cvdHistory.push(_cvdBase);
    if (_cvdHistory.length > CVD_MAX) _cvdHistory.shift();

    const trend = _cvdHistory[_cvdHistory.length - 1] - _cvdHistory[0];
    const col   = trend >= 0 ? 'rgba(63,185,80,0.85)' : 'rgba(248,81,73,0.85)';
    const bg    = trend >= 0 ? 'rgba(63,185,80,0.08)'  : 'rgba(248,81,73,0.08)';
    _cvdChart.data.datasets[0].borderColor     = col;
    _cvdChart.data.datasets[0].backgroundColor = bg;
    _cvdChart.data.labels                      = _cvdHistory.map((_, i) => i);
    _cvdChart.data.datasets[0].data            = _cvdHistory;
    _cvdChart.update('none');

    const el     = document.getElementById('cvd-value');
    el.textContent = cvd >= 0 ? `+${cvd.toFixed(1)}` : cvd.toFixed(1);
    el.className   = 'cvd-value ' + (cvd >= 0 ? 'pos' : 'neg');
  }

  // ── Cascade Probability Curve chart ───────────────────────

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
            data: [null, null, null],
            borderColor: 'rgba(63,185,80,0.9)',
            backgroundColor: 'rgba(63,185,80,0.08)',
            borderWidth: 2, pointRadius: 3,
            pointBackgroundColor: 'rgba(63,185,80,0.9)',
            fill: false, tension: 0.35, spanGaps: true,
          },
          {
            label: 'SHORT',
            data: [null, null, null],
            borderColor: 'rgba(248,81,73,0.9)',
            backgroundColor: 'rgba(248,81,73,0.08)',
            borderWidth: 2, pointRadius: 3,
            pointBackgroundColor: 'rgba(248,81,73,0.9)',
            fill: false, tension: 0.35, spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: {
          legend: { 
            display: true,
            position: 'top',
            labels: {
              color: '#c9d1d9',
              font: { size: 11 },
              padding: 8,
              usePointStyle: true,
            }
          },
          tooltip: {
            enabled: true, mode: 'index', intersect: false,
            backgroundColor: '#161b22', borderColor: '#21262d', borderWidth: 1,
            titleColor: '#8b949e', bodyColor: '#c9d1d9',
            callbacks: {
              label: (item) => {
                const v = item.raw;
                if (v === null || v === undefined) return null;
                return `${item.datasetIndex === 0 ? '▲' : '▼'} ${(v * 100).toFixed(1)}%`;
              },
            },
          },
        },
        scales: {
          x: { display: false },
          y: {
            display: true, min: 0, max: 1,
            grid: { color: 'rgba(33,38,45,0.8)', drawTicks: false },
            border: { display: false },
            ticks: {
              color: '#8b949e', font: { size: 9 }, maxTicksLimit: 3,
              callback: (v) => Math.round(v * 100) + '%', padding: 2,
            },
          },
        },
        layout: { padding: { left: 2, right: 4, top: 4, bottom: 0 } },
      },
    });
  }

  function _updateCurveChart(curveLong, curveShort) {
    if (!_curveChart) return;
    const toArr = (c) => CURVE_HORIZONS.map(h => (c && c[h] !== undefined ? c[h] : null));
    _curveChart.data.datasets[0].data = toArr(curveLong);
    _curveChart.data.datasets[1].data = toArr(curveShort);
    _curveChart.update('none');
  }

  // ── Prob bars ─────────────────────────────────────────────

  function _updateProbBar(barEl, valEl, prob, isShort, hasSignal) {
    const pct = prob !== null && prob !== undefined ? Math.round(prob * 100) : 0;
    barEl.style.width = pct + '%';
    valEl.textContent = prob !== null && prob !== undefined ? pct + '%' : '---%';

    if (isShort) {
      barEl.className = 'prob-bar prob-bar-short';
      if (hasSignal)    barEl.classList.add('signal');
      else if (pct >= 60) barEl.classList.add('high');
    } else {
      barEl.className = 'prob-bar';
      if (hasSignal)    barEl.classList.add('signal');
      else if (pct >= 60) barEl.classList.add('high');
    }
  }

  function _updateTtcBadge(elId, ttcMinutes) {
    const el = document.getElementById(elId);
    if (!el) return;
    if (ttcMinutes === null || ttcMinutes === undefined) {
      el.textContent = '---';
      el.className   = 'ttc-badge';
    } else {
      el.textContent = `~${Math.round(ttcMinutes)}m`;
      el.className   = 'ttc-badge' + (ttcMinutes <= 2 ? ' ttc-urgent' : '');
    }
  }

  // ── Mini stats ────────────────────────────────────────────

  function _updateMiniStats(tick) {
    if (tick.funding_rate !== undefined && tick.funding_rate !== null) {
      const f  = (tick.funding_rate * 100).toFixed(4);
      const el = document.getElementById('funding');
      el.textContent = f + '%';
      el.style.color = tick.funding_rate > 0 ? 'var(--green)' : 'var(--red)';
    }
    if (tick.delta_oi_1m !== undefined && tick.delta_oi_1m !== null) {
      const el = document.getElementById('delta-oi');
      el.textContent = (tick.delta_oi_1m >= 0 ? '+' : '') + (tick.delta_oi_1m * 100).toFixed(3) + '%';
      el.style.color = tick.delta_oi_1m >= 0 ? 'var(--green)' : 'var(--red)';
    }
  }

  function _updateImbalance(imb) {
    if (imb === null || imb === undefined) return;
    const pct = Math.round(imb * 100);
    document.getElementById('imb-pct').textContent   = pct + '%';
    document.getElementById('imbalance').textContent = pct + '%';
    document.getElementById('imb-marker').style.left = pct + '%';
  }

  // ── Signal panel ──────────────────────────────────────────

  function _formatPrice(p) {
    if (p === null || p === undefined) return '---';
    return '$' + Number(p).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function _startCountdown(openedAt) {
    if (_countdownTimer) clearInterval(_countdownTimer);
    const endTime = new Date(openedAt).getTime() + 3 * 60 * 1000;
    _countdownTimer = setInterval(() => {
      const left = Math.max(0, endTime - Date.now());
      const mm   = Math.floor(left / 60000);
      const ss   = Math.floor((left % 60000) / 1000);
      const el   = document.getElementById('countdown-timer');
      if (el) el.textContent = `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
      if (left === 0) clearInterval(_countdownTimer);
    }, 1000);
  }

  function _renderSignalPanel(signal) {
    const el = document.getElementById('signal-info');

    if (!signal) {
      el.innerHTML = '<div class="no-signal">Chưa có signal</div>';
      if (_countdownTimer) { clearInterval(_countdownTimer); _countdownTimer = null; }
      return;
    }

    const isLong = signal.signal !== 'CASCADE_SHORT';
    const color  = isLong ? 'var(--green)' : 'var(--red)';
    const arrow  = isLong ? '▲' : '▼';
    const label  = isLong ? 'LONG CASCADE' : 'SHORT CASCADE';
    const estMin = signal.est_minutes ? `~${Math.round(signal.est_minutes)}m` : '---';

    el.innerHTML = `
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
          <span class="sig-lbl">TP <span style="font-size:10px;color:var(--muted)">(+0.8%)</span></span>
          <span class="sig-val sig-tp">${_formatPrice(signal.tp)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">SL <span style="font-size:10px;color:var(--muted)">(-0.5%)</span></span>
          <span class="sig-val sig-sl">${_formatPrice(signal.sl)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">Prob</span>
          <span class="sig-val sig-prob">${Math.round((signal.prob || 0) * 100)}%</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">Est. cascade</span>
          <span class="sig-val" style="color:var(--yellow)">${estMin}</span>
        </div>
        <div class="countdown" style="${isLong ? '' : 'border-color:rgba(248,81,73,.3);background:rgba(248,81,73,.08);color:var(--red)'}">
          Đóng sau <span class="timer" id="countdown-timer">03:00</span>
        </div>
      </div>`;

    _startCountdown(signal.opened_at || new Date().toISOString());

    const isNew = signal.opened_at !== _lastSignalTs;
    if (isNew) {
      _lastSignalTs = signal.opened_at;
      _showAlert(signal);
      _browserNotify(signal);
      TradesModule.load(); // refresh ngay khi có signal mới, không chờ 30s
    }
  }

  function _showAlert(signal) {
    const isLong = signal.signal !== 'CASCADE_SHORT';
    document.getElementById('alert-icon').textContent  = isLong ? '⚡' : '⚡';
    document.getElementById('alert-title').textContent = isLong ? 'LONG CASCADE' : 'SHORT CASCADE';
    document.getElementById('alert-title').style.color = isLong ? 'var(--green)' : 'var(--red)';

    const estMin = signal.est_minutes ? `~${Math.round(signal.est_minutes)}m` : '---';
    document.getElementById('alert-detail').innerHTML =
      `Entry <b>${_formatPrice(signal.entry)}</b> → TP <b>${_formatPrice(signal.tp)}</b><br>` +
      `Prob ${Math.round((signal.prob || 0) * 100)}% | Est. cascade: ${estMin}`;

    const popup = document.getElementById('alert-popup');
    popup.style.borderColor = isLong ? 'var(--green)' : 'var(--red)';
    popup.classList.add('show');
    setTimeout(() => popup.classList.remove('show'), 10000);
  }

  function _browserNotify(signal) {
    if (!('Notification' in window)) return;
    const isLong = signal.signal !== 'CASCADE_SHORT';
    const title  = isLong ? '⚡ LONG CASCADE Signal!' : '⚡ SHORT CASCADE Signal!';
    if (Notification.permission === 'granted') {
      new Notification(title, {
        body: `Entry: ${_formatPrice(signal.entry)}  TP: ${_formatPrice(signal.tp)}`,
      });
    } else if (Notification.permission !== 'denied') {
      Notification.requestPermission().then(p => { if (p === 'granted') _browserNotify(signal); });
    }
  }

  // ── onTick ────────────────────────────────────────────────

  function onTick(tick) {
    const probLong  = tick.cascade_prob_long  ?? null;
    const probShort = tick.cascade_prob_short ?? null;
    const ttcLong   = tick.time_to_cascade_long  ?? null;
    const ttcShort  = tick.time_to_cascade_short ?? null;
    const signal    = tick.cascade_signal ?? null;

    // Prob bars
    _updateProbBar(
      document.getElementById('prob-bar-long'),
      document.getElementById('prob-value-long'),
      probLong, false, !!signal && signal.signal !== 'CASCADE_SHORT',
    );
    _updateProbBar(
      document.getElementById('prob-bar-short'),
      document.getElementById('prob-value-short'),
      probShort, true, !!signal && signal.signal === 'CASCADE_SHORT',
    );

    // TTC badges
    _updateTtcBadge('ttc-long',  ttcLong);
    _updateTtcBadge('ttc-short', ttcShort);

    // Curve chart
    _updateCurveChart(tick.cascade_curve_long ?? null, tick.cascade_curve_short ?? null);

    // Other charts
    _updateImbalance(tick.imbalance);
    _updateMiniStats(tick);
    if (tick.cvd_1m !== undefined) _updateCvdChart(tick.cvd_1m);

    // Signal panel
    _renderSignalPanel(signal);
  }

  function init() {
    _initCvdChart();
    _initCurveChart();
    document.addEventListener('click', () => {
      if (Notification.permission === 'default') Notification.requestPermission();
    }, { once: true });
  }

  return { init, onTick };
})();
