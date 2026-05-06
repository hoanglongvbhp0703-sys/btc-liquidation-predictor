"""
notifier.py — Gửi thông báo Telegram khi có signal

Config qua env var (không bắt buộc):
  TELEGRAM_BOT_TOKEN=<token>
  TELEGRAM_CHAT_ID=<chat_id>

Nếu không set → chỉ log ra stdout, không báo lỗi.
"""

import os
import urllib.request
import urllib.parse
import json

_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def _send_telegram(text: str) -> bool:
    if not _TOKEN or not _CHAT_ID:
        return False
    url     = f"https://api.telegram.org/bot{_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": _CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
    req     = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[SIG] ⚠️  Telegram error: {e}")
        return False


def notify_signal(signal: dict, opened_at) -> None:
    """Gửi thông báo khi có signal LONG mới."""
    msg = (
        f"🟢 <b>BTC LONG SIGNAL</b>\n"
        f"🕒 {opened_at.strftime('%Y-%m-%d %H:%M')} UTC\n"
        f"\n"
        f"  Entry : <b>${signal['entry']:,.0f}</b>\n"
        f"  TP    : <b>${signal['tp']:,.0f}</b>  (+{(signal['tp']/signal['entry']-1)*100:.2f}%)\n"
        f"  SL    : <b>${signal['sl']:,.0f}</b>  ({(signal['sl']/signal['entry']-1)*100:.2f}%)\n"
        f"  R:R   : <b>{signal['rr']:.2f}</b>\n"
        f"  Prob  : <b>{signal['prob']*100:.1f}%</b>\n"
    )
    print(f"[SIG] 📢 Signal:\n{msg}")
    sent = _send_telegram(msg)
    if sent:
        print("[SIG] ✅ Telegram gửi thành công")
    elif _TOKEN:
        print("[SIG] ❌ Telegram gửi thất bại")


def notify_outcome(trade: dict) -> None:
    """Gửi thông báo khi trade đóng (WIN/LOSS/EXPIRED)."""
    outcome = trade.get("outcome", "")
    icon    = "✅" if outcome == "WIN" else ("❌" if outcome == "LOSS" else "⏳")
    pnl     = trade.get("pnl_pct", 0)

    msg = (
        f"{icon} <b>BTC Trade {outcome}</b>\n"
        f"  Entry : ${float(trade['entry']):,.0f}\n"
        f"  TP    : ${float(trade['tp']):,.0f}\n"
        f"  SL    : ${float(trade['sl']):,.0f}\n"
        f"  PnL   : <b>{float(pnl):+.2f}%</b>\n"
        f"  Opened: {trade['opened_at'][:16]} UTC\n"
    )
    _send_telegram(msg)
