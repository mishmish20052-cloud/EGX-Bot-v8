"""
قوالب الرسائل الجاهزة.

كل دالة تأخذ data dict وترجع string منسق للعرض في تليجرام.
الفكرة: نضمن شكل موحد لكل الرسائل، وسهولة التعديل مستقبلاً.
"""

from datetime import datetime
from typing import Optional

from config.settings import CAIRO_TZ, TOTAL_FEE_RATE


# ===========================================================
# بانر وضع القياس
# ===========================================================
def measurement_banner(measurement_mode: bool) -> str:
    """يرجع بانر واضح لو إحنا في وضع محاكاة."""
    if measurement_mode:
        return "📝📝 *وضع القياس (محاكاة) — ليست صفقة حقيقية* 📝📝\n\n"
    return ""


# ===========================================================
# 1. تقرير الصباح
# ===========================================================
def morning_report(
    regime: dict,
    measurement_mode: bool = False,
) -> str:
    """تقرير بداية اليوم."""
    banner = measurement_banner(measurement_mode)
    regime_type = regime.get("type", "UNKNOWN")
    regime_risk = regime.get("risk", "MEDIUM")
    change = regime.get("change_pct", 0.0)
    max_trades = regime.get("max_trades", 3)
    source = regime.get("source", "unknown")
    breadth = regime.get("breadth_pct")

    breadth_line = ""
    if breadth is not None:
        breadth_line = f"\n📉 اتساع السوق: `{breadth}%` أسهم حمراء"

    return (
        banner +
        f"🌍 *تقرير الصباح*\n\n"
        f"📊 التغير: `{change:+.2f}%`\n"
        f"🎯 الحالة: `{regime_type}`\n"
        f"⚠️ المخاطرة: `{regime_risk}`\n"
        f"💼 أقصى صفقات: `{max_trades}`\n"
        f"📡 المصدر: `{source}`"
        f"{breadth_line}"
    )


# ===========================================================
# 2. إشارة دخول (مختصرة — للاستخدام السريع)
# ===========================================================
def entry_signal(
    symbol: str,
    name: str,
    sector: str,
    signal_type: str,
    score: float,
    plan: dict,
    market_regime: str,
    measurement_mode: bool = False,
) -> str:
    """رسالة إشارة شراء مختصرة."""
    banner = measurement_banner(measurement_mode)

    return (
        banner +
        f"🚀 *{signal_type}*\n"
        f"🎖️ الجودة: `{score:.0f}/100` → "
        f"الوزن: `{plan.get('weight', 0):.1f}%`\n\n"
        f"🌍 السوق: `{market_regime}`\n"
        f"📌 `{symbol} - {name}` ({sector})\n"
        f"💵 دخول: `{plan.get('entry_price', 0):.2f}`\n"
        f"📦 الكمية: `{plan.get('shares', 0)}` سهم\n"
        f"💸 الخسارة عند الستوب: `{plan.get('loss_egp', 0):,.0f}` ج.م\n"
        f"🎯 T1 `{plan.get('t1', 0):.2f}`: +`{plan.get('p1', 0):,.0f}` ج.م\n"
        f"🚀 T2 `{plan.get('t2', 0):.2f}`: +`{plan.get('p2', 0):,.0f}` ج.م\n"
        f"🔥 T3 `{plan.get('t3', 0):.2f}`: +`{plan.get('p3', 0):,.0f}` ج.م"
    )


