"""
EGX-Bot-v8 — الملف الرئيسي.

يحتوي على نقطتي دخول:
- run_short_bot(): تشغيل السوينج (يومي)
- run_long_bot(): تشغيل الاستثمار متوسط المدى (أسبوعي)

الاستخدام:
    python bot.py short    # تشغيل السوينج
    python bot.py long     # تشغيل الاستثمار متوسط المدى
    python bot.py          # تشغيل الاثنين
"""

import json
import logging
import sys
from datetime import datetime

from config.settings import (
    CAIRO_TZ,
    TOTAL_CAPITAL,
    SHORT_TERM_CAPITAL,
    LONG_TERM_CAPITAL,
    MEASUREMENT_MODE,
    FORCE_RUN,
    SHORT_PULSE_CYCLES,
    SHORT_PULSE_SLEEP,
    MIN_POSITION_VALUE,
    print_summary,
)
from config.stocks import (
    ALL_SYMBOLS,
    MARKET_PROXY_BASKET,
    defensive_symbols,
    get_name,
    get_sector,
)

from core.market_regime import (
    MarketRegime,
    classify_regime,
    apply_breadth_adjustment,
    should_skip_new_trades,
    should_use_defensive_only,
    get_max_trades,
    log_regime,
)

from data_sources import dispatcher
from state.manager import StateManager, today_str, bump_stat, set_meta
from state.github_backend import GitHubBackend

from notifications import telegram as tg
from notifications import templates as tpl

from strategies.shared.risk import (
    calculate_position,
    check_total_risk,
)
from strategies.short_term import evaluator as short_eval
from strategies.short_term import planner as short_plan
from strategies.long_term import screener as long_screen
from strategies.long_term import scorer as long_scorer
from strategies.long_term import portfolio as long_portfolio
from strategies.long_term import exit_engine as long_exit

logger = logging.getLogger("egx_bot")


# ===========================================================
# نقطة 1: تشغيل السوينج (Short-Term Bot)
# ===========================================================
def run_short_bot() -> None:
    """تشغيل بوت السوينج — دورة يومية بـ 4 نبضات."""
    logger.info("=" * 60)
    logger.info("⚡ تشغيل بوت السوينج")
    logger.info("=" * 60)

    # 1. تهيئة الحالة
    gh = GitHubBackend()
    state = StateManager(github_backend=gh)
    state.load_all(force_remote=True)

    # 2. تحديد حالة السوق
    regime = _get_market_regime()
    if regime is None:
        logger.error("❌ فشل تحليل حالة السوق — إيقاف")
        tg.send_error("فشل تحليل حالة السوق")
        return

    # 3. انهيار → إغلاق كل شيء
    if should_skip_new_trades(regime) and regime.risk_multiplier == 0.0:
        logger.warning("🚨 انهيار سوق — إيقاف")
        tg.send(tpl.market_crash(regime.change_pct, MEASUREMENT_MODE))
        return

    # 4. تقرير الصباح
    _send_morning_report(regime, state)

    # 5. حلقة النبض
    for cycle in range(SHORT_PULSE_CYCLES):
        logger.info(f"\n💓 نبضة {cycle + 1}/{SHORT_PULSE_CYCLES}")

        symbols = _get_symbols_for_scan(regime)
        stocks_data = dispatcher.fetch_stocks(symbols)

        if not stocks_data:
            logger.warning("لا توجد بيانات — تخطي النبضة")
            continue

        regime = apply_breadth_adjustment(regime, stocks_data)
        trades = state.get("short_positions", {})

        _track_short_positions(trades, stocks_data, regime, state)
        _scan_for_short_entries(trades, stocks_data, regime, state)

        state.save_all()

        if cycle < SHORT_PULSE_CYCLES - 1:
            logger.info(f"😴 نوم {SHORT_PULSE_SLEEP} ثانية...")
            import time
            time.sleep(SHORT_PULSE_SLEEP)

    # 6. تقرير الإغلاق
    _send_eod_report(state)

    logger.info("\n✅ انتهى بوت السوينج بنجاح")


