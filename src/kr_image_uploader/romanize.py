"""Korean -> Latin romanization (Revised Romanization, syllable based).

Used to turn an attraction title such as ``고석정`` into an ASCII filename slug
``Goseokjeong``. The conversion is syllable based and intentionally simple; it
does not implement every assimilation rule, but it produces stable, unique,
ASCII-only names suitable for S3 object keys.
"""

from __future__ import annotations

# Initial consonants (choseong), 19.
_CHO = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s",
        "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
# Vowels (jungseong), 21.
_JUNG = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa",
         "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
# Final consonants (jongseong), 28 (index 0 = none).
_JONG = ["", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l",
         "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t"]

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3
_JONG_RIEUL = 8       # final ㄹ
_CHO_SILENT = 11      # initial ㅇ (no sound)

import re

_PAREN = re.compile(r"\([^)]*\)")


def romanize(title: str) -> str:
    """Romanize ``title`` into a PascalCase ASCII slug.

    Parenthetical qualifiers are dropped. Latin letters and digits already in
    the title are kept as-is. Returns an empty string if nothing usable remains.
    """
    text = _PAREN.sub("", title or "")
    chars = list(text)
    words: list[str] = []
    cur = ""

    for i, ch in enumerate(chars):
        code = ord(ch)
        if _HANGUL_BASE <= code <= _HANGUL_LAST:
            offset = code - _HANGUL_BASE
            cho = offset // (21 * 28)
            jung = (offset % (21 * 28)) // 28
            jong = offset % 28
            final = _JONG[jong]
            # liaison: final ㄹ before a silent initial (ㅇ + vowel) -> "r"
            if jong == _JONG_RIEUL and i + 1 < len(chars):
                nxt = ord(chars[i + 1])
                if _HANGUL_BASE <= nxt <= _HANGUL_LAST:
                    if (nxt - _HANGUL_BASE) // (21 * 28) == _CHO_SILENT:
                        final = "r"
            cur += _CHO[cho] + _JUNG[jung] + final
        elif ch.isascii() and ch.isalnum():
            cur += ch
        else:
            if cur:
                words.append(cur)
                cur = ""
    if cur:
        words.append(cur)

    return "".join(word[:1].upper() + word[1:] for word in words if word)
