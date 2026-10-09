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
# 2. إشارة دخول
# ===========================================================
def entry_signal(
    symbol: str,
    name: str,
    sector: str,
    signal_type: str,           # "Trend 📈" أو "Super Breakout 🚀"
    score: float,
    plan: dict,                  # من make_plan
    market_regime: str,
    measurement_mode: bool = False,
) -> str:
    """رسالة إشارة شراء."""
    banner = measurement_banner(measurement_mode)

    return (
        banner +
        f"🚀 *{signal_type}*\n"
        f"🎖️ الجودة: `{score:.0f}/100` → "
        f"الوزن: `{plan.get('weight', 0):.1f}%`\n\n"
        f"🌍 السوق: `{market_regime}`\n"
        f"📌 `{symbol} - {name}` ({sector})\n"
        f"💵 دخول: `{plan.get('entry_price', 0):.2f}`\n"
        f"📦 الكمية: `{plan.get('shares', 0)}` سهم "
        f"(بقيمة `{plan.get('position_value', 0):,.0f}` ج.م)\n"
        f"💰 نسبة من رأس المال: `{plan.get('weight', 0):.1f}%`\n\n"
        f"💸 الخسارة عند الستوب `{plan.get('sl', 0):.2f}`: "
        f"≈ `{plan.get('loss_egp', 0):,.0f}` ج.م\n"
        f"🛡️ المخاطرة: `{plan.get('risk_pct', 0):.2f}%`\n"
        f"✅ R:R = `1:{plan.get('rr_ratio', 0):.2f}`\n\n"
        f"🎯 *الأهداف:*\n"
        f"  T1 `{plan.get('t1', 0):.2f}`: +`{plan.get('p1', 0):,.0f}` ج.م\n"
        f"  T2 `{plan.get('t2', 0):.2f}`: +`{plan.get('p2', 0):,.0f}` ج.م\n"
        f"  T3 `{plan.get('t3', 0):.2f}`: +`{plan.get('p3', 0):,.0f}` ج.م"
    )


# ===========================================================
# 3. الأهداف (T1 / T2 / T3)
# ===========================================================
def target_hit(
    symbol: str,
    name: str,
    price: float,
    target_label: str,          # "T1" / "T2" / "T3"
    sold_shares: int,
    remaining: int,
    net_profit: float,
    new_stop: Optional[float] = None,
    measurement_mode: bool = False,
) -> str:
    """رسالة تحقق هدف."""
    banner = measurement_banner(measurement_mode)

    emoji = {"T1": "🎯", "T2": "🚀", "T3": "🔥"}.get(target_label, "🎯")
    portion_text = {"T1": "40%", "T2": "30%", "T3": "المتبقي"}.get(target_label, "")

    stop_line = ""
    if new_stop is not None:
        stop_label = {
            "T1": "نقطة التعادل",
            "T2": "قفل ربح — يتحرك تلقائيًا",
        }.get(target_label, "")
        stop_line = f"\n🛑 *الستوب الجديد:* `{new_stop:.2f}` ({stop_label})"

    complete_line = "\n✅ *صفقة مكتملة بنجاح*" if target_label == "T3" else ""

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
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار القوالب")
    print("=" * 60)

    # 1. تقرير الصباح
    regime = {
        "type": "BULL 🟢",
        "risk": "LOW",
        "change_pct": 1.25,
        "max_trades": 4,
        "source": "EGX30",
        "breadth_pct": 35.0,
    }
    print("\n1️⃣ تقرير الصباح:")
    print(morning_report(regime))

    # 2. إشارة دخول
    plan = {
        "entry_price": 25.50,
        "shares": 100,
        "position_value": 2550,
        "weight": 25.5,
        "sl": 24.50,
        "loss_egp": 100,
        "risk_pct": 1.0,
        "rr_ratio": 2.5,
        "t1": 27.00, "p1": 150,
        "t2": 29.00, "p2": 350,
        "t3": 32.00, "p3": 650,
    }
    print("\n2️⃣ إشارة دخول:")
    print(entry_signal(
        "TMGH", "طلعت مصطفى", "REALESTATE",
        "Trend 📈", 78, plan, "BULL 🟢"
    ))

    # 3. تحقق هدف
    print("\n3️⃣ T1 تحقق:")
    print(target_hit(
        "TMGH", "طلعت مصطفى", 27.00, "T1",
        40, 60, 60.00, new_stop=25.50
    ))

    # 4. ستوب
    print("\n4️⃣ ستوب:")
    print(stop_hit(
        "TMGH", "طلعت مصطفى", 24.50,
        60, -60.00, is_win=False
    ))

    print("\n" + "=" * 60)
    print("✅ اختبار القوالب اكتمل")
