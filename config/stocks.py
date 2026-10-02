"""
قائمة الأسهم المتوافقة مع الشريعة في البورصة المصرية،
مع تصنيف القطاعات وفلاتر الأولية.
"""

# ===========================================================
# قائمة الأسهم — {الرمز: (الاسم العربي, القطاع)}
# ===========================================================
SHARIA_STOCKS = {
    # البنوك الإسلامية
    "ADIB": ("مصرف أبوظبي الإسلامي", "FINANCIAL"),
    "SAUD": ("مصرف البركة", "FINANCIAL"),
    "FAIT": ("بنك فيصل الإسلامي", "FINANCIAL"),

    # الصناعة
    "EGAL": ("مصر للألومنيوم", "INDUSTRY"),
    "ATQA": ("الوطنية للصلب - عتاقة", "INDUSTRY"),
    "ORWE": ("النساجون الشرقيون", "INDUSTRY"),
    "MTIE": ("إم إم جروب", "INDUSTRY"),
    "ACGC": ("العربية لحليج الأقطان", "INDUSTRY"),

    # الطاقة والبتروكيماويات
    "AMOC": ("الإسكندرية للزيوت المعدنية", "ENERGY"),
    "EGAS": ("مصر للغاز", "ENERGY"),
    "SKPC": ("سيدبك", "CHEMICALS"),
    "ICFC": ("الدولية للأسمدة", "CHEMICALS"),

    # البناء والتشييد
    "ARCC": ("العربية للأسمنت", "CONSTRUCTION"),
    "MCQE": ("أسمنت قنا", "CONSTRUCTION"),
    "LCSW": ("ليسيكو مصر", "CONSTRUCTION"),
    "ORAS": ("أوراسكوم للإنشاءات", "CONSTRUCTION"),

    # الرعاية الصحية
    "ISPH": ("ابن سينا فارما", "HEALTHCARE"),
    "RMDA": ("رميدا", "HEALTHCARE"),

    # الأغذية والمشروبات
    "EFID": ("إيديتا", "FOOD"),
    "JUFO": ("جهينة", "FOOD"),
    "OLFI": ("عبور لاند", "FOOD"),
    "MPCO": ("المنصورة للدواجن", "FOOD"),
    "IFAP": ("الدولية للمحاصيل", "FOOD"),

    # العقارات
    "MASR": ("مدينة مصر", "REALESTATE"),
    "ORHD": ("أوراسكوم للتنمية", "REALESTATE"),
    "PHDC": ("بالم هيلز", "REALESTATE"),
    "OCDI": ("سوديك", "REALESTATE"),
    "TMGH": ("طلعت مصطفى", "REALESTATE"),

    # الخدمات والتقنية والاتصالات
    "CIRA": ("القاهرة للاستثمار", "SERVICES"),
    "EFIH": ("إي فاينانس", "TECH"),
    "RACC": ("رايا", "TECH"),
    "ETEL": ("المصرية للاتصالات", "TELECOM"),

    # النقل والخدمات اللوجستية
    "ETRS": ("مصر للنقل", "LOGISTICS"),
}

# ===========================================================
# قوائم مشتقة
# ===========================================================
ALL_SYMBOLS = list(SHARIA_STOCKS.keys())

# القطاعات الدفاعية (أقل تأثرًا بالانخفاضات)
DEFENSIVE_SECTORS = {"FOOD", "HEALTHCARE", "TELECOM"}

# سلة أسهم كبيرة/سائلة لتقدير حالة السوق عند غياب EGX30
MARKET_PROXY_BASKET = ["TMGH", "CIRA", "EFIH", "ETEL", "ORAS", "PHDC"]

# ===========================================================
# دوال مساعدة
# ===========================================================
def get_name(symbol: str) -> str:
    """يرجع الاسم العربي للسهم."""
    return SHARIA_STOCKS.get(symbol, (symbol, "OTHER"))[0]


def get_sector(symbol: str) -> str:
    """يرجع قطاع السهم."""
    return SHARIA_STOCKS.get(symbol, (symbol, "OTHER"))[1]


def filter_by_sector(sectors: set[str]) -> list[str]:
    """يرجع قائمة الأسهم التي تنتمي لقطاعات محددة."""
    return [s for s, (_, sec) in SHARIA_STOCKS.items() if sec in sectors]


def defensive_symbols() -> list[str]:
    """يرجع قائمة الأسهم الدفاعية."""
    return filter_by_sector(DEFENSIVE_SECTORS)


def all_sectors() -> set[str]:
    """يرجع كل القطاعات الفريدة."""
    return {sec for _, sec in SHARIA_STOCKS.values()}
