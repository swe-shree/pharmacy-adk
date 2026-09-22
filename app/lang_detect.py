"""Zero-cost per-turn language labeling for logs only.

This does not decide what language the assistant speaks -- the live model
reads the user's actual audio and rule 1 in VOICE_PROMPT (app/router.py)
tells it to answer in whatever language that turn was spoken in. This
module exists only so `[TURN ...]` log lines can carry a `language=`/
`response_language=` field without an extra LLM call just to label a log
line.
"""

import re

# (label, (unicode block low, unicode block high))
_SCRIPT_RANGES: tuple[tuple[str, tuple[int, int]], ...] = (
    ("ta", (0x0B80, 0x0BFF)),  # Tamil
    ("hi", (0x0900, 0x097F)),  # Devanagari (Hindi, Marathi, ...)
    ("te", (0x0C00, 0x0C7F)),  # Telugu
    ("kn", (0x0C80, 0x0CFF)),  # Kannada
    ("ml", (0x0D00, 0x0D7F)),  # Malayalam
    ("bn", (0x0980, 0x09FF)),  # Bengali
    ("gu", (0x0A80, 0x0AFF)),  # Gujarati
    ("pa", (0x0A00, 0x0A7F)),  # Gurmukhi (Punjabi)
    ("ur", (0x0600, 0x06FF)),  # Arabic script (Urdu/Arabic)
    ("zh", (0x4E00, 0x9FFF)),  # CJK
    ("ja", (0x3040, 0x30FF)),  # Hiragana/Katakana
    ("ko", (0xAC00, 0xD7A3)),  # Hangul
    ("ru", (0x0400, 0x04FF)),  # Cyrillic
)

# Romanized Tamil (Tanglish) is written entirely in Latin letters, so no
# amount of Unicode-script counting can ever tell it apart from English --
# both use the exact same characters. This is a small, non-exhaustive set
# of common romanized-Tamil function words (not medicine/product names --
# generic grammar words) used only to flag that case for logging; it is
# never used to alter what the live model actually says.
_TANGLISH_MARKERS = frozenset({
    "enakku", "irukku", "irukka", "iruku", "venum", "vaenum", "pannu",
    "panra", "panren", "epdi", "eppadi", "irundha", "vanthu", "sollu",
    "solra", "nalla", "seri", "illa", "illai", "enna", "eppo", "yaru",
    "vera", "unga", "ungal", "naan", "neenga", "romba", "konjam", "da",
    "machi", "anna", "akka", "thalaivali", "seiyanum", "pannunga",
    "irukkanga", "aayiduchu", "aayiduchi",
})


def detect_script_language(text: str) -> str:
    """Best-effort language label for a transcript, for logging only.

    Counts characters by Unicode script block and returns the most common
    one. Latin-script text with no other script characters is checked for
    common romanized-Tamil (Tanglish) words and labeled "ta-en" if found,
    else "en" (English or another Latin-script language); text with no
    letters at all is "unknown".
    """

    if not text:
        return "unknown"

    counts: dict[str, int] = {}

    for char in text:
        code = ord(char)
        for label, (low, high) in _SCRIPT_RANGES:
            if low <= code <= high:
                counts[label] = counts.get(label, 0) + 1
                break

    if counts:
        return max(counts, key=counts.get)

    words = set(re.findall(r"[a-zA-Z]+", text.lower()))

    if words & _TANGLISH_MARKERS:
        return "ta-en"

    if words:
        return "en"

    return "unknown"


def response_language_for(detected_language: str) -> str:
    """Map a detected label to the language the spoken response should
    follow. Tanglish input should get a natural Tamil/Tanglish response,
    not English, even though its own script-based label isn't "ta"."""

    if detected_language == "ta-en":
        return "ta"

    return detected_language
