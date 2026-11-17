"""Extraction pipeline: provider -> strict schema -> price guard -> provenance checks -> catalogue
validation -> deterministic missing-detail questions. The output of this module is the only thing the UI shows
as 'AI' content, and it can never contain a price."""
import re
from datetime import date
from pydantic import ValidationError

from .schema import RawExtraction
from .guard import find_prices, scrub, injection_signals
from .text import prep, norm, norm_lp, detect_language
from .dates import find_date_phrase, pretty
from .questions import build_questions
from .claude import ClaudeProvider, OfflineProvider, ProviderError
from . import offline as offline_mod


def pick_provider(config):
    mode = (config.get("AI_PROVIDER") or "auto").lower()
    key = config.get("ANTHROPIC_API_KEY") or ""
    if mode == "offline" or (mode == "auto" and not key):
        return OfflineProvider()
    return ClaudeProvider(key, config.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"))


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _strings(v)


def _grounded(value: str, text_n: str) -> bool:
    """Is every word of `value` present in the customer's message? (provenance check)"""
    toks = [w for w in re.findall(r"[\w؀-ۿ]+", norm(value)) if len(w) > 1]
    return bool(toks) and all(w in text_n for w in toks)


def _mask_digits(s: str) -> str:
    """Guard logs keep a masked trace (digits -> #) so no model-written price is ever stored."""
    return re.sub(r"\d", "#", s)


def _digits(s):
    return re.sub(r"\D", "", s or "")


def run_extraction(raw_text: str, catalogue: list, config, today: date = None, provider=None, max_chars=4000) -> dict:
    today = today or date.today()
    text = prep(raw_text or "").strip()[:max_chars]
    if not text:
        raise ValueError("The enquiry is empty.")
    text_n = norm(text)
    by_id = {s["id"]: s for s in catalogue}
    notices, guard_events = [], {"raw_price_events": [], "removed": []}
    provider = provider or pick_provider(config)

    # ---- 1. ask the provider (one retry on invalid output), else fall back to offline rules ----
    raw_dict, used, hint = None, provider.name, ""
    attempts = 2 if provider.name == "claude" else 1
    parsed = None
    for attempt in range(attempts):
        try:
            raw_dict = provider.extract(text, catalogue, today.isoformat(), hint)
        except ProviderError as e:
            hint, raw_dict = str(e), None
            notices.append(f"AI service problem: {e}")
            continue
        # measure what the model tried to say about money BEFORE the guard cleans it
        for s in _strings(raw_dict):
            for p in find_prices(s):
                guard_events["raw_price_events"].append(_mask_digits(p))
        try:
            parsed = RawExtraction.model_validate(raw_dict)
            break
        except ValidationError as e:
            hint = "; ".join(f"{'.'.join(map(str, err['loc']))}: {err['type']}" for err in e.errors()[:5])
            notices.append("AI reply did not match the required format and was rejected.")
            guard_events.setdefault("schema_rejections", []).append(hint)
    if parsed is None:
        if provider.name == "claude":
            notices.append("Used the built-in basic extractor instead. Please check every field carefully.")
        used = "offline" if provider.name == "claude" else provider.name
        raw_dict = offline_mod.extract(text, catalogue, today)
        parsed = RawExtraction.model_validate(raw_dict)
    d = parsed.model_dump()

    # ---- 2. price guard on every piece of text the model wrote ----
    def clean(s):
        c, removed = scrub(s)
        if removed:
            guard_events["removed"].extend(_mask_digits(r) for r in removed)
        return c, bool(removed)

    for key in ("customer_name", "location", "requested_date", "service_summary"):
        if d[key]["value"]:
            d[key]["value"], _ = clean(d[key]["value"])
            d[key]["value"] = d[key]["value"] or None
    for sr in d["special_requirements"]:
        sr["value"], _ = clean(sr["value"] or "")
    d["special_requirements"] = [s for s in d["special_requirements"] if s["value"]]
    d["uncertainty_flags"] = [c for c in (clean(f)[0] for f in d["uncertainty_flags"]) if c]
    for q in d["clarification_questions"]:
        q["question_en"], _ = clean(q["question_en"])
        q["question_ar"], _ = clean(q["question_ar"])
    d["clarification_questions"] = [q for q in d["clarification_questions"] if q["question_en"]]

    # ---- 3. fields: provenance (is 'customer' really in the message?) ----
    flags = list(d["uncertainty_flags"])

    def field(fv, label, check=None):
        v = fv["value"]
        out = {"value": v, "source": fv["source"] if v else "unknown", "uncertain": False}
        if v and out["source"] == "customer" and not _grounded(v, text_n):
            out["source"], out["uncertain"] = "ai", True
            flags.append(f"{label} was not found word-for-word in the message; treated as an AI inference.")
        if v and out["source"] == "ai":
            out["uncertain"] = True
        return out

    name_f = field(d["customer_name"], "Customer name")
    loc_f = field(d["location"], "Location")
    # phone: digits must appear in the message; otherwise discard. Regex can fill a missing one.
    ph = d["phone"]["value"]
    phone_f = {"value": None, "source": "unknown", "uncertain": False}
    if ph and _digits(ph) and _digits(ph)[-8:] in _digits(text):
        phone_f = {"value": ph, "source": "customer", "uncertain": False}
    elif ph:
        flags.append("A phone number from the AI was not in the message and was discarded.")
    if not phone_f["value"]:
        p, _span = offline_mod._find_phone(text)
        if p:
            phone_f = {"value": p, "source": "customer", "uncertain": False}
    # date: the app, not the model, resolves relative dates
    dphrase, dt = find_date_phrase(text, today)
    date_f = field(d["requested_date"], "Date")
    if not date_f["value"] and dphrase:
        date_f = {"value": dphrase, "source": "customer", "uncertain": False}
    resolved = None
    if date_f["value"]:
        _p, dt2 = find_date_phrase(date_f["value"], today)
        dt = dt2 or dt
        resolved = dt.isoformat() if dt else None
        if not dt:
            date_f["uncertain"] = True
    date_f["iso"] = resolved
    date_f["pretty"] = pretty(dt) if dt else None

    special = [field(s, "Requirement") for s in d["special_requirements"]]

    # ---- 4. items: validate catalogue ids, safe descriptions, integer quantities ----
    items = []
    for it in d["items"]:
        sid = it["matched_service_id"]
        method = ("ai" if used == "claude" else "keyword") if sid in by_id else "none"
        if sid not in by_id:
            sid = None
            if it["customer_words"]:  # keyword fallback on the customer's own words
                cw = norm_lp(prep(it["customer_words"]))
                best = None
                for s in catalogue:
                    n_hits = len(offline_mod._kw_spans(cw, s))
                    if n_hits and (best is None or n_hits > best[0]):
                        best = (n_hits, s["id"])
                if best:
                    sid, method = best[1], "keyword"
        svc = by_id.get(sid)
        den, _ = clean(it["description_en"])
        dar, _ = clean(it["description_ar"])
        if svc:
            den = den or svc["desc_en"] or svc["name_en"]
            dar = dar or svc["desc_ar"] or svc["name_ar"]
        qty = it["quantity"]
        qty_milli = int(round(qty * 1000)) if qty not in (None, 0) else None
        items.append({
            "customer_words": clean(it["customer_words"])[0], "quantity": (qty if qty not in (None, 0) else None),
            "quantity_milli": qty_milli, "quantity_source": it["quantity_source"] if qty else "unknown",
            "unit_hint": it["unit_hint"] or (svc["unit"] if svc else None),
            "service_id": sid, "match_method": method if svc else "none",
            "description_en": den, "description_ar": dar,
            "uncertain": bool(it["uncertain"]) or svc is None or qty is None,
        })
    for i in items:
        if i["service_id"] is None:
            flags.append(f"No catalogue service matched “{i['customer_words'][:60]}”. Choose one or add it manually.")

    # ---- 5. assemble, then deterministic questions ----
    base = {"location": loc_f, "requested_date": date_f, "customer_name": name_f,
            "items": [{"matched_service_id": i["service_id"], "quantity": i["quantity"]} for i in items]}
    det = build_questions(text, base, by_id)
    core = {"location", "date", "quantity", "name", "service"}
    model_qs = [q for q in d["clarification_questions"] if q["field"] not in core]
    # drop model questions about core fields we already know
    known = {"location": bool(loc_f["value"]), "date": bool(date_f["value"]), "name": bool(name_f["value"])}
    for q in d["clarification_questions"]:
        if q["field"] in core and not known.get(q["field"], False) and q["field"] in ("quantity", "service"):
            model_qs.append(q)
    questions, seen = [], set()
    for q in det + model_qs:
        key = (q["field"], norm(q["question_en"])[:40])
        if q["field"] in seen and q["field"] in core:
            continue
        seen.add(q["field"])
        questions.append({"field": q["field"], "en": q["question_en"], "ar": q["question_ar"]})
    questions = questions[:8]

    inj = injection_signals(text)
    suspected = bool(inj) or d["injection_suspected"]
    if suspected:
        flags.append("This message contains text that looks like instructions to the AI. It was treated as plain "
                     "customer text and ignored. Check prices and quantities yourself.")
    amounts = find_prices(text)
    if amounts:
        flags.append("The customer mentioned an amount (" + ", ".join(amounts[:3]) +
                     "). It is NOT used as a price. Enter prices yourself.")
    summary_f = {"value": d["service_summary"]["value"] or "; ".join(
        (by_id[i["service_id"]]["name_en"] if i["service_id"] else i["customer_words"]) for i in items)[:300],
        "source": "ai", "uncertain": False}

    return {
        "provider": used, "model": getattr(provider, "model", ""), "notices": notices,
        "language": d["language"] if d["language"] else detect_language(text),
        "customer": {"name": name_f, "phone": phone_f, "location": loc_f},
        "request": {"date": date_f, "summary": summary_f, "special": special},
        "items": items, "questions": questions, "flags": list(dict.fromkeys(flags)),
        "customer_amounts": amounts, "injection": {"suspected": suspected, "signals": inj},
        "guard": guard_events,
    }
