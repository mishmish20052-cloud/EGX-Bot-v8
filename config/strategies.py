"""
معايير الاستراتيجيتين:
- الاستثمار متوسط المدى (3 شهور) — 80% من رأس المال
- السوينج قصير المدى (أيام إلى أسابيع) — 20% من رأس المال
"""

from dataclasses import dataclass, field


# ===========================================================
# معايير الاستثمار متوسط المدى (3 شهور)
# ===========================================================
@dataclass
class LongTermStrategy:
    """معايير اختيار وإدارة صفقات الاستثمار متوسط المدى."""

    # --- معايير الاختيار ---
    # الاتجاه: EMA50 > EMA200 (إجباري)
    require_uptrend: bool = True

    # القوة النسبية: السهم أعلى من السوق خلال 60 يوم (إجباري)
    require_relative_strength: bool = True

    # السيولة اليومية (إجباري)
    min_daily_liquidity_egp: float = 200_000

    # سعر السهم
    min_price: float = 5.0
    max_price: float = 500.0

    # --- التقييم المركّب (المجموع 100) ---
    # 70% فني
    weights_technical: dict = field(default_factory=lambda: {
        "trend": 25,         # اتجاه صاعد (EMA50 > EMA200)
        "momentum": 15,      # زخم 60 يوم
        "relative_strength": 15,  # قوة نسبية أمام السوق
        "sector_strength": 10,    # قوة القطاع
        "liquidity": 5,      # سيولة عالية
    })
    # 30% أساسيات
    weights_fundamental: dict = field(default_factory=lambda: {
        "valuation": 10,     # تقييم معقول (P/E)
        "earnings_growth": 10,  # نمو الأرباح
        "profitability": 10,    # ربحية (ROE/ROA)
    })

    # --- إدارة الصفقة ---
    # أهداف الخروج المتدرج
    targets: list = field(default_factory=lambda: [
        {"pct": 0.10, "sell_portion": 0.25, "label": "T1"},
        {"pct": 0.25, "sell_portion": 0.25, "label": "T2"},
        {"pct": 0.45, "sell_portion": 0.25, "label": "T3"},
        {"pct": 0.70, "sell_portion": 1.00, "label": "T4"},
    ])

    # حد الخسارة الأولي
    initial_stop_pct: float = 0.15  # 15%

    # الخروج عند كسر EMA50
    exit_on_ema50_break: bool = True

    # الخروج عند إشارة انعكاس قوية (RSI < 30 + MACD سلبي)
    exit_on_reversal_signal: bool = True

    # --- مدة الاحتفاظ ---
    min_holding_days: int = 30    # شهر على الأقل
    max_holding_days: int = 90    # 3 شهور كحد أقصى


# ===========================================================
# معايير السوينج (قصير المدى)
# ===========================================================
@dataclass
class ShortTermStrategy:
    """معايير اختيار وإدارة صفقات السوينج."""

    # --- معايير الاختيار ---
    min_adx: float = 25              # قوة الاتجاه
    min_rvol: float = 1.2            # حجم نسبي
    rsi_min: float = 40
    rsi_max: float = 70
    stoch_max: float = 80

    # آلية الدخول المركبة
    entry_conditions: dict = field(default_factory=lambda: {
        "rsi_in_range": True,          # RSI بين 40 و 70
        "ema_cross_bullish": True,     # EMA20 > EMA50
        "macd_positive": True,         # MACD > Signal
        "volume_confirmation": True,   # RVOL > 1.2
        "price_above_ema25": True,     # السعر أعلى من EMA25
    })

    # --- إدارة الصفقة ---
    targets: list = field(default_factory=lambda: [
        {"pct": 0.05, "sell_portion": 0.40, "label": "T1"},
        {"pct": 0.10, "sell_portion": 0.30, "label": "T2"},
        {"pct": 0.18, "sell_portion": 1.00, "label": "T3"},
    ])

    # حد الخسارة
    initial_stop_pct: float = 0.05  # 5%
    trailing_stop_after_t1: bool = True

    # --- مدة الاحتفاظ ---
    max_holding_days: int = 10  # أسبوعين كحد أقصى

    # نسبة المخاطرة/المكافأة الدنيا
    min_rr_ratio: float = 2.0


# ===========================================================
# نسخ جاهزة للاستخدام
# ===========================================================
LONG_TERM = LongTermStrategy()
SHORT_TERM = ShortTermStrategy()
