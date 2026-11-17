"""Price guard and prompt-injection signals.

Rule: the model must never produce a price. Anything that looks like a monetary amount, a price
statement or a discount in model-written text is removed and recorded. Real prices come only from the
user's catalogue or manual entry, and money is computed by quoteflow.money."""
import re
from .text import prep

_CUR = r"(?:bhd|b\.?d\.?|bd|kd|sar|sr|aed|usd|eur|gbp|dinars?|dirhams?|riyals?|fils|dollars?|\$|€|£|دينار|دنانير|دينارا|د\.ب|فلس|فلوس|ريال|درهم|دولار)"
_NUM = r"\d[\d,]*(?:\.\d+)?"
_PATTERNS = [
    re.compile(rf"(?i)\b{_NUM}\s*{_CUR}(?![a-z])"),                  # 25 bhd, 12.500 دينار
    re.compile(rf"(?i)(?<![a-z]){_CUR}\s*{_NUM}"),                   # BHD 25, $25
    re.compile(rf"(?i)\b(?:price|cost|charge|fee|total|rate|quote|سعر|السعر|بسعر|تكلفة|التكلفة|اجمالي|المجموع|رسوم)\b"
               rf"[\s:=\-]{{0,3}}(?:is|of|around|about|at|للـ|ب)?[\s:=\-]{{0,3}}\d{{1,7}}(?:[.,]\d+)?(?!\d)"),
    re.compile(r"(?<!\d)\d{1,6}\.\d{3}(?!\d)"),                      # 12.500 (BHD style amounts)
    re.compile(r"\d+(?:\.\d+)?\s*%"),                                # 10%  (discounts / VAT claims)
    re.compile(r"(?i)\b(?:free of charge|for free|no charge|complimentary|مجانا|مجاني|بدون رسوم)\b"),
    re.compile(r"(?i)\b(?:discount|خصم)\b"),
]


def find_prices(text: str):
    """All substrings in `text` that look like a price, amount, free-offer or discount."""
    t = prep(text or "")
    found = []
    for p in _PATTERNS:
        for m in p.finditer(t):
            found.append(m.group(0).strip())
    # de-duplicate, keep order
    seen, out = set(), []
    for f in found:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def has_price(text: str) -> bool:
    return bool(find_prices(text))


def scrub(text: str):
    """Return (clean_text, removed_matches). Removed pieces are replaced with nothing."""
    removed = find_prices(text)
    clean = prep(text or "")
    for r in sorted(removed, key=len, reverse=True):
        clean = clean.replace(r, "")
    clean = re.sub(r"\s{2,}", " ", clean).strip(" ,;-")
    return clean, removed


_INJECTION = [
    r"ignore (?:all |any |the )?(?:previous|above|prior|earlier) (?:instructions?|prompts?|rules?)",
    r"disregard (?:all |any |the )?(?:previous|above|prior)",
    r"system prompt", r"you are now", r"new instructions?", r"act as", r"developer mode", r"jailbreak",
    r"(?:set|make|put) (?:the )?(?:price|total|cost)", r"(?:price|total) (?:is|to|=) ?\d", r"100% ?discount",
    r"reveal (?:your|the) (?:prompt|instructions|api key)", r"api[_ ]?key", r"</?(?:system|assistant|instructions?)>",
    r"تجاهل (?:كل |جميع )?(?:التعليمات|الاوامر|الأوامر)", r"انسى (?:كل )?(?:التعليمات|ما سبق)",
    r"اعتبر نفسك", r"(?:خلي|اجعل|حط) (?:السعر|المجموع)", r"خصم ?100",
]
_INJ_RE = re.compile("|".join(_INJECTION), re.IGNORECASE)


def injection_signals(raw: str):
    """Heuristic signals that the customer text is trying to instruct the AI. Informational only:
    the real defences are structured output validation and the absence of tools or price fields."""
    return [m.group(0) for m in _INJ_RE.finditer(prep(raw or ""))][:5]
