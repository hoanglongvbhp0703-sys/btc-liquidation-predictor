// signal.js — Signal panel + prob bar + countdown + alert

const SignalModule = (() => {
  let _lastSignalTs = null;
  let _countdownTimer = null;

  // CVD sparkline (line chart, không phải bar → tránh "tường đỏ")
  let _cvdChart = null;
  const _cvdHistory = [];
  const CVD_MAX = 40;
  let _cvdBase = null;   // giá trị đầu tiên để tính relative

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
          y: {
            display: false,
            grid: { display: false },
          },
        },
      },
    });
  }

  function _updateCvdChart(cvd) {
    if (cvd === null || cvd === undefined) return;

    // Tích lũy CVD (cumulative) để đường đi có xu hướng thay vì nhảy
    if (_cvdBase === null) _cvdBase = 0;
    _cvdBase += cvd;
    _cvdHistory.push(_cvdBase);
    if (_cvdHistory.length > CVD_MAX) _cvdHistory.shift();

    // Màu đường theo chiều xu hướng (so sánh với đầu window)
    const trend = _cvdHistory[_cvdHistory.length - 1] - _cvdHistory[0];
    const col = trend >= 0 ? 'rgba(63,185,80,0.85)' : 'rgba(248,81,73,0.85)';
    const bg  = trend >= 0 ? 'rgba(63,185,80,0.08)' : 'rgba(248,81,73,0.08)';
    _cvdChart.data.datasets[0].borderColor     = col;
    _cvdChart.data.datasets[0].backgroundColor = bg;

    _cvdChart.data.labels = _cvdHistory.map((_, i) => i);
    _cvdChart.data.datasets[0].data = _cvdHistory;
    _cvdChart.update('none');

    const el = document.getElementById('cvd-value');
    el.textContent = cvd >= 0 ? `+${cvd.toFixed(1)}` : cvd.toFixed(1);
    el.className   = 'cvd-value ' + (cvd >= 0 ? 'pos' : 'neg');
  }

  function _updateImbalance(imb) {
    if (imb === null || imb === undefined) return;
    const pct = Math.round(imb * 100);
    document.getElementById('imb-pct').textContent = pct + '%';
    document.getElementById('imbalance').textContent = pct + '%';
    // marker position (0% = full left, 100% = full right)
    document.getElementById('imb-marker').style.left = pct + '%';
  }

  function _updateMiniStats(tick) {
    if (tick.dist_upper_pct !== undefined && tick.dist_upper_pct !== null) {
      document.getElementById('dist-upper').textContent =
        (tick.dist_upper_pct * 100).toFixed(2) + '%';
    }
    if (tick.funding_rate !== undefined && tick.funding_rate !== null) {
      const f = (tick.funding_rate * 100).toFixed(4);
      const el = document.getElementById('funding');
      el.textContent = f + '%';
      el.style.color = tick.funding_rate > 0 ? 'var(--green)' : 'var(--red)';
    }
    if (tick.delta_oi_5m !== undefined && tick.delta_oi_5m !== null) {
      const d = (tick.delta_oi_5m * 100).toFixed(3);
      const el = document.getElementById('delta-oi');
      el.textContent = (tick.delta_oi_5m >= 0 ? '+' : '') + d + '%';
      el.style.color = tick.delta_oi_5m >= 0 ? 'var(--green)' : 'var(--red)';
    }
  }

  function _updateProbBar(prob, hasSignal) {
    const pct = prob !== null ? Math.round(prob * 100) : 0;
    const bar  = document.getElementById('prob-bar');
    const val  = document.getElementById('prob-value');

    bar.style.width = pct + '%';
    val.textContent = prob !== null ? pct + '%' : '---%';

    bar.className = 'prob-bar';
    if (hasSignal) bar.classList.add('signal');
    else if (pct >= 60) bar.classList.add('high');
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

  function _renderSignalPanel(signal, prob) {
    const el = document.getElementById('signal-info');

    if (!signal) {
      el.innerHTML = '<div class="no-signal">Chưa có signal</div>';
      if (_countdownTimer) { clearInterval(_countdownTimer); _countdownTimer = null; }
      return;
    }

    const isNew = signal.opened_at !== _lastSignalTs;
    _lastSignalTs = signal.opened_at;

    el.innerHTML = `
      <div class="signal-active">
        <div class="sig-row">
          <span class="sig-lbl">Signal</span>
          <span class="sig-val" style="color:var(--green)">⬆ LONG</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">Entry</span>
          <span class="sig-val sig-entry">${_formatPrice(signal.entry)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">TP</span>
          <span class="sig-val sig-tp">${_formatPrice(signal.tp)}</span>
        </div>
        <div class="sig-row">
          <span class="sig-lbl">SL</span>
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
        <div class="countdown">
          Đóng sau <span class="timer" id="countdown-timer">30:00</span>
        </div>
      </div>`;

    _startCountdown(signal.opened_at);

    if (isNew) {
      _showAlert(signal);
      _browserNotify(signal);
    }
  }

  function _showAlert(signal) {
    const popup = document.getElementById('alert-popup');
    document.getElementById('alert-detail').innerHTML =
      `Entry <b>${_formatPrice(signal.entry)}</b> → TP <b>${_formatPrice(signal.tp)}</b><br>` +
      `SL ${_formatPrice(signal.sl)} | R:R ${Number(signal.rr).toFixed(2)} | Prob ${Math.round(signal.prob*100)}%`;
    popup.classList.add('show');
    setTimeout(() => popup.classList.remove('show'), 10000);
  }

  function _browserNotify(signal) {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'granted') {
      new Notification('🚀 BTC LONG Signal!', {
        body: `Entry: ${_formatPrice(signal.entry)}  TP: ${_formatPrice(signal.tp)}  R:R ${Number(signal.rr).toFixed(2)}`,
        icon: '',
      });
    } else if (Notification.permission !== 'denied') {
      Notification.requestPermission().then(p => {
        if (p === 'granted') _browserNotify(signal);
      });
    }
  }

  function onTick(tick) {
    _updateProbBar(tick.prob, !!tick.signal);
    _updateImbalance(tick.imbalance);
    _updateMiniStats(tick);
    if (tick.cvd_5m !== undefined) _updateCvdChart(tick.cvd_5m);
    _renderSignalPanel(tick.signal, tick.prob);
  }

  function init() {
    _initCvdChart();
    // Request browser notification permission on first interaction
    document.addEventListener('click', () => {
      if (Notification.permission === 'default') Notification.requestPermission();
    }, { once: true });
  }

  return { init, onTick };
})();
