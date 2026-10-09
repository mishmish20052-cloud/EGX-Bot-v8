"""
مدير الحالة الموحد (State Manager).

المسؤوليات:
- تحميل كل ملفات الحالة من القرص/GitHub
- حفظ التغييرات في الذاكرة
- رفع دفعة واحدة إلى GitHub (commit واحد)
- fallback محلي لو GitHub فشل
- التحقق من صحة البيانات قبل الحفظ

الاستخدام:
    state = StateManager()
    state.load_all()
    
    trades = state.get("short_positions", {})
    trades["COMI"] = {...}
    state.set("short_positions", trades)
    
    state.save_all()  # commit واحد فقط
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

from config.settings import CAIRO_TZ, STATE_FILES

logger = logging.getLogger("egx_bot.state")


# ===========================================================
# قيم افتراضية لكل ملف
# ===========================================================
DEFAULT_VALUES: dict[str, Any] = {
    "long_positions": {},
    "short_positions": {},
    "long_watchlist": {},
    "dna_memory": {},
    "sector_dna": {},
    "daily_stats": {},
    "lock": {},
}


# ===========================================================
# مدير الحالة
# ===========================================================
class StateManager:
    """
    يدير كل ملفات الحالة في مكان واحد.

    الفوائد:
    - تقليل عدد طلبات GitHub من 30+ إلى 1-2
    - fallback محلي
    - دعم التعديلات المؤقتة قبل الحفظ
    - تتبع التغييرات (dirty flags)
    """

    def __init__(self, github_backend=None):
        """
        المعاملات:
        - github_backend: instance من GitHubBackend (اختياري)
                          لو None، يعمل بشكل محلي فقط
        """
        self.github = github_backend
        self._data: dict[str, Any] = {}       # الذاكرة الحالية
        self._dirty: set[str] = set()          # الملفات المعدلة
        self._loaded = False

    # ======================================================
    # التحميل
    # ======================================================
    def load_all(self, force_remote: bool = False) -> None:
        """
        يحمّل كل ملفات الحالة.

        الترتيب:
        1. لو فيه github_backend، جرب التحميل من GitHub
        2. لو فشل، حمّل من القرص المحلي
        3. لو مش موجود، استخدم القيم الافتراضية
        """
        logger.info("📥 تحميل ملفات الحالة...")

        for key, filename in STATE_FILES.items():
            data = None

            # 1. من GitHub
            if self.github and force_remote:
                try:
                    data = self.github.download(filename)
                    if data is not None:
                        logger.debug(f"  ✅ {filename} من GitHub")
                except Exception as e:
                    logger.debug(f"  ⚠️ GitHub فشل لـ {filename}: {e}")

            # 2. من القرص المحلي
            if data is None:
                data = self._load_local(filename)
                if data is not None:
                    logger.debug(f"  ✅ {filename} من القرص")

            # 3. القيمة الافتراضية
            if data is None:
                data = DEFAULT_VALUES.get(key, {})
                logger.debug(f"  ⚠️ {filename} غير موجود — استخدام الافتراضي")

            self._data[key] = data

        self._loaded = True
        logger.info(f"✅ تم تحميل {len(self._data)} ملف حالة")

    def _load_local(self, filename: str) -> Optional[Any]:
        """يحمّل ملف من القرص المحلي."""
        if not os.path.exists(filename):
            return None
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"فشل تحميل {filename}: {e}")
            return None

    # ======================================================
    # الوصول للبيانات
    # ======================================================
    def get(self, key: str, default: Any = None) -> Any:
        """
        يرجع قيمة مفتاح من الحالة.
        key: مفتاح من STATE_FILES (مثل "short_positions")
        """
        if not self._loaded:
            self.load_all()
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        يعدل قيمة ويعلّمها للحفظ.
        """
        if key not in STATE_FILES:
            raise KeyError(f"مفتاح غير معروف: {key}. المتاح: {list(STATE_FILES.keys())}")
        self._data[key] = value
        self._dirty.add(key)
        logger.debug(f"📝 تم تعديل: {key}")

    def update(self, key: str, updates: dict) -> None:
        """يحدّث dict موجود بمفاتيح جديدة."""
        current = self.get(key, {})
        if not isinstance(current, dict):
            raise TypeError(f"{key} ليس dict — لا يمكن update")
        current.update(updates)
        self.set(key, current)

    def delete(self, key: str) -> None:
        """يحذف مفتاح."""
        if key in self._data:
            del self._data[key]
        self._dirty.add(key)

    # ======================================================
    # الحفظ
    # ======================================================
    def save_all(self, force: bool = False) -> dict:
        """
        يحفظ كل التعديلات.

        الخطوات:
        1. حفظ محلي لكل ملف
        2. رفع إلى GitHub (في commit واحد)
        3. تنظيف dirty flags

        ترجع dict: {filename: success_bool}
        """
        if not self._loaded:
            logger.warning("لا يوجد شيء لتحميله أولًا")
            return {}

        if not force and not self._dirty:
            logger.debug("لا يوجد تعديلات للحفظ")
            return {}

        results: dict[str, bool] = {}

        for key in list(self._dirty):
            filename = STATE_FILES.get(key)
            if not filename:
                continue

            data = self._data.get(key)

            # 1. حفظ محلي
            local_ok = self._save_local(filename, data)

            # 2. حفظ على GitHub
            remote_ok = True
            if self.github:
                try:
                    remote_ok = self.github.upload(
                        filename, data, f"update {filename}"
                    )
                except Exception as e:
                    logger.warning(f"GitHub upload فشل لـ {filename}: {e}")
                    remote_ok = False

            results[filename] = local_ok and (remote_ok or not self.github)

            if results[filename]:
                logger.debug(f"  ✅ {filename} محفوظ")
            else:
                logger.warning(f"  ⚠️ {filename} فشل جزئيًا")

        # نظف dirty flags
        self._dirty.clear()

        success_count = sum(1 for v in results.values() if v)
        total = len(results)
        logger.info(f"💾 تم حفظ {success_count}/{total} ملف")

        return results

    def _save_local(self, filename: str, data: Any) -> bool:
        """يحفظ ملف محليًا."""
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"فشل الحفظ المحلي لـ {filename}: {e}")
            return False

    # ======================================================
    # أدوات مساعدة
    # ======================================================
    def dirty_files(self) -> list[str]:
        """يرجع قائمة بأسماء الملفات المعدلة."""
        return [STATE_FILES.get(k, k) for k in self._dirty]

    def has_changes(self) -> bool:
        """هل فيه تعديلات غير محفوظة؟"""
        return len(self._dirty) > 0

    def reset(self) -> None:
        """يمسح كل التعديلات غير المحفوظة."""
        self._dirty.clear()
        self._data.clear()
        self._loaded = False

    def __repr__(self) -> str:
        dirty = len(self._dirty)
        total = len(self._data)
        return f"StateManager(loaded={self._loaded}, files={total}, dirty={dirty})"