# ===========================================================
# 2-ب. إشارة دخول مفصلة (مع تفصيل التقييم)
# ===========================================================
def entry_signal_detailed(
    symbol: str,
    name: str,
    sector: str,
    signal_type: str,
    score: float,
    plan: dict,
    market_regime: str,
    score_details: dict,
    measurement_mode: bool = False,
) -> str:
    """
    رسالة إشارة شراء مع تفصيل كامل للتقييم.

    score_details: dict من ScoreResult.to_dict()
      يحتوي على breakdown بالتفصيل
    """
    banner = measurement_banner(measurement_mode)

    # --- تفصيل التقييم الفني ---
    tech_breakdown = score_details.get("breakdown", {})
    technical_score = score_details.get("technical_score", 0)
    fundamental_score = score_details.get("fundamental_score", 0)
    grade = score_details.get("grade", "?")

    # --- بناء قسم التفصيل ---
    breakdown_lines = ["📊 *تفصيل التقييم*", "━━━━━━━━━━━━━━━━━"]

    # الفني (70)
    breakdown_lines.append(f"\n🎯 *الدرجة الفنية ({technical_score:.0f}/70):*")

    if "tech_trend" in tech_breakdown:
        v = tech_breakdown["tech_trend"]
        emoji = "✅" if v >= 20 else "🟡" if v >= 10 else "❌"
        breakdown_lines.append(f"  {emoji} الاتجاه: {v:.0f}/25")

    if "tech_momentum" in tech_breakdown:
        v = tech_breakdown["tech_momentum"]
        emoji = "✅" if v >= 12 else "🟡" if v >= 6 else "❌"
        breakdown_lines.append(f"  {emoji} الزخم: {v:.0f}/15")

    if "tech_relative_strength" in tech_breakdown:
        v = tech_breakdown["tech_relative_strength"]
        emoji = "✅" if v >= 12 else "🟡" if v >= 6 else "❌"
        breakdown_lines.append(f"  {emoji} القوة النسبية: {v:.0f}/15")

    if "tech_sector_strength" in tech_breakdown:
        v = tech_breakdown["tech_sector_strength"]
        emoji = "✅" if v >= 7 else "🟡" if v >= 4 else "❌"
        breakdown_lines.append(f"  {emoji} قوة القطاع: {v:.0f}/10")

    if "tech_liquidity" in tech_breakdown:
        v = tech_breakdown["tech_liquidity"]
        emoji = "✅" if v >= 4 else "🟡" if v >= 2 else "❌"
        breakdown_lines.append(f"  {emoji} السيولة: {v:.0f}/5")

    # الأساسي (30)
    breakdown_lines.append(f"\n💰 *الدرجة الأساسية ({fundamental_score:.0f}/30):*")

    if "fund_valuation" in tech_breakdown:
        v = tech_breakdown["fund_valuation"]
        emoji = "✅" if v >= 8 else "🟡" if v >= 5 else "❌"
        breakdown_lines.append(f"  {emoji} التقييم: {v:.0f}/10")

    if "fund_earnings_growth" in tech_breakdown:
        v = tech_breakdown["fund_earnings_growth"]
        emoji = "✅" if v >= 8 else "🟡" if v >= 5 else "❌"
        breakdown_lines.append(f"  {emoji} نمو الأرباح: {v:.0f}/10")

    if "fund_profitability" in tech_breakdown:
        v = tech_breakdown["fund_profitability"]
        emoji = "✅" if v >= 8 else "🟡" if v >= 5 else "❌"
        breakdown_lines.append(f"  {emoji} الربحية: {v:.0f}/10")

    # --- الأسباب ---
    reasons = score_details.get("reasons", [])
    if reasons:
        breakdown_lines.append("\n⚠️ *ملاحظات:*")
        for r in reasons[:3]:
            breakdown_lines.append(f"  • {r}")

    # --- الأسعار والأهداف ---
    price_lines = [
        "",
        "━━━━━━━━━━━━━━━━━",
        "🎯 *خطة الصفقة*",
        "━━━━━━━━━━━━━━━━━",
        f"  💵 الدخول: `{plan.get('entry_price', 0):.2f}`",
        f"  🛑 الستوب: `{plan.get('sl', 0):.2f}` "
        f"(خسارة: `{plan.get('loss_egp', 0):,.0f}` ج.م)",
        f"  📦 الكمية: `{plan.get('shares', 0)}` سهم",
        f"  💰 القيمة: `{plan.get('shares', 0) * plan.get('entry_price', 0):,.0f}` ج.م",
        f"  🎖️ الوزن: `{plan.get('weight', 0):.1f}%`",
        f"  ⚖️ R:R: `1:{plan.get('rr_ratio', 0):.2f}`",
        "",
        "🎯 *الأهداف المتدرجة:*",
        f"  T1 `{plan.get('t1', 0):.2f}`: +`{plan.get('p1', 0):,.0f}` ج.م",
        f"  T2 `{plan.get('t2', 0):.2f}`: +`{plan.get('p2', 0):,.0f}` ج.م",
        f"  T3 `{plan.get('t3', 0):.2f}`: +`{plan.get('p3', 0):,.0f}` ج.م",
    ]

    # --- دمج الكل ---
    return (
        banner +
        f"🚀 *إشارة {signal_type}*\n"
        f"📌 `{symbol} - {name}` ({sector})\n"
        f"🌍 السوق: `{market_regime}`\n"
        f"🎖️ *الجودة: {score:.0f}/100 ({grade})*\n\n"
        + "\n".join(breakdown_lines)
        + "\n".join(price_lines)
    )


