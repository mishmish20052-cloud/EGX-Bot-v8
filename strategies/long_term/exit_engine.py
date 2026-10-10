"""
محرك الخروج للاستثمار متوسط المدى.

يراقب كل صفقة مفتوحة ويقرر:
- T1/T2/T3/T4 (بيع متدرج)
- Trailing stop بعد T2
- Stop Loss
- كسر EMA50
- إغلاق زمني بعد 90 يوم
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config.settings import (
    CAIRO_TZ,
    TOTAL_FEE_RATE,
    TRAILING_ATR_MULT,
)
from config.strategies import LONG_TERM
from strategies.shared.risk import calculate_net_pnl

logger = logging.getLogger("egx_bot.long_term.exit_engine")


# ===========================================================
# نموذج حدث الخروج
# ===========================================================
@dataclass
class ExitEvent:
    """حدث خروج أو بيع جزئي."""
    symbol: str
    event_type: str          # "T1" / "T2" / "T3" / "T4" / "STOP" / "TRAIL" / "TIME" / "EMA_BREAK" / "REVERSAL"
    price: float
    sold_shares: int
    remaining_shares: int
    net_pnl: float
    new_stop: Optional[float] = None
    is_full_exit: bool = False
    is_win: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "event_type": self.event_type,
            "price": round(self.price, 2),
            "sold_shares": self.sold_shares,
            "remaining_shares": self.remaining_shares,
            "net_pnl": round(self.net_pnl, 2),
            "new_stop": round(self.new_stop, 2) if self.new_stop else None,
            "is_full_exit": self.is_full_exit,
            "is_win": self.is_win,
            "note": self.note,
        }


# ===========================================================
# حساب الأهداف من الاستراتيجية
# ===========================================================
def compute_targets_from_entry(
    entry_price: float,
    stop_loss: float,
) -> dict:
    """
    يحسب T1/T2/T3/T4 من سعر الدخول والستوب.
    """
    risk = entry_price - stop_loss
    if risk <= 0:
        return {"t1": 0, "t2": 0, "t3": 0, "t4": 0}

    # أهداف مبنية على R:R
    targets = {
        "t1": round(entry_price + risk * 1.5, 2),
        "t2": round(entry_price + risk * 2.5, 2),
        "t3": round(entry_price + risk * 4.0, 2),
        "t4": round(entry_price + risk * 6.0, 2),
    }
    return targets


# ===========================================================
# فحص T1/T2/T3/T4
# ===========================================================
def check_targets(
    symbol: str,
    position: dict,
    current_price: float,
) -> Optional[ExitEvent]:
    """
    يفحص الأهداف بالترتيب (T4 → T3 → T2 → T1).
    يرجع ExitEvent لو تحقق هدف، وإلا None.
    """
    shares = position.get("shares", 0)
    remaining = position.get("remaining", shares)
    entry = position.get("entry_price", 0)

    if remaining <= 0 or entry <= 0:
        return None

    # T4 (بيع كل المتبقي)
    if not position.get("t4_hit") and current_price >= position.get("t4", 999999):
        sold = remaining
        net = calculate_net_pnl(entry, current_price, sold)
        return ExitEvent(
            symbol=symbol,
            event_type="T4",
            price=current_price,
            sold_shares=sold,
            remaining_shares=0,
            net_pnl=net,
            is_full_exit=True,
            is_win=True,
            note="هدف نهائي — بيع الكل",
        )

    # T3 (بيع 25%)
    if position.get("t2_hit") and not position.get("t3_hit") and current_price >= position.get("t3", 999999):
        sold = max(1, min(remaining, math.floor(shares * 0.25)))
        net = calculate_net_pnl(entry, current_price, sold)
        return ExitEvent(
            symbol=symbol,
            event_type="T3",
            price=current_price,
            sold_shares=sold,
            remaining_shares=remaining - sold,
            net_pnl=net,
            new_stop=position.get("t1", entry),
            is_win=True,
            note="بيع 25%",
        )

    # T2 (بيع 25% + تفعيل Trailing)
    if position.get("t1_hit") and not position.get("t2_hit") and current_price >= position.get("t2", 999999):
        sold = max(1, min(remaining, math.floor(shares * 0.25)))
        net = calculate_net_pnl(entry, current_price, sold)
        return ExitEvent(
            symbol=symbol,
            event_type="T2",
            price=current_price,
            sold_shares=sold,
            remaining_shares=remaining - sold,
            net_pnl=net,
            new_stop=entry,  # قفل ربح عند سعر الدخول
            is_win=True,
            note="بيع 25% — تفعيل Trailing",
        )

    # T1 (بيع 25% + نقل الستوب لـ التعادل)
    if not position.get("t1_hit") and current_price >= position.get("t1", 999999):
        sold = max(1, min(remaining, math.floor(shares * 0.25)))
        net = calculate_net_pnl(entry, current_price, sold)
        return ExitEvent(
            symbol=symbol,
            event_type="T1",
            price=current_price,
            sold_shares=sold,
            remaining_shares=remaining - sold,
            net_pnl=net,
            new_stop=entry,  # نقل الستوب لـ التعادل
            is_win=True,
            note="بيع 25% — الستوب إلى التعادل",
        )

    return None


# ===========================================================
# فحص Trailing Stop
# ===========================================================
def check_trailing_stop(
    symbol: str,
    position: dict,
    current_price: float,
    atr: float,
) -> Optional[float]:
    """
    يحسب الستوب الجديد للـ Trailing Stop.
    يرجع الستوب الجديد لو أعلى من الحالي، وإلا None.
    """
    if not position.get("trailing_active"):
        return None

    current_stop = position.get("current_stop", 0)
    if current_stop <= 0:
        return None

    # الستوب الجديد = السعر - (ATR × معامل)
    candidate = round(current_price - (atr * TRAILING_ATR_MULT), 2)

    # لا يتجاوز 2% تحت السعر
    ceiling = current_price * 0.98
    candidate = min(candidate, ceiling)

    if candidate > current_stop:
        return candidate
    return None


# ===========================================================
# فحص Stop Loss
# ===========================================================
def check_stop_loss(
    symbol: str,
    position: dict,
    current_price: float,
) -> Optional[ExitEvent]:
    """
    يفحص كسر الستوب (الأساسي أو Trailing).
    """
    current_stop = position.get("current_stop") or position.get("stop_loss", 0)
    if current_stop <= 0:
        return None

    if current_price <= current_stop:
        remaining = position.get("remaining", position.get("shares", 0))
        entry = position.get("entry_price", 0)
        net = calculate_net_pnl(entry, current_price, remaining)
        is_win = net >= 0

        return ExitEvent(
            symbol=symbol,
            event_type="TRAIL" if position.get("trailing_active") else "STOP",
            price=current_price,
            sold_shares=remaining,
            remaining_shares=0,
            net_pnl=net,
            is_full_exit=True,
            is_win=is_win,
            note="Trailing stop" if position.get("trailing_active") else "Stop loss",
        )
    return None


# ===========================================================
# فحص كسر EMA50
# ===========================================================
def check_ema50_break(
    symbol: str,
    position: dict,
    current_price: float,
    ema50: float,
) -> Optional[ExitEvent]:
    """
    يفحص كسر EMA50 كإشارة خروج.
    """
    if not LONG_TERM.exit_on_ema50_break:
        return None

    if ema50 <= 0:
        return None

    # بس لو السهم في ربح حاليًا، وإلا نعتمد على Stop Loss
    entry = position.get("entry_price", 0)
    if current_price <= entry:
        return None  # السيولة مازالت تحت السيطرة

    # لو كسر EMA50 بقوة (نزل 1% تحته)
    if current_price < ema50 * 0.99:
        remaining = position.get("remaining", position.get("shares", 0))
        net = calculate_net_pnl(entry, current_price, remaining)

        return ExitEvent(
            symbol=symbol,
            event_type="EMA_BREAK",
            price=current_price,
            sold_shares=remaining,
            remaining_shares=0,
            net_pnl=net,
            is_full_exit=True,
            is_win=net >= 0,
            note="كسر EMA50",
        )
    return None


# ===========================================================
# فحص إشارة انعكاس
# ===========================================================
def check_reversal_signal(
    symbol: str,
    position: dict,
    data: dict,
) -> Optional[ExitEvent]:
    """
    يفحص إشارة انعكاس قوية (RSI < 30 + MACD سلبي).
    """
    if not LONG_TERM.exit_on_reversal_signal:
        return None

    rsi = data.get("rsi", 50)
    macd = data.get("macd", 0)
    macd_signal = data.get("macd_signal", 0)
    current_price = data.get("close", 0)

    # شرطين لازم يتحققوا معًا
    if rsi < 30 and macd < macd_signal:
        remaining = position.get("remaining", position.get("shares", 0))
        entry = position.get("entry_price", 0)
        net = calculate_net_pnl(entry, current_price, remaining)

        return ExitEvent(
            symbol=symbol,
            event_type="REVERSAL",
            price=current_price,
            sold_shares=remaining,
            remaining_shares=0,
            net_pnl=net,
            is_full_exit=True,
            is_win=net >= 0,
            note=f"RSI {rsi:.0f} + MACD سلبي",
        )
    return None


# ===========================================================
# فحص الإغلاق الزمني
# ===========================================================
def check_time_exit(
    symbol: str,
    position: dict,
    current_price: float,
) -> Optional[ExitEvent]:
    """
    يفحص الإغلاق الزمني بعد LONG_TERM.max_holding_days يوم.
    """
    entry_date_str = position.get("entry_date", "")
    if not entry_date_str:
        return None

    try:
        entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d")
        days_held = (datetime.now(CAIRO_TZ).replace(tzinfo=None) - entry_date).days
    except Exception:
        return None

    if days_held < LONG_TERM.max_holding_days:
        return None

    remaining = position.get("remaining", position.get("shares", 0))
    entry = position.get("entry_price", 0)
    net = calculate_net_pnl(entry, current_price, remaining)

    return ExitEvent(
        symbol=symbol,
        event_type="TIME",
        price=current_price,
        sold_shares=remaining,
        remaining_shares=0,
        net_pnl=net,
        is_full_exit=True,
        is_win=net >= 0,
        note=f"مضى {days_held} يوم (الحد {LONG_TERM.max_holding_days})",
    )


# ===========================================================
# الدالة الرئيسية
# ===========================================================
def process_position(
    symbol: str,
    position: dict,
    data: dict,
) -> Optional[ExitEvent]:
    """
    يعالج صفقة واحدة بكل الفحوصات بالترتيب.

    ترتيب الفحوصات:
    1. T4 (كامل)
    2. T3 (جزئي)
    3. T2 (جزئي)
    4. T1 (جزئي)
    5. Stop Loss
    6. كسر EMA50
    7. إشارة انعكاس
    8. إغلاق زمني

    ترجع: ExitEvent أو None
    """
    current_price = data.get("close", 0)
    if current_price <= 0:
        return None

    # 1-4: الأهداف
    target_event = check_targets(symbol, position, current_price)
    if target_event:
        return target_event

    # 5: الستوب
    stop_event = check_stop_loss(symbol, position, current_price)
    if stop_event:
        return stop_event

    # 6: EMA50
    ema50 = data.get("ema50_daily", 0)
    ema_event = check_ema50_break(symbol, position, current_price, ema50)
    if ema_event:
        return ema_event

    # 7: إشارة انعكاس
    reversal_event = check_reversal_signal(symbol, position, data)
    if reversal_event:
        return reversal_event

    # 8: إغلاق زمني
    time_event = check_time_exit(symbol, position, current_price)
    if time_event:
        return time_event

    return None


# ===========================================================
# تحديث الصفقة بعد حدث
# ===========================================================
def apply_exit_event(
    position: dict,
    event: ExitEvent,
) -> dict:
    """
    يحدّث سجل الصفقة بعد حدث خروج.
    ترجع: السجل المحدّث (أو {} لو خروج كامل).
    """
    if event.is_full_exit:
        return {}  # احذف الصفقة

    # بيع جزئي
    position["remaining"] = event.remaining_shares

    # تحديث علامات الأهداف
    if event.event_type == "T1":
        position["t1_hit"] = True
        if event.new_stop:
            position["current_stop"] = event.new_stop
    elif event.event_type == "T2":
        position["t2_hit"] = True
        position["trailing_active"] = True
        if event.new_stop:
            position["current_stop"] = event.new_stop
    elif event.event_type == "T3":
        position["t3_hit"] = True

    return position


# ===========================================================
# حفظ الأهداف في السجل (عند فتح الصفقة)
# ===========================================================
def attach_targets_to_position(
    position: dict,
    entry_price: float,
    stop_loss: float,
    atr: float = 0,
) -> dict:
    """
    يضيف حقول الأهداف والستوب لسجل الصفقة الجديدة.
    """
    targets = compute_targets_from_entry(entry_price, stop_loss)
    position.update(targets)
    position["stop_loss"] = stop_loss
    position["current_stop"] = stop_loss
    position["atr"] = atr
    return position
