"""Conservative album metadata normalization shared by the Beets plugin."""

from __future__ import annotations

import re
import unicodedata


_TRAILING_QUALIFIER = re.compile(
    r"^(?P<title>.+?)\s*[\(\[（［](?P<qualifier>[^\(\)\[\]（）［］]+)[\)\]）］]\s*$"
)

_QUALIFIER_COMPONENTS = (
    # Audio encodings and storefront quality labels.
    re.compile(
        r"\b(?:flac|alac|wav|wave|aiff?|pcm|mqa|lossless|web)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:hi[\s-]*res(?:olution)?|high[\s-]*resolution)(?:[\s-]*audio)?\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:ハイレゾ(?:音源)?|高解像度(?:音源)?)", re.IGNORECASE),
    re.compile(r"\bdsd\s*(?:64|128|256|512|1024)?\b", re.IGNORECASE),
    # Sample rates, bit depths, and common shorthand such as 24/96.
    re.compile(r"\b\d{2,3}(?:\.\d+)?\s*k\s*hz\b", re.IGNORECASE),
    re.compile(r"\b\d{4,6}\s*hz\b", re.IGNORECASE),
    re.compile(r"\b(?:8|16|20|24|32|64)\s*[- ]?\s*bit\b", re.IGNORECASE),
    re.compile(
        r"\b(?:8|16|20|24|32|64)\s*(?:/|x|×)\s*"
        r"(?:44(?:\.1)?|48|88(?:\.2)?|96|176(?:\.4)?|192|352(?:\.8)?|384)\b",
        re.IGNORECASE,
    ),
    # Retail/distribution qualifiers. Musical variants such as live,
    # acoustic, remix, and remaster are intentionally not included.
    re.compile(
        r"\b(?:standard|regular|limited|special|deluxe|digital|download|"
        r"streaming|international|japanese|japan|domestic|bonus(?:\s+track)?|"
        r"(?:\d+(?:st|nd|rd|th)\s+)?anniversary)\s+"
        r"(?:edition|version|release|press(?:ing)?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:digital\s+media|digital|download|cd|sacd|vinyl|lp)\b", re.IGNORECASE),
    re.compile(
        r"(?:通常盤|初回(?:限定)?(?:盤|プレス)|完全生産限定盤|期間生産限定盤|"
        r"数量限定盤|限定盤|特装盤|豪華盤|デラックス(?:盤|エディション)|"
        r"配信限定(?:盤)?|国内盤|輸入盤|日本盤|標準盤)",
        re.IGNORECASE,
    ),
)

_QUALIFIER_SEPARATORS = re.compile(r"[\s/\\&+,;:|・·._-]+")


def is_non_title_qualifier(value: str | None) -> bool:
    """Return whether a value consists only of technical/retail metadata."""

    if not value:
        return False

    candidate = unicodedata.normalize("NFKC", value).strip().casefold()
    if not candidate:
        return False

    for component in _QUALIFIER_COMPONENTS:
        candidate = component.sub("", candidate)

    return not _QUALIFIER_SEPARATORS.sub("", candidate)


def normalize_album_title(value: str | None) -> str:
    """Strip recognized trailing qualifiers without changing artistic text."""

    title = value or ""
    while match := _TRAILING_QUALIFIER.match(title):
        if not is_non_title_qualifier(match.group("qualifier")):
            break
        title = match.group("title").rstrip()
    return title