# ===========================================================
# 2-ج. تقرير الفلترة اليومي
# ===========================================================
def screening_report(
    accepted: list,
    rejected: list,
    total_screened: int,
    measurement_mode: bool = False,
) -> str:
    """
    تقرير مفصل عن الفلترة والتقييم اليومي.

    accepted: قائمة ScoredCandidate المقبولين
    rejected: قائمة dict {"symbol", "reason", "score"}
    total_screened: عدد الأسهم الكلي قبل الفلترة
    """
    banner = measurement_banner(measurement_mode)

    lines = [
        "📊 *تقرير الفلترة اليومي*",
        f"📅 {datetime.now(CAIRO_TZ).strftime('%Y-%m-%d')}",
        "━━━━━━━━━━━━━━━━━",
        f"",
        f"🔍 *إجمالي الأسهم:* `{total_screened}`",
        f"✅ *مقبول:* `{len(accepted)}`",
        f"❌ *مرفوض:* `{len(rejected)}`",
        f"",
    ]

    # المقبولون
    if accepted:
        lines.append("━━━━━━━━━━━━━━━━━")
        lines.append("✅ *الأسهم المقبولة:*")
        lines.append("")
        for c in accepted[:5]:
            lines.append(
                f"  • `{c.symbol}` ({c.grade}) — {c.total_score:.0f}/100"
            )
            lines.append(f"    قطاع: {c.sector}")

    # المرفوضون
    if rejected:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━")
        lines.append("❌ *الأسهم المرفوضة (أول 5):*")
        lines.append("")
        for r in rejected[:5]:
            lines.append(f"  • `{r['symbol']}`")
            lines.append(f"    السبب: {r['reason']}")

    return banner + "\n".join(lines)


# ===========================================================
# 3. الأهداف (T1 / T2 / T3 / T4)
# ===========================================================
def target_hit(
    symbol: str,
    name: str,
    price: float,
    target_label: str,
    sold_shares: int,
    remaining: int,
    net_profit: float,
    new_stop: Optional[float] = None,
    measurement_mode: bool = False,
) -> str:
    """رسالة تحقق هدف."""
    banner = measurement_banner(measurement_mode)

    emoji = {"T1": "🎯", "T2": "🚀", "T3": "🔥", "T4": "💎"}.get(target_label, "🎯")
    portion_text = {
        "T1": "25%",
        "T2": "25%",
        "T3": "25%",
        "T4": "المتبقي",
    }.get(target_label, "")

    stop_line = ""
    if new_stop is not None:
        stop_label = {
            "T1": "نقطة التعادل",
            "T2": "قفل ربح — يتحرك تلقائيًا",
        }.get(target_label, "")
        stop_line = f"\n🛑 *الستوب الجديد:* `{new_stop:.2f}` ({stop_label})"

    complete_line = "\n✅ *صفقة مكتملة بنجاح*" if target_label == "T4" else ""

    return (
        banner +
        f"{emoji} *{target_label} تحقق*\n"
        f"📌 `{symbol} - {name}` | 💵 `{price:.2f}`\n"
        f"🛒 *بع:* `{sold_shares}` سهم ({portion_text})\n"
        f"📦 المتبقي: `{remaining}` سهم\n"
        f"💰 صافي الربح: `{net_profit:,.0f}` ج.م"
        f"{stop_line}{complete_line}"
    )