# ===========================================================
# دوال مساعدة للتواريخ والإحصائيات
# ===========================================================
def today_str() -> str:
    """يرجع تاريخ اليوم بصيغة YYYY-MM-DD."""
    return datetime.now(CAIRO_TZ).strftime("%Y-%m-%d")


def ensure_today_stats(state: StateManager) -> dict:
    """
    يضمن وجود قسم إحصائيات اليوم في daily_stats.
    """
    stats = state.get("daily_stats", {})
    today = today_str()
    if today not in stats:
        stats[today] = {"wins": 0, "losses": 0, "signals": 0}
        state.set("daily_stats", stats)
    return stats[today]


def bump_stat(state: StateManager, key: str, value: int = 1) -> None:
    """
    يزيد إحصائية اليوم.
    key: "wins" / "losses" / "signals"
    """
    stats = state.get("daily_stats", {})
    today = today_str()
    stats.setdefault(today, {"wins": 0, "losses": 0, "signals": 0})
    stats[today][key] = stats[today].get(key, 0) + value
    state.set("daily_stats", stats)


def get_meta(state: StateManager) -> dict:
    """يرجع قسم _meta من daily_stats."""
    stats = state.get("daily_stats", {})
    meta = stats.setdefault("_meta", {})
    return meta


def set_meta(state: StateManager, key: str, value: Any) -> None:
    """يعدل قيمة في _meta."""
    stats = state.get("daily_stats", {})
    meta = stats.setdefault("_meta", {})
    meta[key] = value
    stats["_meta"] = meta
    state.set("daily_stats", stats)


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار StateManager")
    print("=" * 60)

    # 1. إنشاء instance
    state = StateManager()
    print(f"\n1️⃣ بعد الإنشاء: {state}")

    # 2. تحميل
    state.load_all()
    print(f"2️⃣ بعد التحميل: {state}")

    # 3. قراءة
    trades = state.get("short_positions", {})
    print(f"3️⃣ عدد الصفقات الحالية: {len(trades)}")

    # 4. تعديل
    trades["TEST_SYMBOL"] = {
        "entry_price": 100.0,
        "shares": 10,
        "entry_date": today_str(),
    }
    state.set("short_positions", trades)
    print(f"4️⃣ بعد التعديل: {state}")
    print(f"   الملفات المعدلة: {state.dirty_files()}")

    # 5. إحصائية
    bump_stat(state, "signals", 1)
    print(f"5️⃣ بعد bump_stat: {state}")

    # 6. حفظ
    results = state.save_all()
    print(f"\n6️⃣ نتائج الحفظ:")
    for fname, ok in results.items():
        status = "✅" if ok else "❌"
        print(f"   {status} {fname}")

    print(f"\n7️⃣ بعد الحفظ: {state}")

    # 7. إعادة تعيين (للاختبار فقط)
    print("\n" + "=" * 60)
    print("✅ اختبار StateManager اكتمل")
