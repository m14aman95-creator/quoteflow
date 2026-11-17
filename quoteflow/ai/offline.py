"""Offline rule-based extractor. NOT an LLM: patterns, a Bahrain area list and the user's catalogue keywords.

It exists so the demo works without an API key and as a baseline for the evaluation report.
It returns the same shape the language model must return (ai.schema.RawExtraction), so both go through the
same validation, price guard and trust-cue pipeline."""
import re
from datetime import date
from .text import prep, norm_lp, is_arabic, detect_language, tokens_with_pos, token_number
from .dates import find_date_phrase

AREAS = {
    "saar": "سار", "sar": "", "seef": "السيف", "juffair": "الجفير", "manama": "المنامة", "riffa": "الرفاع",
    "isa town": "مدينة عيسى", "hamad town": "مدينة حمد", "muharraq": "المحرق", "busaiteen": "البسيتين",
    "amwaj": "امواج", "budaiya": "البديع", "sitra": "سترة", "adliya": "العدلية", "hidd": "الحد", "tubli": "توبلي",
    "sanabis": "سنابس", "zinj": "الزنج", "janabiyah": "الجنبية", "jidhafs": "جدحفص", "galali": "قلالي",
    "arad": "عراد", "hoora": "الحورة", "gudaibiya": "القضيبية", "umm al hassam": "ام الحصم", "salmabad": "سلماباد",
    "aali": "عالي", "sanad": "سند", "diyar al muharraq": "ديار المحرق", "karbabad": "كرباباد", "barbar": "باربار",
    "janusan": "جنوسان", "durrat al bahrain": "درة البحرين", "reef island": "جزيرة ريف", "tashan": "تاشان",
    "zallaq": "الزلاق", "malkiya": "المالكية", "shakhura": "الشاخورة", "hamala": "الهملة", "dar kulaib": "دار كليب",
    "sakhir": "الصخير", "awali": "عوالي", "jasra": "الجسرة", "samaheej": "سماهيج", "dumistan": "دمستان",
    "bilad al qadeem": "البلاد القديم", "mahooz": "المحوز", "naim": "النعيم", "bahrain bay": "خليج البحرين",
    "adhari": "الاداري", "um al hassam": "", "al jasra": "", "karranah": "الكرانه", "qudaibiya": "",
    "burhama": "برهامه", "mina salman": "ميناء سلمان",
}
_AREA_ALIASES = {"sar": "Saar"}

_STOP_AR = set("من في ابي ابغي ابغى اريد محتاج عندي يا ويا و على الى عن مع هل ممكن لو بس".split())


def _find_phone(t):
    m = re.search(r"(?<![\d.])(?:\+?\(?973\)?[\s-]?)?([13689]\d(?:[\s-]?\d){6})(?!\d)", t)
    if not m:
        return None, None
    d = re.sub(r"\D", "", m.group(1))
    return f"+973 {d[:4]} {d[4:]}", (m.start(), m.end())


_NAME_STOP = {"thanks", "thank", "regards", "please", "hi", "hello", "ok", "okay", "bye", "urgent", "kind", "best",
              "salam", "shukran", "dear", "sir", "madam", "hey", "thx", "cheers", "morning", "evening", "tomorrow", "today"}
_TAIL = r"(?:[\s,.-]*\+?[\d\s-]{7,})?[\s.!]*$"


_NOT_NAME_WORDS = {"location", "area", "block", "road", "building", "flat", "villa", "shop", "office", "house", "home",
                   "apartment", "street", "address", "floor", "number", "phone", "mobile", "whatsapp", "contact"}


def _ok_name(name, area_keys):
    words = name.lower().split()
    if not words or words[0] in _NAME_STOP:
        return False
    if name.lower() in area_keys or any(w in _NOT_NAME_WORDS or w in area_keys for w in words):
        return False
    return True