# ===========================================================
# نقطة 2: تشغيل الاستثمار متوسط المدى (Long-Term Bot)
# ===========================================================
def run_long_bot() -> None:
    """تشغيل بوت الاستثمار متوسط المدى — تشغيل أسبوعي."""
    logger.info("=" * 60)
    logger.info("📈 تشغيل بوت الاستثمار متوسط المدى")
    logger.info("=" * 60)

    # 1. تهيئة الحالة
    gh = GitHubBackend()
    state = StateManager(github_backend=gh)
    state.load_all(force_remote=True)

    # 2. حالة السوق
    regime = _get_market_regime()
    if regime is None:
        logger.error("❌ فشل تحليل حالة السوق")
        tg.send_error("فشل تحليل حالة السوق (Long)")
        return

    # 3. انهيار → لا شراء
    if should_skip_new_trades(regime):
        logger.warning("🚨 السوق في حالة سيئة — لا شراء طويل المدى")
        tg.send(
            tpl.measurement_banner(MEASUREMENT_MODE) +
            f"⚠️ *لا شراء طويل المدى اليوم*\n"
            f"حالة السوق: `{regime.type}`"
        )
        state.save_all()
        return

    # 4. جلب بيانات كل الأسهم
    logger.info("📥 جلب بيانات كل الأسهم...")
    stocks_data = dispatcher.fetch_stocks(ALL_SYMBOLS)

    if not stocks_data:
        logger.error("❌ لا توجد بيانات")
        tg.send_error("لا توجد بيانات للتحليل الطويل")
        return

    logger.info(f"✅ تم جلب {len(stocks_data)} سهم")

    # 5. الفلترة الأولية
    logger.info("🔍 الفلترة الأولية...")
    from strategies.long_term.screener import screen_batch, screen_stock
    screened = screen_batch(stocks_data)
    logger.info(f"✅ {len(screened)} سهم اجتاز الفلترة الأولية")

    # جمع المرفوضين في الفلترة الأولية
    rejected_in_screening = []
    for symbol, data in stocks_data.items():
        passed, reason = screen_stock(symbol, data)
        if not passed:
            rejected_in_screening.append({
                "symbol": symbol,
                "reason": reason,
                "stage": "screening",
            })

    # 6. التقييم المركب
    logger.info("🎯 التقييم المركب...")
    scored_all = long_scorer.score_candidates(screened, min_score=0.0)

    # المرفوضون في التقييم
    rejected_in_scoring = []
    accepted_for_ranking = []

    for candidate in scored_all:
        if candidate.total_score >= 55.0:
            accepted_for_ranking.append(candidate)
        else:
            rejected_in_scoring.append({
                "symbol": candidate.symbol,
                "reason": f"score {candidate.total_score:.1f} < 55",
                "stage": "scoring",
                "score": candidate.total_score,
            })

    # 7. الاختيار المتنوع
    selected = long_scorer.select_diversified(
        accepted_for_ranking,
        max_count=5,
    )
    divers_report = long_scorer.diversification_report(selected)

    # المرفوضون بسبب التنويع
    selected_syms = {c.symbol for c in selected}
    rejected_in_diversification = []
    for candidate in accepted_for_ranking:
        if candidate.symbol not in selected_syms:
            rejected_in_diversification.append({
                "symbol": candidate.symbol,
                "reason": f"القطاع {candidate.sector} وصل الحد الأقصى",
                "stage": "diversification",
                "score": candidate.total_score,
            })

    # --- حفظ تقرير الفلترة كامل ---
    all_rejected = (
        rejected_in_screening +
        rejected_in_scoring +
        rejected_in_diversification
    )
    _save_screening_report_json(
        accepted=selected,
        rejected=all_rejected,
        total_screened=len(stocks_data),
    )

    if not selected:
        logger.info("لا يوجد مرشحون للاستثمار")
        tg.send(
            tpl.measurement_banner(MEASUREMENT_MODE) +
            "📭 *لا يوجد مرشحون* للاستثمار متوسط المدى اليوم"
        )
        _send_screening_report_tg(
            selected=[],
            rejected=all_rejected[:10],
            total=len(stocks_data),
        )
        # ✅ نرسل تقرير الإغلاق كذلك
        _send_eod_report(state)
        state.save_all()
        return

    logger.info(f"✅ {len(selected)} مرشح اجتازوا الفلترة")

    # 8. إدارة المحفظة الحالية
    open_positions = state.get("long_positions", {})

    _track_long_positions(open_positions, stocks_data, state)
    open_positions = state.get("long_positions", {})

    # 9. فحص إمكانية فتح صفقات جديدة
    accepted, decisions = long_portfolio.select_final_candidates(
        selected, open_positions
    )

    # 10. إرسال تقرير الفلترة على تليجرام
    _send_screening_report_tg(
        selected=selected,
        rejected=all_rejected[:8],
        total=len(stocks_data),
    )

    if not accepted:
        logger.info("لا توجد صفقات جديدة ممكنة")
        _send_long_report(selected, decisions, open_positions, divers_report, state)
        # ✅ إرسال تقرير الإغلاق
        _send_eod_report(state)
        state.save_all()
        return

    logger.info(f"✅ {len(accepted)} صفقة جديدة ممكنة")

    # 11. توزيع الأوزان
    allocations = long_portfolio.allocate_weights(accepted, open_positions)

    # 12. فتح الصفقات الجديدة
    for candidate in accepted:
        if candidate.symbol not in allocations:
            continue
        _open_long_position(candidate, allocations[candidate.symbol], state)

    # 13. تقرير نهائي
    _send_long_report(selected, decisions, open_positions, divers_report, state)

    # ✅ إرسال تقرير الإغلاق
    _send_eod_report(state)

    state.save_all()
    logger.info("\n✅ انتهى بوت الاستثمار متوسط المدى بنجاح")


