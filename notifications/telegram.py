"""
إرسال رسائل Telegram.

المزايا:
- fallback تلقائي لو Markdown فشل
- retry لو الشبكة فشلت
- تسجيل كامل
- دعم الرسائل الطويلة (تقسيم تلقائي)
"""

import logging
import time
from typing import Optional

import requests

from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger("egx_bot.telegram")


# ===========================================================
# إعدادات
# ===========================================================
API_BASE = "https://api.telegram.org"
MAX_RETRIES = 3
BASE_DELAY = 1  # ثانية
MAX_MESSAGE_LENGTH = 4000  # أقل من حد تليجرام (4096)


# ===========================================================
# الحالة العامة
# ===========================================================
_enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


# ===========================================================
# الدالة الرئيسية
# ===========================================================
def send(
    message: str,
    parse_mode: str = "Markdown",
    silent: bool = False,
) -> bool:
    """
    إرسال رسالة على تليجرام.

    المعاملات:
    - message: نص الرسالة
    - parse_mode: "Markdown" / "HTML" / None
    - silent: لو True، الرسالة توصل بدون صوت

    ترجع: True لو نجحت، False لو فشلت.
    """
    if not _enabled:
        logger.debug("Telegram معطّل — الرسالة لم تُرسل")
        return False

    if not message or not message.strip():
        logger.warning("رسالة فارغة — تجاهل")
        return False

    # لو الرسالة طويلة، قسّمها
    if len(message) > MAX_MESSAGE_LENGTH:
        return _send_long_message(message, parse_mode, silent)

    return _send_single(message, parse_mode, silent)


def _send_single(
    message: str,
    parse_mode: Optional[str],
    silent: bool,
) -> bool:
    """يرسل رسالة واحدة مع retry و fallback."""
    url = f"{API_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    for attempt in range(MAX_RETRIES):
        try:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_notification": silent,
            }
            if parse_mode:
                payload["parse_mode"] = parse_mode

            r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)

            # نجاح
            if r.status_code == 200:
                logger.debug(f"✅ TG نجح ({len(message)} حرف)")
                return True

            # خطأ في Markdown — جرب بدون parse_mode
            if r.status_code == 400 and parse_mode:
                logger.debug("TG رفض Markdown — جرب بدون formatting")
                payload.pop("parse_mode", None)
                r2 = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
                if r2.status_code == 200:
                    logger.info("✅ TG نجح (بدون Markdown)")
                    return True
                logger.error(f"TG فشل حتى بدون Markdown: {r2.status_code}")
                return False

            # rate limit
            if r.status_code == 429:
                wait = BASE_DELAY * (2 ** attempt) * 2
                logger.warning(f"⏳ TG rate limit — انتظار {wait}s")
                time.sleep(wait)
                continue

            # أخطاء أخرى
            logger.error(f"TG فشل: HTTP {r.status_code} — {r.text[:200]}")
            return False

        except requests.exceptions.Timeout:
            logger.warning(f"⏱️ TG timeout (محاولة {attempt+1})")
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_DELAY * (2 ** attempt))
        except Exception as e:
            logger.error(f"TG exception: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(BASE_DELAY * (2 ** attempt))

    return False


def _send_long_message(
    message: str,
    parse_mode: Optional[str],
    silent: bool,
) -> bool:
    """يقسّم رسالة طويلة لأجزاء ويرسلها."""
    chunks = _split_message(message, MAX_MESSAGE_LENGTH)
    logger.info(f"📨 رسالة طويلة — تقسيمها لـ {len(chunks)} أجزاء")

    success = True
    for i, chunk in enumerate(chunks):
        header = f"[{i+1}/{len(chunks)}]\n" if len(chunks) > 1 else ""
        ok = _send_single(header + chunk, parse_mode, silent)
        if not ok:
            success = False
        if i < len(chunks) - 1:
            time.sleep(0.5)  # تجنب rate limit

    return success


def _split_message(message: str, max_len: int) -> list[str]:
    """يقسّم الرسالة على حدود الأسطر."""
    lines = message.split("\n")
    chunks: list[str] = []
    current = ""

    for line in lines:
        # لو السطر لوحده أطول من max_len، قطعه
        if len(line) > max_len:
            if current:
                chunks.append(current)
                current = ""
            while len(line) > max_len:
                chunks.append(line[:max_len])
                line = line[max_len:]
            current = line
            continue

        # لو إضافة السطر هتعدي الحد
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line

    if current:
        chunks.append(current)

    return chunks


# ===========================================================
# دوال مساعدة
# ===========================================================
def is_enabled() -> bool:
    """هل تليجرام مفعّل؟"""
    return _enabled


def test_connection() -> bool:
    """
    يختبر الاتصال بتليجرام.
    يرسل رسالة اختبار.
    """
    if not _enabled:
        logger.error("Telegram معطّل — لا يمكن الاختبار")
        return False

    test_msg = "🧪 *رسالة اختبار*\n\n✅ الاتصال بتليجرام شغال"
    return send(test_msg)


def send_error(error_text: str) -> bool:
    """يرسل رسالة خطأ بتنسيق موحد."""
    msg = f"❌ *خطأ في البوت*\n\n`{error_text[:500]}`"
    return send(msg)


def send_info(info_text: str) -> bool:
    """يرسل رسالة معلومات."""
    return send(f"ℹ️ {info_text}")


def send_success(success_text: str) -> bool:
    """يرسل رسالة نجاح."""
    return send(f"✅ {success_text}")


def send_warning(warning_text: str) -> bool:
    """يرسل رسالة تحذير."""
    return send(f"⚠️ {warning_text}")


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار Telegram")
    print("=" * 60)

    print(f"\n1️⃣ الحالة: {'✅ مفعّل' if is_enabled() else '❌ معطّل'}")

    if not is_enabled():
        print("\n⚠️ تأكد من TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID")
        exit(0)

    # 2. اختبار رسالة بسيطة
    print("\n2️⃣ إرسال رسالة اختبار...")
    ok = send("🧪 *اختبار تليجرام*\n\n✅ الرسالة وصلت")
    print(f"   {'✅ نجح' if ok else '❌ فشل'}")

    # 3. اختبار رسالة طويلة
    print("\n3️⃣ اختبار رسالة طويلة...")
    long_msg = "📋 تقرير طويل\n\n" + "\n".join(
        [f"سطر رقم {i}: هذا سطر تجريبي للاختبار" for i in range(1, 150)]
    )
    ok = send(long_msg)
    print(f"   {'✅ نجح' if ok else '❌ فشل'}")

    # 4. اختبار رسالة بدون Markdown صحيح
    print("\n4️⃣ اختبار رسالة فيها رموز Markdown غير مزدوجة...")
    ok = send("هذا نص فيه *نجمة واحدة فقط")
    print(f"   {'✅ نجح (fallback)' if ok else '❌ فشل'}")

    print("\n" + "=" * 60)
    print("✅ اختبار Telegram اكتمل")