def _find_name(t):
    area_keys = set(AREAS)
    m = re.search(r"\b(?i:my name is|i am|i'm|this is|call me|name\s*:)\s+([A-Z][a-z]{1,}(?:\s[A-Z][a-z]{1,})?)", t)
    if m and _ok_name(m.group(1), area_keys):
        return m.group(1)
    m = re.search(r"\b(?:Mr|Mrs|Ms|Eng|Dr|Miss)\.?\s+([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?)", t)
    if m and _ok_name(m.group(1), area_keys):
        return m.group(1)
    m = re.search(r"(?i:thanks|thank you|regards|best regards|best|shukran|thx|cheers)[,!:\s-]+([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?)" + _TAIL, t.strip())
    if m and _ok_name(m.group(1), area_keys):
        return m.group(1)
    m = re.search(r"(?:[.!?]\s+|\n)([A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})?)" + _TAIL, t.strip())
    if m and _ok_name(m.group(1), area_keys):
        return m.group(1)
    m = re.search(r"(?:اسمي|معك|معاك|اخوكم|أخوكم|اختكم|أختكم|الاخ|الأخ)\s+([\u0621-\u064A]{2,})(?:\s+([\u0621-\u064A]{3,}))?", t)
    if m:
        first, second = m.group(1), m.group(2)
        if second and second not in _STOP_AR and len(second) >= 3 and not norm_lp(second).startswith(("ابي", "ابغ", "محتاج", "اريد")):
            return f"{first} {second}"
        return first
    return None


def _find_location(t, n):
    best = None
    for en, ar in AREAS.items():
        for m in re.finditer(rf"(?<![a-z]){re.escape(en)}(?![a-z])", n):
            if best is None or m.start() < best[0]:
                best = (m.start(), m.end(), en)
        if ar:
            a = norm_lp(ar)
            idx = n.find(a)
            if idx >= 0 and (best is None or idx < best[0]):
                best = (idx, idx + len(a), en)
    extra = []
    m = re.search(r"(?:block|بلوك|مجمع)\s*#?\s*(\d{3,4})", n)
    if m:
        extra.append(f"Block {m.group(1)}")
    m = re.search(r"(?:road|rd\.?|طريق|شارع)\s*#?\s*(\d{1,4})", n)
    if m:
        extra.append(f"Road {m.group(1)}")
    m = re.search(r"(?:building|bldg|مبنى|بناية|عمارة)\s*#?\s*(\d{1,4})", n)
    if m:
        extra.append(f"Building {m.group(1)}")
    m = re.search(r"(?:flat|apt|apartment|شقة|شقه)\s*#?\s*(\d{1,4})", n)
    if m:
        extra.append(f"Flat {m.group(1)}")
    if best:
        area = t[best[0]:best[1]].strip()
        area = _AREA_ALIASES.get(area.lower(), area) if not is_arabic(area) else area
        if not is_arabic(area) and area.islower():
            area = area.title()
        return ", ".join([area] + extra)
    return ", ".join(extra) if extra else None


def _mask(t, spans):
    s = list(t)
    for a, b in spans:
        for i in range(a, b):
            s[i] = " "
    return "".join(s)


def _term_spans(n, k):
    k = norm_lp(k).strip()
    if len(k) < 2:
        return []
    if is_arabic(k):
        return [(m.start(), m.end()) for m in re.finditer(re.escape(k), n)] if len(k) >= 3 else []
    return [(m.start(), m.end()) for m in re.finditer(rf"(?<![a-z0-9]){re.escape(k)}(?:s|es|ing|ed)?(?![a-z0-9])", n)]


def _kw_spans(n, svc, weak=False):
    """Keyword hits for a catalogue service. Keyword syntax (catalogue 'keywords' field):
       word          plain keyword (a phrase works too)
       a+b           both words must appear close together (any order)
       ~word         weak keyword (a symptom): only used when no real service matched
       !word         exclusion: the service is NOT matched if this word appears"""
    kws = [k.strip() for k in (svc["keywords"] or "").split(",") if k.strip()]
    if any(k.startswith("!") and _term_spans(n, k[1:]) for k in kws):
        return []
    kws = [k for k in kws if not k.startswith("!")]
    if not weak:
        kws += [svc["name_en"] or "", svc["name_ar"] or ""]
    spans = []
    for kw in kws:
        is_weak = kw.startswith("~")
        if is_weak != weak:
            continue
        parts = [p.strip() for p in kw.lstrip("~").split("+") if p.strip()]
        if len(parts) == 1:
            spans += _term_spans(n, parts[0])
            continue
        lists = [_term_spans(n, p) for p in parts]
        if not all(lists):
            continue
        for a in lists[0]:
            chosen = [a]
            for other in lists[1:]:
                near = min(other, key=lambda b: abs(b[0] - a[0]))
                if abs(near[0] - a[0]) <= 45:
                    chosen.append(near)
            if len(chosen) == len(lists):
                spans.append((min(c[0] for c in chosen), max(c[1] for c in chosen)))
    return spans


