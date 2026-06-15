"""Extract image download targets from a raw VisitKorea city payload."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .romanize import romanize

# Image fields, in order, mapped to the filename suffix they receive.
_IMAGE_FIELDS = (("1", "firstimage"), ("2", "firstimage2"))


@dataclass(frozen=True)
class ImageTarget:
    """A single image to download and upload."""

    name: str          # romanized, collision-safe filename base
    suffix: str        # "1" or "2"
    url: str           # source image URL
    content_id: str    # VisitKorea contentid (for traceability)
    title: str         # original Korean title


def collect_image_targets(payload: dict[str, Any]) -> list[ImageTarget]:
    """Return every non-empty firstimage / firstimage2 in ``payload``.

    Attractions and festivals are both scanned. Filenames are romanized from the
    title; duplicates within a city are disambiguated by appending the contentid.
    """
    targets: list[ImageTarget] = []
    used: set[str] = set()

    for key in ("attractions", "festivals"):
        group = payload.get(key)
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            content_id = str(item.get("contentid", "")).strip()
            title = str(item.get("title", ""))
            base = romanize(title) or content_id or "item"
            if base in used:
                base = f"{base}_{content_id}"
            used.add(base)

            for suffix, field in _IMAGE_FIELDS:
                url = str(item.get(field) or "").strip()
                if url:
                    targets.append(
                        ImageTarget(
                            name=base,
                            suffix=suffix,
                            url=url,
                            content_id=content_id,
                            title=title,
                        )
                    )
    return targets
