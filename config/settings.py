"""
الإعدادات العامة للنظام.
كل القيم قابلة للتعديل من متغيرات البيئة (Environment Variables).
"""

import os
import logging
from zoneinfo import ZoneInfo

# ===========================================================
# التهيئة الأولى للتسجيل — قبل أي استخدام لـ logging
# ===========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("egx_bot")

# ===========================================================
# المنطقة الزمنية
# ===========================================================
CAIRO_TZ = ZoneInfo("Africa/Cairo")

# ===========================================================
# رأس المال وتوزيعه
# ===========================================================
TOTAL_CAPITAL = float(os.environ.get("TOTAL_CAPITAL", "10000"))

# نسبة رأس المال المخصصة لكل استراتيجية
CAPITAL_ALLOCATION = {
    "long_term": 0.80,   # 80% للاستثمار متوسط المدى
    "short_term": 0.20,  # 20% للسوينج
}

LONG_TERM_CAPITAL = TOTAL_CAPITAL * CAPITAL_ALLOCATION["long_term"]
SHORT_TERM_CAPITAL = TOTAL_CAPITAL * CAPITAL_ALLOCATION["short_term"]

# ===========================================================
# إدارة المخاطر
# ===========================================================
# نسبة المخاطرة لكل صفقة (تم تخفيضها من 1.5% إلى 1.0% لرأس مال صغير)
RISK_PER_TRADE = 0.010  # 1.0%

# الحد الأقصى لعدد الصفقات المفتوحة
MAX_LONG_POSITIONS = 5     # للاستثمار متوسط المدى
MAX_SHORT_POSITIONS = 2    # للسوينج

# حد أقصى لعدد الصفقات في نفس القطاع
MAX_TRADES_PER_SECTOR_LONG = 1   # سهم واحد لكل قطاع في الطويل
MAX_TRADES_PER_SECTOR_SHORT = 2  # سوينج

# الحد الأدنى لقيمة المركز (بالجنيه)
MIN_POSITION_VALUE = 1000

# الحد الأدنى للسعر لكل سهم
MIN_STOCK_PRICE = 5.0

# الحد الأدنى للسيولة اليومية (بالجنيه)
MIN_DAILY_LIQUIDITY = 200_000

# ===========================================================
# العمولات والضرائب (البورصة المصرية)
# ===========================================================
COMMISSION_RATE = 0.0015   # 0.15% عمولة سمسرة
SLIPPAGE_RATE = 0.001      # 0.10% انزلاق سعري
TAX_RATE = 0.00125         # 0.125% ضريبة دمغة
TOTAL_FEE_RATE = COMMISSION_RATE + SLIPPAGE_RATE + TAX_RATE  # ~0.375% لكل اتجاه

# ===========================================================
# وضع التشغيل
# ===========================================================
# MEASUREMENT_MODE=1 يعني محاكاة (paper trading)، 0 يعني حقيقي
MEASUREMENT_MODE = os.environ.get("MEASUREMENT_MODE", "1") == "1"

# FORCE_RUN=1 يعني تشغيل حتى لو السوق مقفول (للتشخيص)
FORCE_RUN = os.environ.get("FORCE_RUN", "0") == "1"

# ===========================================================
# إعدادات الجلب من المصادر
# ===========================================================
REQUEST_DELAY = 0.5      # ثانية بين كل طلب
MAX_RETRIES = 5          # عدد محاولات الفشل
REQUEST_TIMEOUT = 15     # ثانية

# ===========================================================
# إعدادات المؤشرات الفنية
# ===========================================================
ADX_THRESHOLD = 25            # أدنى ADX للسوينج
ADX_BONUS_THRESHOLD = 40      # ADX للجودة العالية
RSI_OVERBOUGHT = 75
RSI_OVERSOLD = 30
STOCH_OVERBOUGHT = 80

# ===========================================================
# إعدادات تليجرام
# ===========================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ===========================================================
# إعدادات GitHub
# ===========================================================
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")

# ===========================================================
# إعدادات الحلقة الرئيسية (Pulse Loop)
# ===========================================================
# للسوينج: 4 دورات × 30 ثانية = دقيقتين
SHORT_PULSE_CYCLES = 4
SHORT_PULSE_SLEEP = 30