_UNIT_HINTS = [
    (r"units?|acs?\b|split|مكيف|وحد|سبلت", "unit"), (r"rooms?|غرف|غرفه", "room"), (r"hours?|ساع", "hour"),
    (r"windows?|نواف|شباب", "window"), (r"seats?|seater|مقعد|مقاعد", "seat"), (r"m2|sqm|متر", "m2"),
    (r"villas?|فيل", "job"), (r"apartments?|flats?|شقه|شقق", "job"),
]


def _nearest_number(n_masked, span, window=5):
    toks = tokens_with_pos(n_masked)
    if not toks:
        return None
    # index of first token that overlaps the span
    ci = next((i for i, (_, s, e) in enumerate(toks) if e > span[0] and s < span[1]), None)
    if ci is None:
        ci = min(range(len(toks)), key=lambda i: abs(toks[i][1] - span[0]))
    best = None
    from .text import DUAL_WORDS
    if norm_lp(toks[ci][0]) in DUAL_WORDS:          # the keyword itself is a dual noun: كنبتين
        return 2, None
    for i, (tok, s, e) in enumerate(toks):
        if i == ci or abs(i - ci) > window:
            continue
        v = token_number(tok)
        if v is None or v == 0:
            continue
        nxt = toks[i + 1][0].lower() if i + 1 < len(toks) else ""
        if nxt in ("am", "pm", "bhd", "bd", "dinar", "dinars") or re.fullmatch(r"\d+(?:st|nd|rd|th)", tok.lower()):
            continue
        d = abs(i - ci)
        if best is None or d < best[0]:
            best = (d, v, i)
    if not best:
        return None
    _, v, i = best
    # unit hint from the next one or two tokens
    hint = None
    for j in (i + 1, i + 2):
        if j < len(toks):
            for pat, u in _UNIT_HINTS:
                if re.match(pat, norm_lp(toks[j][0])):
                    hint = u
                    break
        if hint:
            break
    return v, hint


def _special_requirements(t, n):
    pats = [
        r"urgent(?:ly)?|asap|emergency|immediately|as soon as possible|مستعجل|ضروري|طارئ|طوارئ|بسرعه|بأسرع وقت|اقرب وقت",
        r"after \d{1,2}(?::\d{2})? ?(?:am|pm)?|before \d{1,2}(?::\d{2})? ?(?:am|pm)?|between \d{1,2}(?::\d{2})? ?(?:am|pm)? ?(?:and|-|to) ?\d{1,2}(?::\d{2})? ?(?:am|pm)?",
        r"(?:in the |)(?:morning|afternoon|evening)|بعد العصر|بعد المغرب|الصبح|الصباح|بالليل|بعد الظهر|بعد العشاء|بعد \d{1,2}",
        r"weekend|friday|saturday|الجمعه|السبت|نهاية الاسبوع",
        r"no cooling|not cooling|not working|stopped working|making noise|noisy|smell|bad smell|ما يبرد|مو يبرد|لا يبرد|ما يشتغل|صوت|ريحه",
        r"pet|dog|cat|baby|elderly|كلب|قطه|طفل|مريض",
        r"parking|lift|elevator|second floor|3rd floor|floor \d|دور \d|الدور|مصعد|بدون مصعد|موقف",
        r"bring (?:your )?own|supplies (?:included|provided)|with materials|مع المواد|مع المعدات",
        r"photo|picture|video|صور[هة]?|فيديو",
    ]
    out, seen = [], set()
    for p in pats:
        for m in re.finditer(p, n):
            s = t[m.start():m.end()].strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
    return out[:6]


