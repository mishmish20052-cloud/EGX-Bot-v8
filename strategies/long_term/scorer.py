"""
تقييم الأسهم المرشحة للاستثمار متوسط المدى.

يستقبل قائمة الأسهم من screener، ويقيّمها بـ core.scoring
(70% فني + 30% أساسيات)، ويرجع قائمة مرتبة بأفضل المرشحين.

يتضمن أيضًا:
- اختيار متنوع بين القطاعات (أقصى 2 لكل قطاع)
- تقرير تنويع مفصل
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from core.scoring import score_stock, ScoreResult, get_weights_by_score
from core.fundamentals import fetch_fundamentals_dict, compute_sector_strength
from config.stocks import SHARIA_STOCKS, get_sector
from config.settings import MAX_TRADES_PER_SECTOR_LONG
from strategies.long_term.screener import ScreenedStock

logger = logging.getLogger("egx_bot.long_term.scorer")


# ===========================================================
# نموذج النتيجة
# ===========================================================
@dataclass
class ScoredCandidate:
    """سهم تم تقييمه بدرجة نهائية."""
    symbol: str
    name: str
    sector: str
    total_score: float
    technical_score: float
    fundamental_score: float
    grade: str
    sector_strength: float
    data: dict = field(default_factory=dict)
    score_details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "total_score": round(self.total_score, 1),
            "technical_score": round(self.technical_score, 1),
            "fundamental_score": round(self.fundamental_score, 1),
            "grade": self.grade,
            "sector_strength": round(self.sector_strength, 1),
        }


# ===========================================================
# حساب قوة القطاعات
# ===========================================================
def compute_sector_strengths(stocks_data: dict) -> dict[str, float]:
    """
    يحسب قوة كل قطاع بناءً على متوسط أداء أسهمه.
    """
    sectors_map = {sym: get_sector(sym) for sym in stocks_data.keys()}
    return compute_sector_strength(stocks_data, sectors_map)


# ===========================================================
# جلب الأساسيات
# ===========================================================
def fetch_all_fundamentals(symbols: list[str]) -> dict[str, dict]:
    """
    يجلب الأساسيات لكل الأسهم مرة واحدة.
    """
    try:
        fundamentals = fetch_fundamentals_dict(symbols)
        logger.info(f"📊 تم جلب أساسيات {len(fundamentals)} سهم")
        return fundamentals
    except Exception as e:
        logger.warning(f"⚠️ فشل جلب الأساسيات: {e}")
        return {}


# ===========================================================
# تقييم مرشح واحد
# ===========================================================
def score_candidate(
    candidate: ScreenedStock,
    fundamental: Optional[dict] = None,
    sector_strength: float = 50.0,
) -> ScoredCandidate:
    """
    تقييم مرشح واحد بـ core.scoring.
    """
    symbol = candidate.symbol
    name = SHARIA_STOCKS.get(symbol, (symbol, "OTHER"))[0]
    sector = get_sector(symbol)

    # استدعاء دالة التقييم المركّب
    result: ScoreResult = score_stock(
        symbol=symbol,
        technical=candidate.data,
        fundamental=fundamental,
        sector_strength=sector_strength,
    )

    return ScoredCandidate(
        symbol=symbol,
        name=name,
        sector=sector,
        total_score=result.total,
        technical_score=result.technical_score,
        fundamental_score=result.fundamental_score,
        grade=result.grade,
        sector_strength=sector_strength,
        data=candidate.data,
        score_details=result.to_dict(),
    )


# ===========================================================
# الدالة الرئيسية: تقييم قائمة مرشحين
# ===========================================================
def score_candidates(
    candidates: list[ScreenedStock],
    min_score: float = 55.0,
    fetch_fundamentals_flag: bool = True,
) -> list[ScoredCandidate]:
    """
    تقييم قائمة كاملة من المرشحين.

    المعاملات:
    - candidates: من screener.screen_batch
    - min_score: الحد الأدنى للدرجة (افتراضي 55)
    - fetch_fundamentals_flag: هل نجيب الأساسيات؟

    ترجع: قائمة مرتبة تنازليًا حسب الدرجة.
    """
    if not candidates:
        logger.info("لا يوجد مرشحون للتقييم")
        return []

    # 1. حساب قوة القطاعات (من كل الأسهم المتاحة)
    stocks_data = {c.symbol: c.data for c in candidates}
    sector_strengths = compute_sector_strengths(stocks_data)

    # 2. جلب الأساسيات (اختياري)
    fundamentals: dict[str, dict] = {}
    if fetch_fundamentals_flag:
        fundamentals = fetch_all_fundamentals([c.symbol for c in candidates])

    # 3. تقييم كل مرشح
    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        fundamental = fundamentals.get(candidate.symbol)
        sector_strength = sector_strengths.get(candidate.sector, 50.0)

        result = score_candidate(candidate, fundamental, sector_strength)

        # الفلترة بالدرجة
        if result.total_score < min_score:
            logger.debug(
                f"⏭️ {result.symbol}: score {result.total_score:.1f} "
                f"أقل من {min_score}"
            )
            continue

        scored.append(result)

    # 4. ترتيب تنازليًا
    scored.sort(key=lambda c: c.total_score, reverse=True)

    logger.info(
        f"🎯 التقييم المركّب: {len(scored)} من {len(candidates)} "
        f"مرشح فوق الحد {min_score}"
    )

    return scored


# ===========================================================
# الدالة الشاملة: من بيانات خام إلى أفضل المرشحين
# ===========================================================
def get_top_long_candidates(
    stocks_data: dict,
    min_score: float = 55.0,
    max_count: int = 5,
) -> list[ScoredCandidate]:
    """
    دالة شاملة: تأخذ بيانات كل الأسهم وترجع أفضل N مرشح.

    الخطوات:
    1. فلترة أولية (screener)
    2. تقييم مركّب (scoring)
    3. ترتيب وأخذ أفضل N
    """
    from strategies.long_term.screener import screen_batch

    # 1. الفلترة الأولية
    candidates = screen_batch(stocks_data)
    if not candidates:
        logger.info("لا يوجد مرشحون بعد الفلترة الأولية")
        return []

    # 2. التقييم المركّب
    scored = score_candidates(candidates, min_score=min_score)

    # 3. أفضل N
    return scored[:max_count]


# ===========================================================
# توزيع الأوزان
# ===========================================================
def suggest_position_weights(
    scored: list[ScoredCandidate],
    max_positions: int = 5,
) -> dict[str, float]:
    """
    يقترح أوزان كل سهم بناءً على درجته.

    ترجع: {symbol: weight_pct} حيث مجموع الأوزان = 100%.
    """
    if not scored:
        return {}

    top = scored[:max_positions]

    # مجموع الدرجات
    total_score = sum(c.total_score for c in top)
    if total_score <= 0:
        # وزع بالتساوي
        equal = 100.0 / len(top)
        return {c.symbol: round(equal, 2) for c in top}

    # وزن نسبي
    weights = {}
    for c in top:
        weights[c.symbol] = round((c.total_score / total_score) * 100, 2)

    return weights


# ===========================================================
# دوال مساعدة
# ===========================================================
def filter_by_grade(
    scored: list[ScoredCandidate],
    min_grade: str = "B",
) -> list[ScoredCandidate]:
    """يرجع الأسهم بدرجة معينة أو أعلى."""
    grade_order = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4, "A+": 5}
    min_level = grade_order.get(min_grade, 3)
    return [c for c in scored if grade_order.get(c.grade, 0) >= min_level]


def summary_text(scored: list[ScoredCandidate]) -> str:
    """نص ملخص للمرشحين (للتقارير)."""
    if not scored:
        return "لا يوجد مرشحون"

    lines = [f"📊 {len(scored)} مرشح:"]
    for c in scored[:10]:
        lines.append(
            f"  • {c.symbol} ({c.name[:20]}) | "
            f"درجة: {c.total_score:.0f} ({c.grade}) | "
            f"قطاع: {c.sector}"
        )
    return "\n".join(lines)


# ===========================================================
# اختيار الأسهم مع تنويع القطاعات
# ===========================================================
def select_diversified(
    scored: list[ScoredCandidate],
    max_count: int = 5,
    max_per_sector: int = None,
) -> list[ScoredCandidate]:
    """
    يختار أفضل N سهم مع ضمان تنويع القطاعات.

    القاعدة: أقصى max_per_sector سهم من نفس القطاع.

    المعاملات:
    - scored: قائمة الأسهم مرتبة تنازليًا حسب الدرجة
    - max_count: أقصى عدد نهائي (افتراضي 5)
    - max_per_sector: أقصى عدد من نفس القطاع
      (افتراضي من الإعدادات: MAX_TRADES_PER_SECTOR_LONG)

    ترجع: قائمة نهائية متنوعة.
    """
    if max_per_sector is None:
        max_per_sector = MAX_TRADES_PER_SECTOR_LONG

    selected: list[ScoredCandidate] = []
    sector_counts: dict[str, int] = {}
    skipped: list[str] = []

    for candidate in scored:
        if len(selected) >= max_count:
            break

        sector = candidate.sector
        current = sector_counts.get(sector, 0)

        # تجاوز لو القطاع وصل الحد
        if current >= max_per_sector:
            skipped.append(f"{candidate.symbol} ({sector})")
            continue

        selected.append(candidate)
        sector_counts[sector] = current + 1

    # تسجيل النتائج
    logger.info(
        f"🎯 التنويع: اخترنا {len(selected)} سهم من "
        f"{len(sector_counts)} قطاعات"
    )
    for sector, count in sector_counts.items():
        logger.debug(f"   • {sector}: {count} سهم")

    if skipped:
        logger.debug(f"⏭️ تم تخطي: {', '.join(skipped[:5])}")

    return selected


# ===========================================================
# تقرير التنويع
# ===========================================================
def diversification_report(
    selected: list[ScoredCandidate],
) -> dict:
    """
    تقرير مفصل عن تنويع المحفظة.

    ترجع:
    {
        "total_stocks": عدد الأسهم،
        "num_sectors": عدد القطاعات،
        "sectors": {اسم القطاع: {"count", "pct", "symbols"}},
        "is_well_diversified": هل التنويع جيد؟
    }
    """
    sectors: dict[str, list[str]] = {}
    for c in selected:
        sectors.setdefault(c.sector, []).append(c.symbol)

    total = len(selected)
    report = {
        "total_stocks": total,
        "num_sectors": len(sectors),
        "sectors": {},
        "is_well_diversified": len(sectors) >= min(3, total) if total > 0 else False,
    }

    for sector, symbols in sectors.items():
        report["sectors"][sector] = {
            "count": len(symbols),
            "pct": round(len(symbols) / total * 100, 1) if total > 0 else 0,
            "symbols": symbols,
        }

    return report


# ===========================================================
# الدالة الشاملة: من البيانات الخام إلى أفضل المرشحين
# مع التنويع
# ===========================================================
def get_top_long_candidates_diversified(
    stocks_data: dict,
    min_score: float = 55.0,
    max_count: int = 5,
    max_per_sector: int = None,
) -> tuple[list[ScoredCandidate], dict]:
    """
    دالة شاملة: تأخذ بيانات كل الأسهم وترجع أفضل N مع تنويع.

    ترجع: (قائمة المرشحين، تقرير التنويع)
    """
    from strategies.long_term.screener import screen_batch

    # 1. الفلترة الأولية
    candidates = screen_batch(stocks_data)
    if not candidates:
        logger.info("لا يوجد مرشحون بعد الفلترة الأولية")
        return ([], diversification_report([]))

    # 2. التقييم المركّب
    scored = score_candidates(candidates, min_score=min_score)

    # 3. الاختيار مع التنويع
    selected = select_diversified(
        scored,
        max_count=max_count,
        max_per_sector=max_per_sector,
    )

    # 4. التقرير
    report = diversification_report(selected)

    logger.info(
        f"✅ اخترنا {len(selected)} سهم من {report['num_sectors']} قطاعات"
    )

    return (selected, report)
