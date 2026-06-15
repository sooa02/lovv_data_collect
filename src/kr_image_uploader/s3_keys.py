"""S3 key builders for KR city attraction images."""

from __future__ import annotations

import re

DEFAULT_PREFIX = "images/KR"


def safe_name(value: str) -> str:
    """Strip characters that are unsafe in an S3 object key segment."""
    normalized = (value or "").strip().replace(" ", "_")
    normalized = re.sub(r"[^A-Za-z0-9_\-]", "", normalized)
    return normalized or "UNKNOWN"


def build_image_key(
    city_name_en: str,
    file_base: str,
    suffix: str,
    ext: str,
    prefix: str = DEFAULT_PREFIX,
) -> str:
    """Build ``<prefix>/<City>/<Name>_<suffix>.<ext>``.

    Example: ``images/KR/Cheorwon/Goseokjeong_1.jpg``.
    """
    city = safe_name(city_name_en)
    base = safe_name(file_base)
    clean_ext = (ext or "").lower().lstrip(".") or "jpg"
    return f"{prefix}/{city}/{base}_{suffix}.{clean_ext}"