# ===========================================================
# 4. Stop Loss / Trailing Stop
# ===========================================================
def stop_hit(
    symbol: str,
    name: str,
    stop_price: float,
    sold_shares: int,
    net_pnl: float,
    is_win: bool,
    measurement_mode: bool = False,
) -> str:
    """رسالة خروج بستوب."""
    banner = measurement_banner(measurement_mode)

    if is_win:
        title = "🟢 *خروج بستوب رابح (Trailing)*"
        pnl_emoji = "💰"
        pnl_label = "صافي الربح"
    else:
        title = "🛑 *Stop Loss*"
        pnl_emoji = "💸"
        pnl_label = "صافي الخسارة"

    return (
        banner +
        f"{title}\n"
        f"📌 `{symbol} - {name}` | 📉 كسر `{stop_price:.2f}`\n"
        f"🛒 *بع كل المتبقي:* `{sold_shares}` سهم\n"
        f"{pnl_emoji} {pnl_label}: `{abs(net_pnl):,.0f}` ج.م"
    )


# ===========================================================
# 5. الإغلاق الزمني
# ===========================================================
def time_stop(
    symbol: str,
    name: str,
    days: int,
    limit_days: int,
    sold_shares: int,
    net_pnl: float,
    measurement_mode: bool = False,
) -> str:
    """رسالة إغلاق زمني."""
    banner = measurement_banner(measurement_mode)

    return (
        banner +
        f"⏳ *إغلاق زمني*\n"
        f"📌 `{symbol} - {name}`\n"
        f"📅 راكد `{days}` يوم (الحد: `{limit_days}`)\n"
        f"🛒 *بع الكل:* `{sold_shares}` سهم\n"
        f"💸 صافي: `{net_pnl:,.0f}` ج.م"
    )


# ===========================================================
# 6. تقرير الإغلاق
# ===========================================================
def eod_report(
    stats: dict,
    open_positions: int,
    week_summary: Optional[dict] = None,
    measurement_mode: bool = False,
) -> str:
    """تقرير نهاية اليوم."""
    banner = measurement_banner(measurement_mode)
    today = datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")

    msg = (
        banner +
        f"🌙 *تقرير الإغلاق*\n\n"
        f"📅 {today}\n"
        f"🎯 إشارات: `{stats.get('signals', 0)}`\n"
        f"✅ أهداف: `{stats.get('wins', 0)}`\n"
        f"🛑 ستوبات: `{stats.get('losses', 0)}`\n"
        f"💼 مفتوحة: `{open_positions}`"
    )

    if week_summary:
        msg += (
            f"\n\n📊 *ملخص الأسبوع:*\n"
            f"✅ أرباح: `{week_summary.get('wins', 0)}`\n"
            f"🛑 خسائر: `{week_summary.get('losses', 0)}`"
        )

    return msg


# ===========================================================
# 7. قاطع الدائرة اليومي
# ===========================================================
def circuit_breaker(
    consecutive_losses: int,
    limit: int,
    measurement_mode: bool = False,
) -> str:
    """رسالة تفعيل قاطع الدائرة."""
    banner = measurement_banner(measurement_mode)

    return (
        banner +
        f"🚨 *قاطع الدائرة اليومي مفعّل!*\n\n"
        f"📉 سُجّلت `{consecutive_losses}` خسائر متتالية اليوم.\n"
        f"🎯 الحد الأقصى: `{limit}`\n\n"
        f"⛔ تم إيقاف فتح صفقات جديدة لبقية اليوم.\n"
        f"🔄 الصفقات المفتوحة تبقى تحت المتابعة."
    )


# ===========================================================
# 8. تنبيه حركة قوية
# ===========================================================
def strong_move_alert(
    symbol: str,
    name: str,
    change_pct: float,
    rvol: float,
    rsi: float,
) -> str:
    """تنبيه عند حركة قوية على سهم (بدون فتح صفقة)."""
    return (
        f"🚨 *حركة قوية مدعومة*\n"
        f"📌 `{symbol} - {name}`\n"
        f"📈 التغير: `{change_pct:+.2f}%`\n"
        f"📊 RVOL: `{rvol:.2f}x` | RSI: `{rsi:.0f}`"
    )