# ===========================================================
# الدوال المساعدة (Helpers)
# ===========================================================
def _get_market_regime() -> MarketRegime:
    """يجلب حالة السوق من EGX30 أو سلة بديلة أو fallback نهائي."""
    index_data = dispatcher.fetch_market_index()

    if index_data and index_data.get("close", 0) > 0:
        regime = classify_regime(
            close=index_data.get("close", 0),
            open_price=index_data.get("open", 0),
            ema50=index_data.get("ema50", 0),
            ema200=index_data.get("ema200", 0),
            rsi_val=index_data.get("rsi", 50),
            macd_val=index_data.get("macd", 0),
            macd_signal=index_data.get("macd_signal", 0),
        )
        regime.source = index_data.get("source", "EGX30")
        return regime

    logger.warning("⚠️ EGX30 غير متاح — استخدام سلة بديلة")
    basket_data = dispatcher.fetch_market_basket(MARKET_PROXY_BASKET)

    if len(basket_data) >= 3:
        closes = [d["close"] for d in basket_data.values()]
        opens = [d["open"] for d in basket_data.values()]
        ema50s = [d.get("ema50_daily", d["close"]) for d in basket_data.values()]
        rsis = [d.get("rsi", 50) for d in basket_data.values()]

        avg_close = sum(closes) / len(closes)
        avg_open = sum(opens) / len(opens)
        avg_ema50 = sum(ema50s) / len(ema50s)
        avg_rsi = sum(rsis) / len(rsis)

        regime = classify_regime(
            close=avg_close,
            open_price=avg_open,
            ema50=avg_ema50,
            ema200=0,
            rsi_val=avg_rsi,
            macd_val=0,
            macd_signal=0,
        )
        regime.source = f"basket({len(basket_data)})"
        return regime

    logger.warning("⚠️ فشل جلب بيانات السوق — fallback: SIDEWAYS")
    return MarketRegime(
        type="SIDEWAYS",
        risk="MEDIUM",
        risk_multiplier=0.8,
        max_trades=3,
        source="fallback",
        change_pct=0.0,
        breadth_pct=None,
    )


def _get_symbols_for_scan(regime: MarketRegime) -> list[str]:
    """يحدد الأسهم المرشحة للفحص حسب حالة السوق."""
    if should_use_defensive_only(regime):
        return defensive_symbols()
    return ALL_SYMBOLS


def _send_morning_report(regime: MarketRegime, state: StateManager) -> None:
    """يرسل تقرير الصباح (مرة واحدة يوميًا)."""
    meta = state.get("daily_stats", {}).get("_meta", {})
    today = today_str()
    if meta.get("morning_report") == today:
        return

    try:
        msg = tpl.morning_report(regime.to_dict(), MEASUREMENT_MODE)
        tg.send(msg)
        set_meta(state, "morning_report", today)
    except Exception as e:
        logger.error(f"فشل تقرير الصباح: {e}")