def extract(raw: str, catalogue: list, today: date) -> dict:
    t = prep(raw)
    n = norm_lp(t)
    lang = detect_language(t)

    phone, pspan = _find_phone(t)
    name = _find_name(t)
    location = _find_location(t, n)
    dphrase, _dt = find_date_phrase(t, today)

    # mask things that look like numbers but are not quantities
    spans = []
    if pspan:
        spans.append(pspan)
    for pat in (r"(?:block|بلوك|مجمع|road|rd\.?|طريق|شارع|building|bldg|مبنى|بناية|عمارة|flat|apt|شقه|شقة)\s*#?\s*\d+",
                r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", r"after \d{1,2}|before \d{1,2}|بعد \d{1,2}",
                r"\d{1,2}[/\-.]\d{1,2}(?:[/\-.]\d{2,4})?", r"\b20\d\d\b", r"\+?973", r"\d{7,}"):
        for m in re.finditer(pat, n):
            spans.append((m.start(), m.end()))
    nm = _mask(n, spans)

    # catalogue matching by keywords (strong hits first; weak symptom keywords only if no real work item matched)
    strong, weak = [], []
    for svc in catalogue:
        sp = _kw_spans(n, svc)
        if sp:
            strong.append((min(s_ for s_, _ in sp), svc, sp))
        else:
            wsp = _kw_spans(n, svc, weak=True)
            if wsp:
                weak.append((min(s_ for s_, _ in wsp), svc, wsp))
    work_hit = any(svc["unit"] != "visit" for _, svc, _ in strong)
    hits = sorted(strong + ([] if work_hit else weak), key=lambda h: h[0])

    # global "N units" fallback quantity (e.g. "3 ACs", "three split units")
    gq = None
    m = re.search(r"\b(\w+)\s+(?:split\s+|window\s+)?(?:units?|acs?|air ?conditioners?|مكيفات?|وحدات?|مكيف)\b", nm)
    if m:
        gq = token_number(m.group(1))
    singular = bool(re.search(r"\b(?:my|the|our|this|one|a|an)\s+(?:\w+\s+)?(?:ac|a/c|air ?conditioner|aircon)\b", nm)
                    or re.search(r"مكيف(?![اتين])", nm))
    _count_words = r"(?:visits?|times?|jobs?|months?|زيار|مره|مرات|شهر)"

    items = []
    for _, svc, sp in hits:
        best = None
        for span in sp:
            r = _nearest_number(nm, span)
            if r and (best is None):
                best = r
        qty, qsrc, hint = (None, "unknown", None)
        if svc["unit"] in ("visit", "job", "month"):
            # one job / visit unless the customer counts them ("2 visits"); stray numbers (bedrooms, units) are ignored
            toks = tokens_with_pos(nm)
            counted = None
            if best:
                for i, (tk, _s, _e) in enumerate(toks):
                    if token_number(tk) == best[0] and i + 1 < len(toks) and re.match(_count_words, norm_lp(toks[i + 1][0])):
                        counted = best[0]
            qty, qsrc = (counted, "customer") if counted else (1, "ai")
        elif best:
            qty, hint = best[0], best[1]
            qsrc = "customer"
        elif gq and svc["unit"] == "unit":
            qty, qsrc = gq, "customer"
        elif svc["unit"] == "unit" and singular:
            qty, qsrc = 1, "ai"
        first = min(sp, key=lambda s_: s_[0])
        a = max([m_.end() for m_ in re.finditer(r"[,.;؛،\n!?؟]| and | و", t[:first[0]])] or [0])
        mb = re.search(r"[,.;؛،\n!?؟]| and | و", t[first[1]:])
        b = first[1] + mb.start() if mb else len(t)
        words = t[a:b].strip()
        items.append({
            "customer_words": words[:160], "quantity": qty, "quantity_source": qsrc,
            "unit_hint": hint or svc["unit"], "matched_service_id": svc["id"],
            "description_en": svc["desc_en"] or svc["name_en"], "description_ar": svc["desc_ar"] or svc["name_ar"],
            "uncertain": qty is None,
        })
    if not items:
        first_sentence = re.split(r"[.!?\n؟]", t.strip(), maxsplit=1)[0][:120] or t.strip()[:120]
        items.append({"customer_words": first_sentence, "quantity": None, "quantity_source": "unknown",
                      "unit_hint": None, "matched_service_id": None,
                      "description_en": "", "description_ar": "", "uncertain": True})

    # an item with a "specific" keyword hides a generic "service" duplicate: keep as is (user can delete)
    summary = "; ".join((next((s["name_en"] for s in catalogue if s["id"] == i["matched_service_id"]), i["customer_words"]))
                        for i in items)[:300]
    flags = []
    if any(i["matched_service_id"] is None for i in items):
        flags.append("Could not match the request to a service in your catalogue.")
    if any(i["quantity"] is None for i in items):
        flags.append("Quantity is not clear for at least one item.")

    def fv(v, src="customer"):
        return {"value": v, "source": src if v else "unknown"}

    return {
        "language": lang,
        "customer_name": fv(name), "phone": fv(phone), "location": fv(location), "requested_date": fv(dphrase),
        "service_summary": fv(summary, "ai"),
        "special_requirements": [{"value": s, "source": "customer"} for s in _special_requirements(t, n)],
        "items": items, "uncertainty_flags": flags, "clarification_questions": [], "injection_suspected": False,
    }
