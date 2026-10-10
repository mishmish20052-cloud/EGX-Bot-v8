"""
إدارة محفظة الاستثمار متوسط المدى.

المسؤوليات:
- التحقق من إمكانية فتح صفقات جديدة
- توزيع رأس المال على المراكز
- فحص الحدود (عدد المراكز، القطاعات، التعرض)
- إدارة الصفقات المفتوحة
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config.settings import (
    LONG_TERM_CAPITAL,
    MAX_LONG_POSITIONS,
    MAX_TRADES_PER_SECTOR_LONG,
    MIN_POSITION_VALUE,
    CAIRO_TZ,
)
from config.stocks import get_sector
from strategies.long_term.scorer import ScoredCandidate

logger = logging.getLogger("egx_bot.long_term.portfolio")


# ===========================================================
# نموذج قرار فتح صفقة
# ===========================================================
@dataclass
class OpenDecision:
    """قرار فتح صفقة جديدة."""
    symbol: str
    can_open: bool
    reason: str = ""
    suggested_weight_pct: float = 0.0
    sector: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "can_open": self.can_open,
            "reason": self.reason,
            "suggested_weight_pct": round(self.suggested_weight_pct, 2),
            "sector": self.sector,
        }


# ===========================================================
# تحليل الوضع الحالي للمحفظة
# ===========================================================
def analyze_portfolio(
    open_positions: dict,
) -> dict:
    """
    يحلل الوضع الحالي للمحفظة.

    ترجع dict فيه:
    - num_positions: عدد المراكز المفتوحة
    - deployed: رأس المال المستثمر
    - remaining: رأس المال المتبقي
    - sector_counts: عدد المراكز لكل قطاع
    - has_space: هل فيه مكان لصفقة جديدة؟
    - is_full: هل المحفظة ممتلئة؟
    """
    num_positions = len(open_positions)

    deployed = sum(
        p.get("entry_price", 0) * p.get("shares", 0)
        for p in open_positions.values()
    )

    remaining = LONG_TERM_CAPITAL - deployed

    # عدد المراكز لكل قطاع
    sector_counts: dict[str, int] = {}
    for symbol in open_positions.keys():
        sector = get_sector(symbol)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    has_space = num_positions < MAX_LONG_POSITIONS
    is_full = num_positions >= MAX_LONG_POSITIONS

    return {
        "num_positions": num_positions,
        "deployed": round(deployed, 2),
        "remaining": round(remaining, 2),
        "sector_counts": sector_counts,
        "has_space": has_space,
        "is_full": is_full,
        "capital": LONG_TERM_CAPITAL,
        "max_positions": MAX_LONG_POSITIONS,
    }


# ===========================================================
# فحص إمكانية فتح صفقة
# ===========================================================
def check_open_allowed(
    candidate: ScoredCandidate,
    open_positions: dict,
    portfolio_state: dict = None,
) -> OpenDecision:
    """
    يفحص إمكانية فتح صفقة جديدة.

    المعاملات:
    - candidate: السهم المرشح
    - open_positions: الصفقات المفتوحة حاليًا
    - portfolio_state: من analyze_portfolio (اختياري)

    ترجع: OpenDecision
    """
    symbol = candidate.symbol
    sector = candidate.sector

    if portfolio_state is None:
        portfolio_state = analyze_portfolio(open_positions)

    # 1. هل السهم مفتوح بالفعل؟
    if symbol in open_positions:
        return OpenDecision(
            symbol=symbol,
            can_open=False,
            reason="السهم مفتوح بالفعل",
            sector=sector,
        )

    # 2. هل المحفظة ممتلئة؟
    if portfolio_state["is_full"]:
        return OpenDecision(
            symbol=symbol,
            can_open=False,
            reason=f"المحفظة ممتلئة ({MAX_LONG_POSITIONS} مراكز)",
            sector=sector,
        )

    # 3. هل القطاع وصل الحد؟
    sector_count = portfolio_state["sector_counts"].get(sector, 0)
    if sector_count >= MAX_TRADES_PER_SECTOR_LONG:
        return OpenDecision(
            symbol=symbol,
            can_open=False,
            reason=f"القطاع {sector} وصل الحد ({MAX_TRADES_PER_SECTOR_LONG})",
            sector=sector,
        )

    # 4. هل رأس المال المتبقي كافي؟
    remaining = portfolio_state["remaining"]
    num_open = portfolio_state["num_positions"]
    num_remaining_slots = MAX_LONG_POSITIONS - num_open

    if num_remaining_slots > 0:
        # نحاول نوزع المتبقي على الفرص المتبقية
        suggested_weight = remaining / num_remaining_slots
    else:
        return OpenDecision(
            symbol=symbol,
            can_open=False,
            reason="لا يوجد مكان للمزيد",
            sector=sector,
        )

    # 5. هل المبلغ المقترح كافي؟
    if suggested_weight < MIN_POSITION_VALUE:
        return OpenDecision(
            symbol=symbol,
            can_open=False,
            reason=f"المبلغ المقترح {suggested_weight:,.0f} أقل من الحد {MIN_POSITION_VALUE:,.0f}",
            sector=sector,
        )

    return OpenDecision(
        symbol=symbol,
        can_open=True,
        reason="",
        suggested_weight_pct=round(suggested_weight, 2),
        sector=sector,
    )


# ===========================================================
# اختيار المرشحين النهائيين
# ===========================================================
def select_final_candidates(
    candidates: list[ScoredCandidate],
    open_positions: dict,
) -> tuple[list[ScoredCandidate], list[OpenDecision]]:
    """
    يختار المرشحين النهائيين بناءً على حالة المحفظة.

    ترجع: (المرشحون المقبولون، كل القرارات)
    """
    accepted: list[ScoredCandidate] = []
    decisions: list[OpenDecision] = []

    # نشتغل على نسخة من الصفقات المفتوحة (عشان نحدثها أثناء الاختيار)
    simulated_open = dict(open_positions)

    for candidate in candidates:
        # حالة المحفظة الحالية
        state = analyze_portfolio(simulated_open)

        # فحص الإمكانية
        decision = check_open_allowed(candidate, simulated_open, state)
        decisions.append(decision)

        if decision.can_open:
            accepted.append(candidate)

            # نضيفه للصفقات "المحاكاة" عشان الفحص اللي بعده ياخده في الحسبان
            simulated_open[candidate.symbol] = {
                "entry_price": candidate.data.get("close", 0),
                "shares": int(decision.suggested_weight_pct / candidate.data.get("close", 1)),
            }

        # لو المحفظة امتلأت، نتوقف
        if len(accepted) + len(open_positions) >= MAX_LONG_POSITIONS:
            break

    logger.info(
        f"📊 اختيار نهائي: {len(accepted)} مقبول من {len(candidates)} مرشح"
    )

    return (accepted, decisions)


# ===========================================================
# توزيع الأوزان النهائي
# ===========================================================
def allocate_weights(
    accepted: list[ScoredCandidate],
    open_positions: dict,
) -> dict[str, dict]:
    """
    يوزع رأس المال المتبقي على المرشحين المقبولين.

    ترجع: {symbol: {"weight_egp": المبلغ, "weight_pct": النسبة, "sector": القطاع}}
    """
    state = analyze_portfolio(open_positions)
    remaining = state["remaining"]
    num_new = len(accepted)

    if num_new == 0 or remaining <= 0:
        return {}

    # 1. حساب الأوزان النسبية بناءً على الدرجة
    total_score = sum(c.total_score for c in accepted)
    if total_score <= 0:
        # توزيع متساوٍ
        per_stock = remaining / num_new
        return {
            c.symbol: {
                "weight_egp": round(per_stock, 2),
                "weight_pct": round(per_stock / LONG_TERM_CAPITAL * 100, 2),
                "sector": c.sector,
            }
            for c in accepted
        }

    # 2. توزيع نسبي
    allocations = {}
    for c in accepted:
        portion = c.total_score / total_score
        amount = remaining * portion
        allocations[c.symbol] = {
            "weight_egp": round(amount, 2),
            "weight_pct": round(amount / LONG_TERM_CAPITAL * 100, 2),
            "sector": c.sector,
            "score": c.total_score,
        }

    return allocations


# ===========================================================
# إضافة صفقة جديدة للمحفظة
# ===========================================================
def build_position_record(
    candidate: ScoredCandidate,
    entry_price: float,
    shares: int,
    allocation_egp: float,
) -> dict:
    """
    يبني سجل صفقة جديد للحفظ في ملف الحالة.
    """
    return {
        "symbol": candidate.symbol,
        "name": candidate.name,
        "sector": candidate.sector,
        "entry_price": entry_price,
        "shares": shares,
        "position_value": round(entry_price * shares, 2),
        "allocation_egp": round(allocation_egp, 2),
        "entry_date": datetime.now(CAIRO_TZ).strftime("%Y-%m-%d"),
        "score": round(candidate.total_score, 1),
        "grade": candidate.grade,
        # الحقول دي هتتحدث لاحقًا بواسطة exit_engine
        "remaining": shares,
        "stop_loss": None,
        "current_stop": None,
        "t1": None,
        "t2": None,
        "t3": None,
        "t4": None,
        "t1_hit": False,
        "t2_hit": False,
        "t3_hit": False,
        "t4_hit": False,
        "trailing_active": False,
    }


# ===========================================================
# ملخص المحفظة
# ===========================================================
def portfolio_summary(open_positions: dict) -> str:
    """
    ملخص نصي للمحفظة (للتقارير).
    """
    if not open_positions:
        return "💼 المحفظة فارغة"

    state = analyze_portfolio(open_positions)

    lines = [
        f"💼 *ملخص المحفظة*",
        f"",
        f"📊 المراكز: `{state['num_positions']}/{state['max_positions']}`",
        f"💰 المستثمر: `{state['deployed']:,.0f}` ج.م",
        f"💵 المتبقي: `{state['remaining']:,.0f}` ج.م",
        f"",
        f"📈 *المراكز الحالية:*",
    ]

    for symbol, pos in open_positions.items():
        name = pos.get("name", symbol)
        entry = pos.get("entry_price", 0)
        shares = pos.get("shares", 0)
        value = entry * shares
        lines.append(f"  • `{symbol}` - {name[:20]}")
        lines.append(f"    دخول: `{entry:.2f}` × `{shares}` = `{value:,.0f}` ج.م")

    # توزيع القطاعات
    if state["sector_counts"]:
        lines.append(f"")
        lines.append(f"🏢 *توزيع القطاعات:*")
        for sector, count in state["sector_counts"].items():
            lines.append(f"  • {sector}: `{count}` سهم")

    return "\n".join(lines)