def _send_eod_report(state: StateManager) -> None:
    """
    يرسل تقرير نهاية اليوم — فقط بعد 2:30 م القاهرة.

    ✅ إصلاح: يقرأ من long_positions + short_positions
    ✅ إصلاح: يعرض قائمة المراكز المفتوحة
    """
    now = datetime.now(CAIRO_TZ)
    if now.hour < 14 or (now.hour == 14 and now.minute < 30):
        return

    meta = state.get("daily_stats", {}).get("_meta", {})
    today = today_str()
    if meta.get("eod_report") == today:
        return

    stats = state.get("daily_stats", {}).get(today, {})

    # ✅ نجمع الطويل + السوينج
    short_trades = state.get("short_positions", {})
    long_trades = state.get("long_positions", {})
    total_open = len(short_trades) + len(long_trades)

    try:
        msg = tpl.eod_report(
            stats,
            total_open,
            measurement_mode=MEASUREMENT_MODE,
        )

        # ✅ نضيف قائمة المراكز الطويلة المفتوحة
        if long_trades:
            msg += "\n\n📊 *المراكز الطويلة المفتوحة:*\n"
            for symbol, pos in list(long_trades.items())[:5]:
                name = pos.get("name", symbol)
                entry = pos.get("entry_price", 0)
                stop = pos.get("current_stop", pos.get("stop_loss", 0))
                shares = pos.get("shares", 0)
                remaining = pos.get("remaining", shares)
                msg += (
                    f"  • `{symbol}` — دخول `{entry:.2f}` | "
                    f"ستوب `{stop:.2f}` | `{remaining}` سهم\n"
                )

        # ✅ نضيف قائمة صفقات السوينج المفتوحة
        if short_trades:
            msg += "\n⚡ *صفقات السوينج المفتوحة:*\n"
            for symbol, pos in list(short_trades.items())[:5]:
                entry = pos.get("entry_price", 0)
                stop = pos.get("current_stop", pos.get("sl", 0))
                shares = pos.get("shares", 0)
                remaining = pos.get("remaining", shares)
                msg += (
                    f"  • `{symbol}` — دخول `{entry:.2f}` | "
                    f"ستوب `{stop:.2f}` | `{remaining}` سهم\n"
                )

        if total_open == 0:
            msg += "\n💼 لا توجد مراكز مفتوحة حالياً"

        tg.send(msg)
        set_meta(state, "eod_report", today)
    except Exception as e:
        logger.error(f"فشل تقرير الإغلاق: {e}")


