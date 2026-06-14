"""ATS compliance audit for cv.pdf — scoring, keyword match, and issue detection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pypdf import PdfReader

BASE_DIR = Path(__file__).parent
DEFAULT_CV = BASE_DIR / "assets" / "cv" / "cv.pdf"

REQUIRED_SECTIONS = [
    "professional summary",
    "core skills",
    "professional experience",
    "education",
]

REQUIRED_EMPLOYERS = [
    "farasan",
    "manate",
    "mahra",
    "amjad",
    "abdul karim",
]

RANK_LABELS = [
    (90, "ممتاز", "success"),
    (75, "جيد جداً", "success"),
    (60, "مقبول", "warning"),
    (40, "ضعيف", "error"),
    (0, "غير متوافق", "error"),
]


def load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(BASE_DIR / path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _extract_pdf_text(path: Path) -> tuple[str, int, list[str]]:
    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages), len(reader.pages), pages


def _count_images(path: Path) -> int:
    return path.read_bytes().count(b"/Subtype /Image")


def _keyword_hits(text: str, keywords: list[str]) -> dict[str, bool]:
    lower = text.lower()
    return {kw: kw.lower() in lower for kw in keywords}


def _rank_label(score: int) -> tuple[str, str]:
    for threshold, label, level in RANK_LABELS:
        if score >= threshold:
            return label, level
    return "غير متوافق", "error"


def audit_cv(
    cv_path: Optional[Path] = None,
    config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    config = config or load_config()
    path = Path(cv_path) if cv_path else DEFAULT_CV
    keywords = config.get("cv_ats_keywords", [])
    profile = config["profile"]

    if not path.exists():
        return {
            "ok": False,
            "score": 0,
            "rank": "غير متوافق",
            "rank_level": "error",
            "issues": ["cv.pdf غير موجود — ارفع ملف PDF من الإعدادات"],
            "passed": [],
            "keywords": {},
            "keyword_score": 0,
            "text_chars": 0,
            "pages": 0,
            "size_kb": 0,
            "images": 0,
            "path": str(path),
        }

    size_kb = path.stat().st_size // 1024
    images = _count_images(path)
    text, pages, _ = _extract_pdf_text(path)
    text_chars = len(text.strip())
    text_lower = text.lower()

    issues: list[str] = []
    passed: list[str] = []
    score = 0

    # Text extractability
    if text_chars >= 500:
        score += 10
        passed.append(f"نص قابل للاستخراج ({text_chars:,} حرف)")
    else:
        issues.append("النص غير قابل للاستخراج — قد يكون PDF ممسوحاً ضوئياً")

    if text_chars >= 2000:
        score += 5
        passed.append("محتوى نصي غني لأنظمة ATS")

    # File size
    if size_kb <= 2048:
        score += 3
        passed.append(f"حجم الملف مناسب ({size_kb} KB)")
    else:
        issues.append(f"حجم الملف كبير ({size_kb} KB) — الحد الموصى به 2 MB")

    if size_kb <= 600:
        score += 5
        passed.append("حجم خفيف — بدون مرفقات ثقيلة")
    elif size_kb > 900:
        issues.append(f"حجم {size_kb} KB مرتفع — غالباً صور أو شهادات مدمجة")

    # Images / graphics
    if images == 0:
        score += 8
        passed.append("بدون صور مدمجة — ممتاز لـ ATS")
    elif images <= 2:
        score += 4
        issues.append(f"{images} صورة مدمجة — قد تشتت أنظمة ATS")
    else:
        issues.append(f"{images} صور مدمجة — يُفضّل CV نصي بدون شهادات")

    if "%" in text or "percent" in text_lower:
        issues.append("نسب مهارات (مثل 97%) — غير مدعومة في ATS")
    else:
        score += 5
        passed.append("بدون نسب مهارات أو رسوم")

    # Contact & identity
    email = profile.get("sender_email", "")
    phone_digits = re.sub(r"\D", "", profile.get("phone", ""))
    if email.lower() in text_lower:
        score += 4
        passed.append("البريد الإلكتروني موجود في CV")
    else:
        issues.append(f"البريد {email} غير موجود في النص المستخرج")

    if phone_digits[-9:] in re.sub(r"\D", "", text):
        score += 4
        passed.append("رقم الجوال موجود في CV")
    else:
        issues.append("رقم الجوال غير واضح في النص المستخرج")

    name_parts = profile["full_name"].lower().split()
    if all(part in text_lower for part in name_parts[:2]):
        score += 3
        passed.append("الاسم الكامل موجود")
    else:
        issues.append("الاسم الكامل غير واضح في النص المستخرج")

    title = profile.get("title", "General Land Surveyor").lower()
    if title in text_lower or "general surveyor" in text_lower or "مساح" in text:
        score += 4
        passed.append("المسمى الوظيفي موجود")
    else:
        issues.append('المسمى "General Land Surveyor / مساح عام" غير واضح')

    # English sections
    section_hits = sum(1 for s in REQUIRED_SECTIONS if s in text_lower)
    score += min(section_hits * 4, 16)
    if section_hits >= 3:
        passed.append(f"أقسام إنجليزية قياسية ({section_hits}/4)")
    else:
        issues.append("أقسام ATS القياسية ناقصة (Summary, Skills, Experience, Education)")

    # Employers
    employer_hits = sum(1 for e in REQUIRED_EMPLOYERS if e in text_lower)
    score += min(employer_hits * 2, 10)
    if employer_hits >= 4:
        passed.append(f"خبرات العمل الخمسة ظاهرة ({employer_hits}/5)")
    elif employer_hits >= 2:
        issues.append(f"بعض جهات العمل ناقصة ({employer_hits}/5)")
    else:
        issues.append("خبرات العمل غير مكتملة في النص المستخرج")

    # Keywords
    hits = _keyword_hits(text, keywords)
    hit_count = sum(hits.values())
    keyword_pct = int((hit_count / len(keywords)) * 100) if keywords else 0
    score += min(int((hit_count / max(len(keywords), 1)) * 25), 25)
    if hit_count >= len(keywords) * 0.8:
        passed.append(f"كلمات مفتاحية {hit_count}/{len(keywords)} ({keyword_pct}%)")
    elif hit_count >= len(keywords) * 0.5:
        issues.append(f"كلمات مفتاحية متوسطة {hit_count}/{len(keywords)} — أضف المزيد")
    else:
        issues.append(f"كلمات مفتاحية ضعيفة {hit_count}/{len(keywords)} — يؤثر على الترتيب")

    score = min(score, 100)
    rank, rank_level = _rank_label(score)

    return {
        "ok": score >= 60,
        "score": score,
        "rank": rank,
        "rank_level": rank_level,
        "issues": issues,
        "passed": passed,
        "keywords": hits,
        "keyword_hits": hit_count,
        "keyword_total": len(keywords),
        "keyword_pct": keyword_pct,
        "text_chars": text_chars,
        "pages": pages,
        "size_kb": size_kb,
        "images": images,
        "path": str(path),
    }
