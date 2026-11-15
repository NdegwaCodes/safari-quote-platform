from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).parent / "fonts"

FACES: tuple[tuple[str, str, str, str], ...] = (
    ("Cormorant Garamond", "normal", "400 700", "cormorant-garamond-normal.woff2"),
    ("Cormorant Garamond", "italic", "400 700", "cormorant-garamond-italic.woff2"),
    ("Libre Franklin", "normal", "300 700", "libre-franklin-normal.woff2"),
)

FALLBACKS = {
    "Cormorant Garamond": "'EB Garamond', Garamond, 'Times New Roman', serif",
    "Libre Franklin": "'Helvetica Neue', Helvetica, Arial, sans-serif",
}


def font_stack(family: str) -> str:
    return f"'{family}', {FALLBACKS[family]}"


@lru_cache(maxsize=1)
def face_css() -> str:
    rules: list[str] = []
    for family, style, weight, filename in FACES:
        path = FONT_DIR / filename
        try:
            payload = base64.b64encode(path.read_bytes()).decode("ascii")
        except OSError:
            continue
        rules.append(
            "@font-face{"
            f"font-family:'{family}';"
            f"font-style:{style};"
            f"font-weight:{weight};"
            "font-display:block;"
            f"src:url(data:font/woff2;base64,{payload}) format('woff2');"
            "}"
        )
    return "".join(rules)


def missing_faces() -> list[str]:
    return [
        filename
        for _family, _style, _weight, filename in FACES
        if not (FONT_DIR / filename).is_file()
    ]
