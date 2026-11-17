"""Text helpers for English / Arabic (Gulf dialect) / mixed enquiries."""
import re

_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TASHKEEL = re.compile("[ً-ٰٟـ]")  # diacritics + tatweel
_ARABIC_RE = re.compile("[؀-ۿ]")
_LATIN_RE = re.compile("[A-Za-z]")


def prep(raw: str) -> str:
    """Length-preserving-ish clean-up used for extraction: ASCII digits, no diacritics."""
    s = raw.translate(_AR_DIGITS)
    s = _TASHKEEL.sub("", s)
    return s.replace("‏", "").replace("‎", "").replace("\r", "")


def norm(s: str) -> str:
    """Normalisation for matching only: lower-case, unify Arabic letter variants, collapse spaces."""
    s = prep(s).lower()
    s = (s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
          .replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي"))
    s = s.replace("گ", "ك").replace("چ", "ج").replace("پ", "ب").replace("ڤ", "ف")
    return re.sub(r"\s+", " ", s).strip()


def norm_lp(s: str) -> str:
    """Length-preserving normalisation (so match spans map back onto the prepared text)."""
    s = s.lower()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي"),
                 ("گ", "ك"), ("چ", "ج"), ("پ", "ب"), ("ڤ", "ف")):
        s = s.replace(a, b)
    return s


def is_arabic(s: str) -> bool:
    return bool(_ARABIC_RE.search(s))


def detect_language(text: str) -> str:
    ar = len(_ARABIC_RE.findall(text))
    la = len(_LATIN_RE.findall(text))
    total = ar + la
    if total == 0:
        return "en"
    ratio = ar / total
    if ratio >= 0.8:
        return "ar"
    if ratio <= 0.15:
        return "en"
    return "mixed"


NUMBER_WORDS = {
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "a couple": 2, "couple": 2,
    # Arabic (normalised forms, incl. Gulf dialect)
    "واحد": 1, "واحده": 1, "اثنين": 2, "اثنان": 2, "ثنتين": 2, "اثنتين": 2, "تنين": 2, "ثنين": 2,
    "ثلاث": 3, "ثلاثه": 3, "اربع": 4, "اربعه": 4, "خمس": 5, "خمسه": 5, "ست": 6, "سته": 6,
    "سبع": 7, "سبعه": 7, "ثمان": 8, "ثمانيه": 8, "ثماني": 8, "تسع": 9, "تسعه": 9, "عشر": 10, "عشره": 10,
    "نص": 0,
}
NUMBER_WORDS = {k: v for k, v in NUMBER_WORDS.items() if v > 0}


DUAL_WORDS = {"كنبتين", "غرفتين", "نافذتين", "شباكين", "مكيفين", "سجادتين", "وحدتين", "فيلتين", "شقتين", "سجادتين",
              "زوليتين", "حمامين", "ثنتين"}


def tokens_with_pos(text: str):
    """[(token, start, end)] over word-ish tokens (letters/digits/dots inside numbers)."""
    return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"[\w؀-ۿ]+(?:\.\d+)?", text)]


def token_number(tok: str):
    """Return int/float value if token is a number or number word, else None."""
    t = norm(tok)
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        v = float(t)
        return int(v) if v == int(v) else v
    if t in NUMBER_WORDS:
        return NUMBER_WORDS[t]
    if t in DUAL_WORDS:                                   # Arabic dual: كنبتين = two sofas
        return 2
    for k in (1, 2):                                      # attached prefixes: وواحد, لثلاث, ولثلاث, بخمس
        if len(t) > k + 1 and all(c in "ولبف" for c in t[:k]) and t[k:] in NUMBER_WORDS:
            return NUMBER_WORDS[t[k:]]
    return None