# للاستثمار متوسط المدى: تشغيل واحد يوميًا (أو أسبوعيًا)
LONG_RUN_WEEKDAY = 3  # الخميس (0=الاثنين، 3=الخميس)

# ===========================================================
# ملفات الحالة (State Files)
# ===========================================================
STATE_FILES = {
    "long_positions": "long_positions.json",
    "short_positions": "short_positions.json",
    "long_watchlist": "long_watchlist.json",
    "dna_memory": "stocks_dna_memory.json",
    "sector_dna": "sector_dna_memory.json",
    "daily_stats": "daily_stats.json",
    "lock": "bot.lock",
}

# ===========================================================
# نظام DNA (للتعلم من الصفقات)
# ===========================================================
MIN_TRADES_FOR_RISK_ADJUST = 10   # حد أدنى من الصفقات قبل تعديل المخاطرة
DNA_ADAPT_DAMPING = 0.5           # تخفيف قوة التعديل

# ===========================================================
# إعدادات ML
# ===========================================================
ML_MODEL_PATH = "ml/artifacts/egx_model.joblib"
ML_META_PATH = "ml/artifacts/model_meta.json"
ML_CONFIDENCE_THRESHOLD = 0.60  # أدنى ثقة لاعتبار الإشارة صالحة
ML_ENABLED = os.environ.get("ML_ENABLED", "1") == "1"

# ===========================================================
# إعدادات القاطع اليومي (Circuit Breaker)
# ===========================================================
DAILY_CIRCUIT_BREAKER_LOSSES = 3  # خسائر متتالية توقف الفتح

# ===========================================================
# دالة مساعدة للتحقق من الإعدادات
# ===========================================================
def validate_settings() -> list[str]:
    """
    يتحقق من صحة الإعدادات الأساسية.
    يرجع قائمة بالتحذيرات (فارغة لو كل شيء سليم).
    """
    warnings = []
    if TOTAL_CAPITAL < MIN_POSITION_VALUE * MAX_LONG_POSITIONS:
        warnings.append(
            f"⚠️ رأس المال {TOTAL_CAPITAL} أقل من الحد المطلوب "
            f"لـ {MAX_LONG_POSITIONS} مراكز × {MIN_POSITION_VALUE} ج.م"
        )
    if not TELEGRAM_BOT_TOKEN:
        warnings.append("⚠️ TELEGRAM_BOT_TOKEN غير مضبوط — لن تُرسل إشعارات")
    if not TELEGRAM_CHAT_ID:
        warnings.append("⚠️ TELEGRAM_CHAT_ID غير مضبوط — لن تُرسل إشعارات")
    return warnings


def print_summary():
    """يطبع ملخص الإعدادات عند بدء التشغيل."""
    logger.info("=" * 60)
    logger.info("⚙️  ملخص الإعدادات")
    logger.info("=" * 60)
    logger.info(f"💰 رأس المال الكلي     : {TOTAL_CAPITAL:,.0f} ج.م")
    logger.info(f"📈 الاستثمار الطويل    : {LONG_TERM_CAPITAL:,.0f} ج.م "
                f"({CAPITAL_ALLOCATION['long_term']*100:.0f}%)")
    logger.info(f"⚡ السوينج             : {SHORT_TERM_CAPITAL:,.0f} ج.م "
                f"({CAPITAL_ALLOCATION['short_term']*100:.0f}%)")
    logger.info(f"🎯 المخاطرة/صفقة       : {RISK_PER_TRADE*100:.2f}%")
    logger.info(f"💸 إجمالي العمولات     : {TOTAL_FEE_RATE*100:.3f}%")
    logger.info(f"📝 وضع التشغيل         : "
                f"{'محاكاة (Paper)' if MEASUREMENT_MODE else 'حقيقي (Live)'}")
    logger.info(f"🤖 ML مفعّل            : {'نعم' if ML_ENABLED else 'لا'}")
    logger.info(f"🌍 التوقيت             : {CAIRO_TZ}")
    logger.info("=" * 60)
    for w in validate_settings():
        logger.warning(w)
