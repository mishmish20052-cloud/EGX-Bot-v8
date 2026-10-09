"""
Backend للتعامل مع GitHub API.

المسؤوليات:
- تحميل ملفات من GitHub (contents API)
- رفع ملفات إلى GitHub (مع sha)
- حذف ملفات
- معالجة rate limits والـ retry

يستخدم داخل StateManager لتخزين دائم بين تشغيلات GitHub Actions.
"""

import base64
import json
import logging
import time
from typing import Any, Optional

import requests

from config.settings import (
    GITHUB_TOKEN,
    GITHUB_REPO,
    REQUEST_TIMEOUT,
)

logger = logging.getLogger("egx_bot.github")


# ===========================================================
# إعدادات
# ===========================================================
MAX_RETRIES = 3
BASE_DELAY = 1  # ثانية
API_BASE = "https://api.github.com"


# ===========================================================
# Backend
# ===========================================================
class GitHubBackend:
    """
    يتعامل مع GitHub Contents API لحفظ وتحميل ملفات الحالة.

    الاستخدام:
        gh = GitHubBackend()
        data = gh.download("short_positions.json")
        gh.upload("short_positions.json", {"COMI": {...}}, "update trades")
    """

    def __init__(
        self,
        token: Optional[str] = None,
        repo: Optional[str] = None,
        branch: str = "main",
    ):
        """
        المعاملات:
        - token: GitHub Personal Access Token (لو None، يقرأ من الإعدادات)
        - repo: "owner/repo" (لو None، يقرأ من الإعدادات)
        - branch: الفرع (افتراضي: main)
        """
        self.token = token or GITHUB_TOKEN
        self.repo = repo or GITHUB_REPO
        self.branch = branch

        self.enabled = bool(self.token and self.repo)

        if not self.enabled:
            logger.warning(
                "⚠️ GitHub backend معطّل — "
                "GITHUB_TOKEN أو GITHUB_REPO غير مضبوط"
            )

        self._headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        } if self.enabled else {}

    # ======================================================
    # تحميل ملف
    # ======================================================
    def download(self, filename: str) -> Optional[Any]:
        """
        يحمّل ملف JSON من GitHub.

        ترجع:
        - البيانات المُحوَّلة لـ Python object
        - None لو الملف غير موجود أو فشل
        """
        if not self.enabled:
            return None

        url = f"{API_BASE}/repos/{self.repo}/contents/{filename}"
        params = {"ref": self.branch}

        for attempt in range(MAX_RETRIES):
            try:
                r = requests.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT,
                )

                if r.status_code == 404:
                    logger.debug(f"📭 {filename} غير موجود على GitHub")
                    return None

                if r.status_code == 200:
                    content_b64 = r.json().get("content", "")
                    decoded = base64.b64decode(content_b64).decode("utf-8")
                    return json.loads(decoded)

                if r.status_code in (403, 429):
                    # rate limit
                    wait = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"⏳ GitHub rate limit — انتظار {wait}s"
                    )
                    time.sleep(wait)
                    continue

                logger.warning(
                    f"⚠️ GitHub download {filename}: "
                    f"HTTP {r.status_code}"
                )
                return None

            except requests.exceptions.Timeout:
                logger.debug(f"⏱️ timeout لـ {filename} (محاولة {attempt+1})")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BASE_DELAY * (2 ** attempt))
            except Exception as e:
                logger.warning(f"GitHub download exception: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BASE_DELAY * (2 ** attempt))

        return None

    # ======================================================
    # رفع ملف
    # ======================================================
    def upload(
        self,
        filename: str,
        data: Any,
        message: str = "update",
    ) -> bool:
        """
        يرفع/يحدّث ملف JSON على GitHub.

        ترجع: True لو نجح، False لو فشل.
        """
        if not self.enabled:
            return False

        url = f"{API_BASE}/repos/{self.repo}/contents/{filename}"

        # 1. جلب sha الحالي (لو الملف موجود)
        sha = self._get_file_sha(filename)

        # 2. تجهيز المحتوى
        try:
            content_str = json.dumps(data, ensure_ascii=False, indent=2)
            content_b64 = base64.b64encode(content_str.encode("utf-8")).decode("ascii")
        except Exception as e:
            logger.error(f"فشل تجهيز محتوى {filename}: {e}")
            return False

        # 3. بناء payload
        payload = {
            "message": message,
            "content": content_b64,
            "branch": self.branch,
        }
        if sha:
            payload["sha"] = sha

        # 4. رفع مع retry
        for attempt in range(MAX_RETRIES):
            try:
                r = requests.put(
                    url,
                    headers=self._headers,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )

                if r.status_code in (200, 201):
                    logger.debug(f"✅ GitHub upload {filename}: نجح")
                    return True

                if r.status_code == 409:
                    # conflict في sha — جرب تحديث sha
                    logger.debug(f"⚠️ conflict في {filename} — تحديث sha")
                    sha = self._get_file_sha(filename)
                    if sha:
                        payload["sha"] = sha
                    time.sleep(BASE_DELAY)
                    continue

                if r.status_code in (403, 429):
                    wait = BASE_DELAY * (2 ** attempt)
                    logger.warning(f"⏳ rate limit — انتظار {wait}s")
                    time.sleep(wait)
                    continue

                logger.warning(
                    f"⚠️ GitHub upload {filename}: HTTP {r.status_code} — "
                    f"{r.text[:200]}"
                )
                return False

            except requests.exceptions.Timeout:
                logger.debug(f"⏱️ timeout في upload {filename}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BASE_DELAY * (2 ** attempt))
            except Exception as e:
                logger.warning(f"GitHub upload exception: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BASE_DELAY * (2 ** attempt))

        return False

    # ======================================================
    # حذف ملف
    # ======================================================
    def delete(self, filename: str, message: str = "delete") -> bool:
        """
        يحذف ملف من GitHub.
        ترجع: True لو نجح.
        """
        if not self.enabled:
            return False

        sha = self._get_file_sha(filename)
        if not sha:
            logger.debug(f"📭 {filename} غير موجود — لا شيء للحذف")
            return True  # نعتبره نجاح

        url = f"{API_BASE}/repos/{self.repo}/contents/{filename}"

        try:
            r = requests.delete(
                url,
                headers=self._headers,
                json={
                    "message": message,
                    "sha": sha,
                    "branch": self.branch,
                },
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code in (200, 204):
                logger.debug(f"✅ GitHub delete {filename}")
                return True
            logger.warning(f"⚠️ GitHub delete {filename}: HTTP {r.status_code}")
            return False
        except Exception as e:
            logger.warning(f"GitHub delete exception: {e}")
            return False

    # ======================================================
    # أدوات مساعدة
    # ======================================================
    def _get_file_sha(self, filename: str) -> Optional[str]:
        """يرجع sha للملف الحالي على GitHub (لو موجود)."""
        if not self.enabled:
            return None

        url = f"{API_BASE}/repos/{self.repo}/contents/{filename}"
        try:
            r = requests.get(
                url,
                headers=self._headers,
                params={"ref": self.branch},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("sha")
        except Exception:
            pass
        return None

    def file_exists(self, filename: str) -> bool:
        """هل الملف موجود على GitHub؟"""
        return self._get_file_sha(filename) is not None

    def check_connection(self) -> bool:
        """
        يتحقق من الاتصال بـ GitHub.
        ترجع: True لو الاتصال شغال.
        """
        if not self.enabled:
            return False
        try:
            url = f"{API_BASE}/repos/{self.repo}"
            r = requests.get(url, headers=self._headers, timeout=10)
            return r.status_code == 200
        except Exception:
            return False

    def get_repo_info(self) -> Optional[dict]:
        """يرجع معلومات الريبو (للتشخيص)."""
        if not self.enabled:
            return None
        try:
            url = f"{API_BASE}/repos/{self.repo}"
            r = requests.get(url, headers=self._headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                return {
                    "full_name": data.get("full_name"),
                    "default_branch": data.get("default_branch"),
                    "private": data.get("private"),
                    "rate_limit_remaining": r.headers.get("X-RateLimit-Remaining"),
                }
        except Exception:
            pass
        return None


# ===========================================================
# اختبار سريع
# ===========================================================
if __name__ == "__main__":
    print("=" * 60)
    print("اختبار GitHub Backend")
    print("=" * 60)

    gh = GitHubBackend()

    if not gh.enabled:
        print("⚠️ GitHub backend معطّل — تأكد من GITHUB_TOKEN و GITHUB_REPO")
        exit(0)

    # 1. اختبار الاتصال
    print("\n1️⃣ اختبار الاتصال...")
    if gh.check_connection():
        print("   ✅ الاتصال شغال")
    else:
        print("   ❌ الاتصال فشل")
        exit(1)

    # 2. معلومات الريبو
    print("\n2️⃣ معلومات الريبو:")
    info = gh.get_repo_info()
    if info:
        for k, v in info.items():
            print(f"   {k}: {v}")

    # 3. اختبار التحميل
    print("\n3️⃣ اختبار التحميل...")
    data = gh.download("README.md")
    if data:
        print(f"   ✅ تم تحميل README.md ({len(str(data))} حرف)")
    else:
        print("   (README.md مش JSON، طبيعي يفشل — ده مجرد اختبار)")

    # 4. اختبار رفع
    print("\n4️⃣ اختبار الرفع...")
    test_data = {"test": True, "timestamp": "test"}
    ok = gh.upload("_test_github_backend.json", test_data, "test upload")
    if ok:
        print("   ✅ تم رفع ملف اختباري")
        # نظّف بعده
        gh.delete("_test_github_backend.json", "cleanup test")
        print("   ✅ تم حذف ملف الاختبار")
    else:
        print("   ❌ فشل الرفع")

    print("\n" + "=" * 60)
    print("✅ اختبار GitHub Backend اكتمل")
