// trades.js — Paper trades table + mini stats

const TradesModule = (() => {

  function _fmt(p) {
    if (p === '' || p === null || p === undefined) return '---';
    return '$' + Number(p).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function _fmtTime(ts) {
    if (!ts) return '---';
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', hour12: false });
    } catch { return ts.slice(11, 16) || '---'; }
  }

  function _outcomeClass(outcome) {
    if (outcome === 'WIN')     return 'outcome-win';
    if (outcome === 'LOSS')    return 'outcome-loss';
    if (outcome === 'EXPIRED') return 'outcome-exp';
    if (outcome === '')        return 'outcome-open';
    return '';
  }

  function _outcomeLabel(outcome) {
    if (outcome === '') return '⏳ Open';
    return outcome;
  }

  function _pnlClass(pnl) {
    if (pnl === '' || pnl === null) return '';
    return Number(pnl) >= 0 ? 'pnl-pos' : 'pnl-neg';
  }

  function render(trades) {
    const tbody = document.getElementById('trades-body');
    if (!trades || trades.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" class="no-data">Chưa có paper trade</td></tr>';
      _updateMiniStats([]);
      return;
    }

    tbody.innerHTML = trades.map(t => {
      const isLong = (t.signal || '').includes('LONG') || !(t.signal || '').includes('SHORT');
      const typeLabel = isLong
        ? '<span style="color:var(--green)">▲ LONG</span>'
        : '<span style="color:var(--red)">▼ SHORT</span>';
      const estMin = t.est_minutes ? `~${Math.round(Number(t.est_minutes))}m` : '---';
      return `
        <tr>
          <td>${_fmtTime(t.opened_at)}</td>
          <td>${typeLabel}</td>
          <td>${_fmt(t.entry)}</td>
          <td class="sig-tp">${_fmt(t.tp)}</td>
          <td class="sig-sl">${_fmt(t.sl)}</td>
          <td>${t.prob ? Math.round(Number(t.prob) * 100) + '%' : '---'}</td>
          <td>${estMin}</td>
          <td class="${_outcomeClass(t.outcome)}">${_outcomeLabel(t.outcome)}</td>
          <td class="${_pnlClass(t.pnl_pct)}">${t.pnl_pct !== '' ? (Number(t.pnl_pct) >= 0 ? '+' : '') + Number(t.pnl_pct).toFixed(2) + '%' : '---'}</td>
        </tr>`;
    }).join('');

    _updateMiniStats(trades);
    _updateTpSlHeaders(trades);
  }

  function _updateMiniStats(trades) {
    const closed = trades.filter(t => t.outcome === 'WIN' || t.outcome === 'LOSS');
    const wins   = trades.filter(t => t.outcome === 'WIN').length;
    const losses = trades.filter(t => t.outcome === 'LOSS').length;
    const wr     = closed.length > 0 ? Math.round(wins / closed.length * 100) : null;
    const pnls   = trades.filter(t => t.pnl_pct !== '').map(t => Number(t.pnl_pct));
    const total  = pnls.reduce((a, b) => a + b, 0);

    document.getElementById('win-count').textContent  = wins;
    document.getElementById('loss-count').textContent = losses;
    document.getElementById('wr-pct').textContent     = wr !== null ? wr + '%' : '--';
    const pnlEl = document.getElementById('total-pnl');
    pnlEl.textContent = pnls.length > 0 ? (total >= 0 ? '+' : '') + total.toFixed(2) + '%' : '--';
    pnlEl.style.color = total >= 0 ? 'var(--green)' : 'var(--red)';
  }

  function _updateTpSlHeaders(trades) {
    const t = trades.find(x => x.entry && x.tp && x.sl);
    if (!t) return;
    const entry = Number(t.entry);
    const tp    = Number(t.tp);
    const sl    = Number(t.sl);
    if (!entry || !tp || !sl) return;
    const isLong  = (t.signal || '').includes('LONG') || !(t.signal || '').includes('SHORT');
    const tpPct   = Math.abs((tp - entry) / entry * 100).toFixed(2);
    const slPct   = Math.abs((sl - entry) / entry * 100).toFixed(2);
    const thTp = document.getElementById('th-tp');
    const thSl = document.getElementById('th-sl');
    if (thTp) thTp.textContent = `TP (+${tpPct}%)`;
    if (thSl) thSl.textContent = `SL (-${slPct}%)`;
  }

  async function load() {
    try {
      const r = await fetch('/api/trades/?limit=30');
      const data = await r.json();
      render(data);
    } catch (e) {
      console.error('trades load error', e);
    }
  }

  return { load, render };
})();