# ===========================================================
# دوال حفظ وإرسال تقرير الفلترة
# ===========================================================
def _save_screening_report_json(
    accepted: list,
    rejected: list,
    total_screened: int,
) -> None:
    """يحفظ تقرير الفلترة كامل في JSON."""
    try:
        today = today_str()
        report = {
            "date": today,
            "timestamp": datetime.now(CAIRO_TZ).isoformat(),
            "total_screened": total_screened,
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "accepted": [
                {
                    "symbol": c.symbol,
                    "name": c.name,
                    "sector": c.sector,
                    "total_score": c.total_score,
                    "technical_score": c.technical_score,
                    "fundamental_score": c.fundamental_score,
                    "grade": c.grade,
                    "sector_strength": c.sector_strength,
                    "score_details": c.score_details,
                }
                for c in accepted
            ],
            "rejected": rejected,
        }

        # حفظ كـ JSON محلي
        with open("screening_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # حفظ نسخة باسم اليوم للرجوع
        archive_name = f"screening_{today}.json"
        with open(archive_name, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"💾 تم حفظ تقرير الفلترة: {archive_name}")
    except Exception as e:
        logger.error(f"فشل حفظ تقرير الفلترة: {e}")


def _send_screening_report_tg(
    selected: list,
    rejected: list,
    total: int,
) -> None:
    """يرسل تقرير الفلترة على تليجرام."""
    try:
        msg = _build_screening_text(selected, rejected, total)
        tg.send(msg)
    except Exception as e:
        logger.error(f"فشل إرسال تقرير الفلترة: {e}")


def _build_screening_text(selected: list, rejected: list, total: int) -> str:
    """يبني نص تقرير الفلترة."""
    banner = tpl.measurement_banner(MEASUREMENT_MODE)
    lines = [
        "📊 *تقرير الفلترة والتقييم*",
        f"📅 {today_str()}",
        "━━━━━━━━━━━━━━━━━",
        "",
        f"🔍 *إجمالي الأسهم:* `{total}`",
        f"✅ *مقبول:* `{len(selected)}`",
        f"❌ *مرفوض:* `{len(rejected)}`",
        "",
    ]

    if selected:
        lines.append("━━━━━━━━━━━━━━━━━")
        lines.append("✅ *المرشحون النهائيون:*")
        for c in selected[:5]:
            lines.append(
                f"  • `{c.symbol}` ({c.grade}) — {c.total_score:.0f}/100"
            )
        lines.append("")

    if rejected:
        lines.append("━━━━━━━━━━━━━━━━━")
        lines.append("❌ *أبرز المرفوضين:*")
        for r in rejected[:5]:
            lines.append(f"  • `{r.get('symbol', '?')}`")
            lines.append(f"    ↳ {r.get('reason', '؟')}")

    return banner + "\n".join(lines)


# ===========================================================
# دوال التشغيل (Short-Term)
# ===========================================================
def _track_short_positions(
    trades: dict,
    stocks_data: dict,
    regime: MarketRegime,
    state: StateManager,
) -> None:
    """متابعة الصفقات المفتوحة (T1/T2/T3 + Stops)."""
    symbols_to_remove = []

    for symbol, position in list(trades.items()):
        if symbol not in stocks_data:
            continue

        data = stocks_data[symbol]
        event = long_exit.process_position(symbol, position, data)

        if event is None:
            continue

        if event.is_full_exit:
            symbols_to_remove.append(symbol)
            _send_short_exit_message(symbol, position, event)
            bump_stat(state, "wins" if event.is_win else "losses")
        else:
            updated = long_exit.apply_exit_event(position, event)
            trades[symbol] = updated
            _send_short_exit_message(symbol, position, event)

    for symbol in symbols_to_remove:
        if symbol in trades:
            del trades[symbol]

    state.set("short_positions", trades)


def _scan_for_short_entries(
    trades: dict,
    stocks_data: dict,
    regime: MarketRegime,
    state: StateManager,
) -> None:
    """يبحث عن صفقات سوينج جديدة."""
    max_trades = get_max_trades(regime, MEASUREMENT_MODE)
    current = len(trades)

    if current >= max_trades:
        return

    can_risk, risk_pct = check_total_risk(trades, capital=SHORT_TERM_CAPITAL)
    if not can_risk:
        logger.warning(f"⚠️ المخاطرة الكلية {risk_pct}% مرتفعة")
        return

    candidates = []
    for symbol, data in stocks_data.items():
        if symbol in trades:
            continue

        result = short_eval.evaluate_signal(
            symbol, data, regime.risk_multiplier
        )
        if result.passed:
            candidates.append(result)

    candidates.sort(key=lambda r: r.score, reverse=True)

    for result in candidates:
        if len(trades) >= max_trades:
            break

        data = stocks_data[result.symbol]

        plan = short_plan.build_plan(
            symbol=result.symbol,
            data=data,
            signal_type=result.signal_type,
            capital=SHORT_TERM_CAPITAL,
        )

        if not plan.valid:
            continue

        sector = data.get("sector", "OTHER")
        sector_count = sum(
            1 for s in trades
            if stocks_data.get(s, {}).get("sector") == sector
        )
        if sector_count >= 2:
            continue

        _open_short_position(result, plan, state)
        trades[result.symbol] = {
            "entry_price": plan.entry_price,
            "shares": plan.shares,
            "remaining": plan.shares,
            "sl": plan.stop_loss,
            "current_stop": plan.stop_loss,
            "t1": plan.t1,
            "t2": plan.t2,
            "t3": plan.t3,
            "entry_date": today_str(),
            "t1_hit": False,
            "t2_hit": False,
            "t3_hit": False,
            "trailing_active": False,
        }
        bump_stat(state, "signals")

    state.set("short_positions", trades)


def _open_short_position(result, plan, state: StateManager) -> None:
    """يرسل رسالة فتح صفقة سوينج."""
    try:
        msg = tpl.entry_signal(
            symbol=result.symbol,
            name=result.details.get("name", result.symbol),
            sector=result.details.get("sector", "OTHER"),
            signal_type=result.signal_type,
            score=result.score,
            plan=plan.to_dict(),
            market_regime="Swing",
            measurement_mode=MEASUREMENT_MODE,
        )
        tg.send(msg)
    except Exception as e:
        logger.error(f"فشل إرسال إشارة {result.symbol}: {e}")


def _send_short_exit_message(symbol: str, position: dict, event) -> None:
    """يرسل رسالة خروج/بيع جزئي."""
    try:
        if event.event_type in ("T1", "T2", "T3"):
            msg = tpl.target_hit(
                symbol=symbol,
                name=position.get("name", symbol),
                price=event.price,
                target_label=event.event_type,
                sold_shares=event.sold_shares,
                remaining=event.remaining_shares,
                net_profit=event.net_pnl,
                new_stop=event.new_stop,
                measurement_mode=MEASUREMENT_MODE,
            )
        elif event.event_type in ("STOP", "TRAIL"):
            msg = tpl.stop_hit(
                symbol=symbol,
                name=position.get("name", symbol),
                stop_price=event.price,
                sold_shares=event.sold_shares,
                net_pnl=event.net_pnl,
                is_win=event.is_win,
                measurement_mode=MEASUREMENT_MODE,
            )
        else:
            msg = (
                tpl.measurement_banner(MEASUREMENT_MODE) +
                f"🔄 *{event.event_type}* — `{symbol}`\n"
                f"💵 السعر: `{event.price:.2f}`\n"
                f"📊 صافي: `{event.net_pnl:,.0f}` ج.م"
            )
        tg.send(msg)
    except Exception as e:
        logger.error(f"فشل إرسال حدث {event.event_type}: {e}")


# ===========================================================
# دوال التشغيل (Long-Term)
# ===========================================================
def _track_long_positions(
    positions: dict,
    stocks_data: dict,
    state: StateManager,
) -> None:
    """متابعة صفقات الاستثمار الطويلة."""
    symbols_to_remove = []

    for symbol, position in list(positions.items()):
        if symbol not in stocks_data:
            continue

        data = stocks_data[symbol]
        event = long_exit.process_position(symbol, position, data)

        if event is None:
            continue

        if event.is_full_exit:
            symbols_to_remove.append(symbol)
            _send_long_exit_message(symbol, position, event)
            bump_stat(state, "wins" if event.is_win else "losses")
        else:
            updated = long_exit.apply_exit_event(position, event)
            positions[symbol] = updated
            _send_long_exit_message(symbol, position, event)

    for symbol in symbols_to_remove:
        if symbol in positions:
            del positions[symbol]

    state.set("long_positions", positions)


def _open_long_position(candidate, allocation: dict, state: StateManager) -> None:
    """يفتح صفقة استثمار طويلة جديدة مع تفصيل كامل."""
    entry = candidate.data.get("close", 0)
    atr = candidate.data.get("atr", entry * 0.025)
    capital_alloc = allocation.get("weight_egp", 0)

    if entry <= 0 or capital_alloc <= 0:
        return

    shares = int(capital_alloc // entry)
    if shares < 1:
        return

    stop_distance = max(atr * 2.5, entry * 0.10)
    stop_loss = round(entry - stop_distance, 2)

    positions = state.get("long_positions", {})
    position = long_portfolio.build_position_record(
        candidate=candidate,
        entry_price=entry,
        shares=shares,
        allocation_egp=capital_alloc,
    )
    position = long_exit.attach_targets_to_position(
        position, entry, stop_loss, atr
    )
    positions[candidate.symbol] = position
    state.set("long_positions", positions)

    bump_stat(state, "signals")

    # استخدام القالب المفصل
    try:
        plan_dict = {
            "entry_price": entry,
            "shares": shares,
            "sl": stop_loss,
            "loss_egp": round(shares * (entry - stop_loss), 2),
            "t1": position["t1"],
            "t2": position["t2"],
            "t3": position["t3"],
            "t4": position["t4"],
            "p1": round(shares * (position["t1"] - entry), 2),
            "p2": round(shares * (position["t2"] - entry), 2),
            "p3": round(shares * (position["t3"] - entry), 2),
            "weight": round(capital_alloc / LONG_TERM_CAPITAL * 100, 2),
            "rr_ratio": round(
                (position["t1"] - entry) / (entry - stop_loss), 2
            ) if (entry - stop_loss) > 0 else 0,
        }

        msg = tpl.entry_signal_detailed(
            symbol=candidate.symbol,
            name=candidate.name,
            sector=candidate.sector,
            signal_type="شراء طويل المدى",
            score=candidate.total_score,
            plan=plan_dict,
            market_regime="Long-Term",
            score_details=candidate.score_details,
            measurement_mode=MEASUREMENT_MODE,
        )
        tg.send(msg)
    except Exception as e:
        logger.error(f"فشل إرسال رسالة شراء {candidate.symbol}: {e}")


def _send_long_exit_message(symbol: str, position: dict, event) -> None:
    """يرسل رسالة خروج لصفقة طويل المدى."""
    try:
        if event.event_type in ("T1", "T2", "T3", "T4"):
            msg = tpl.target_hit(
                symbol=symbol,
                name=position.get("name", symbol),
                price=event.price,
                target_label=event.event_type,
                sold_shares=event.sold_shares,
                remaining=event.remaining_shares,
                net_profit=event.net_pnl,
                new_stop=event.new_stop,
                measurement_mode=MEASUREMENT_MODE,
            )
        elif event.event_type in ("STOP", "TRAIL"):
            msg = tpl.stop_hit(
                symbol=symbol,
                name=position.get("name", symbol),
                stop_price=event.price,
                sold_shares=event.sold_shares,
                net_pnl=event.net_pnl,
                is_win=event.is_win,
                measurement_mode=MEASUREMENT_MODE,
            )
        else:
            msg = (
                tpl.measurement_banner(MEASUREMENT_MODE) +
                f"🔄 *{event.event_type}* — `{symbol}`\n"
                f"💵 السعر: `{event.price:.2f}`\n"
                f"📝 {event.note}\n"
                f"📊 صافي: `{event.net_pnl:,.0f}` ج.م"
            )
        tg.send(msg)
    except Exception as e:
        logger.error(f"فشل إرسال حدث {event.event_type}: {e}")


def _send_long_report(
    candidates: list,
    decisions: list,
    open_positions: dict,
    divers_report: dict,
    state: StateManager,
) -> None:
    """يرسل تقرير الاستثمار الطويل."""
    try:
        msg = (
            tpl.measurement_banner(MEASUREMENT_MODE) +
            f"📊 *تقرير الاستثمار متوسط المدى*\n\n"
            f"🎯 المرشحون: `{len(candidates)}`\n"
            f"✅ مقبولون: `{sum(1 for d in decisions if d.can_open)}`\n"
            f"💼 المراكز المفتوحة: `{len(open_positions)}`\n"
            f"🏢 القطاعات: `{divers_report.get('num_sectors', 0)}`\n\n"
            f"📈 *أفضل المرشحين:*\n"
        )
        for c in candidates[:5]:
            msg += f"  • `{c.symbol}` ({c.grade}) — {c.total_score:.0f}/100\n"

        msg += "\n" + long_portfolio.portfolio_summary(open_positions)

        tg.send(msg)
    except Exception as e:
        logger.error(f"فشل إرسال تقرير الاستثمار: {e}")


# ===========================================================
# الدالة الرئيسية
# ===========================================================
def main() -> None:
    """نقطة الدخول الرئيسية."""
    print_summary()

    mode = sys.argv[1] if len(sys.argv) > 1 else "both"

    try:
        if mode in ("short", "both"):
            run_short_bot()
        if mode in ("long", "both"):
            run_long_bot()
    except Exception as e:
        logger.exception(f"💥 خطأ غير متوقع: {e}")
        tg.send_error(f"خطأ غير متوقع: {e}")


if __name__ == "__main__":
    main()