# ===========================================================
# 9. انهيار السوق
# ===========================================================
def market_crash(
    index_change: float,
    measurement_mode: bool = False,
) -> str:
    """رسالة انهيار السوق."""
    banner = measurement_banner(measurement_mode)

    return (
        banner +
        f"🚨 *انهيار السوق!*\n\n"
        f"📉 EGX30: `{index_change:+.2f}%`\n"
        f"💰 *أغلق كل الصفقات — تحول للكاش*"
    )


# ===========================================================
# 10. تحديث DNA
# ===========================================================
def dna_update(
    reports: list[str],
    measurement_mode: bool = False,
) -> str:
    """رسالة تحديث DNA اليومي."""
    banner = measurement_banner(measurement_mode)
    reports_text = "\n".join(reports[:5]) if reports else "لا توجد تعديلات"

    return (
        banner +
        f"🧬 *تكيف DNA اليومي*\n\n"
        f"{reports_text}"
    )


# ===========================================================
# 11. تشغيل يدوي
# ===========================================================
def manual_run(
    regime: dict,
    total_capital: float,
    pulse_cycles: int,
    pulse_sleep: int,
    measurement_mode: bool = False,
) -> str:
    """رسالة تشغيل يدوي."""
    banner = measurement_banner(measurement_mode)

    return (
        banner +
        f"🧪 *تشغيل يدوي*\n\n"
        f"🌍 السوق: `{regime.get('type', 'UNKNOWN')}`\n"
        f"📊 التغير: `{regime.get('change_pct', 0):+.2f}%`\n"
        f"💰 رأس المال: `{total_capital:,.0f}` ج.م\n"
        f"💓 نبض: `{pulse_cycles}` دورات × `{pulse_sleep}` ثانية"
    )


# ===========================================================
# 12. خطأ
# ===========================================================
def error_message(
    error_text: str,
    context: str = "",
) -> str:
    """رسالة خطأ موحدة."""
    header = f"❌ *خطأ"
    if context:
        header += f" في {context}"
    header += "*"

    return f"{header}\n\n`{error_text[:500]}`"


# ===========================================================
# 13. تفصيل التقييم (رسالة منفصلة عند الطلب)
# ===========================================================
def score_breakdown(symbol: str, score_details: dict) -> str:
    """
    رسالة مستقلة بتفصيل التقييم الكامل لسهم.
    """
    grade = score_details.get("grade", "?")
    total = score_details.get("total", 0)
    tech = score_details.get("technical_score", 0)
    fund = score_details.get("fundamental_score", 0)
    breakdown = score_details.get("breakdown", {})
    reasons = score_details.get("reasons", [])

    lines = [
        f"📊 *تفصيل التقييم — {symbol}*",
        "━━━━━━━━━━━━━━━━━",
        f"🎖️ الدرجة الكلية: *{total:.0f}/100 ({grade})*",
        f"",
        f"🎯 الفني: {tech:.0f}/70",
        f"💰 الأساسي: {fund:.0f}/30",
        "",
        "📋 *كل المكونات:*",
    ]

    for key, value in breakdown.items():
        # تنسيق اسم المفتاح
        clean_key = key.replace("tech_", "").replace("fund_", "")
        clean_key_ar = {
            "trend": "الاتجاه",
            "momentum": "الزخم",
            "relative_strength": "القوة النسبية",
            "sector_strength": "قوة القطاع",
            "liquidity": "السيولة",
            "valuation": "التقييم",
            "earnings_growth": "نمو الأرباح",
            "profitability": "الربحية",
        }.get(clean_key, clean_key)
        lines.append(f"  • {clean_key_ar}: {value:.1f}")

    if reasons:
        lines.append("")
        lines.append("⚠️ *ملاحظات:*")
        for r in reasons[:5]:
            lines.append(f"  • {r}")

    return "\n".join(lines)
