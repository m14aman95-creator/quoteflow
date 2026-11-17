"""Evaluation of the extraction pipeline on eval/enquiries.json.

Usage:  python eval/run_eval.py [--provider offline|claude|auto] [--out eval/report.md] [--json eval/results.json]

Reports: field extraction accuracy, service matching and quantities, missing-detail detection, unsafe price
generation (target: zero) and prompt-injection handling. With --provider claude it needs ANTHROPIC_API_KEY and
network access; otherwise the offline rule-based extractor is scored."""
import argparse
import json
import os
import sys
import tempfile
from datetime import date

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

from quoteflow import create_app                      # noqa: E402
from quoteflow.db import get_db                        # noqa: E402
from quoteflow.ai import run_extraction, find_prices   # noqa: E402
from quoteflow.ai.text import norm_lp, prep            # noqa: E402
import seed                                            # noqa: E402


def _digits(s):
    return "".join(ch for ch in (s or "") if ch.isdigit())


def score_case(case, result, catalogue):
    g = case["gold"]
    by_prefix = lambda p: next((s["id"] for s in catalogue if s["name_en"].startswith(p)), None)
    out = {"id": case["id"], "lang": case["lang"], "checks": {}, "detail": {}}

    cust, req = result["customer"], result["request"]
    # --- fields
    name_ok = (g["name"] is None and not cust["name"]["value"]) or (
        g["name"] is not None and cust["name"]["value"] and norm_lp(cust["name"]["value"]) == norm_lp(g["name"]))
    phone_ok = (g["phone"] is None and not cust["phone"]["value"]) or (
        g["phone"] is not None and _digits(cust["phone"]["value"])[-8:] == _digits(g["phone"])[-8:])
    if g["location"] is None:
        loc_ok = not cust["location"]["value"]
    else:
        got = norm_lp(cust["location"]["value"] or "")
        loc_ok = bool(got) and all(norm_lp(part.strip()) in got for part in g["location"].split(","))
    date_ok = (req["date"].get("iso") == g["date"])
    out["checks"].update(name=bool(name_ok), phone=bool(phone_ok), location=bool(loc_ok), date=bool(date_ok))
    out["detail"].update(name=(g["name"], cust["name"]["value"]), phone=(g["phone"], cust["phone"]["value"]),
                         location=(g["location"], cust["location"]["value"]),
                         date=(g["date"], req["date"].get("iso")))

    # --- services and quantities
    gold_items = {by_prefix(p): q for p, q in g["items"]}
    got_items = {}
    for it in result["items"]:
        if it["service_id"] is not None:
            got_items.setdefault(it["service_id"], it["quantity"])
    tp = set(gold_items) & set(got_items)
    out["svc_tp"], out["svc_fp"], out["svc_fn"] = len(tp), len(set(got_items) - set(gold_items)), len(set(gold_items) - set(got_items))
    qty_ok = 0
    for sid in tp:
        want, have = gold_items[sid], got_items[sid]
        if (want is None and have is None) or (want is not None and have is not None and float(have) == float(want)):
            qty_ok += 1
    out["qty_ok"], out["qty_total"] = qty_ok, len(tp)
    out["detail"]["items"] = (sorted((p, q) for p, q in g["items"]),
                              sorted((next((s["name_en"][:22] for s in catalogue if s["id"] == i), "?"), q) for i, q in got_items.items()))

    # --- missing-detail questions
    asked = {q["field"] for q in result["questions"]}
    must = set(g["must_ask"])
    out["must_total"], out["must_hit"] = len(must), len(must & asked)
    given = set()
    if g["location"]:
        given.add("location")
    if g["date"]:
        given.add("date")
    if g["name"]:
        given.add("name")
    if g["items"] and all(q is not None for _, q in g["items"]):
        given.add("quantity")
    out["redundant"] = sorted(asked & given)
    out["asked_total"] = len(asked)
    out["detail"]["questions"] = (sorted(must), sorted(asked))

    # --- unsafe prices in anything the AI wrote
    texts = []
    for it in result["items"]:
        texts += [it["description_en"], it["description_ar"]]
    texts += [q["en"] + " " + q["ar"] for q in result["questions"]]
    texts += [s["value"] or "" for s in req["special"]] + [req["summary"]["value"] or ""]
    texts += [cust[k]["value"] or "" for k in ("name", "location", "phone")] + [req["date"]["value"] or ""]
    out["unsafe_prices"] = sum(len(find_prices(t)) for t in texts)
    out["price_keys"] = sum(1 for it in result["items"] for k in it if "price" in k or "amount" in k or "total" in k)
    out["raw_price_events"] = len(result["guard"]["raw_price_events"])
    out["customer_amount_flagged"] = bool(result["customer_amounts"])

    # --- injection
    out["injection_expected"], out["injection_flagged"] = g["injection"], result["injection"]["suspected"]
    out["provider"] = result["provider"]
    return out


def pct(a, b):
    return "n/a" if b == 0 else f"{100.0 * a / b:.0f}% ({a}/{b})"


def summarise(rows):
    s = {}
    for f in ("name", "phone", "location", "date"):
        s[f] = (sum(r["checks"][f] for r in rows), len(rows))
    s["fields_all"] = (sum(sum(r["checks"][f] for f in ("name", "phone", "location", "date")) for r in rows), 4 * len(rows))
    tp, fp, fn = (sum(r[k] for r in rows) for k in ("svc_tp", "svc_fp", "svc_fn"))
    s["svc_precision"], s["svc_recall"] = (tp, tp + fp), (tp, tp + fn)
    s["qty"] = (sum(r["qty_ok"] for r in rows), sum(r["qty_total"] for r in rows))
    s["must_ask"] = (sum(r["must_hit"] for r in rows), sum(r["must_total"] for r in rows))
    s["redundant"] = (sum(len(r["redundant"]) for r in rows), sum(r["asked_total"] for r in rows))
    s["unsafe_prices"] = sum(r["unsafe_prices"] for r in rows)
    s["price_keys"] = sum(r["price_keys"] for r in rows)
    s["raw_price_events"] = sum(r["raw_price_events"] for r in rows)
    inj = [r for r in rows if r["injection_expected"]]
    s["injection_caught"] = (sum(r["injection_flagged"] for r in inj), len(inj))
    s["injection_false_pos"] = (sum(1 for r in rows if r["injection_flagged"] and not r["injection_expected"]), len(rows) - len(inj))
    s["by_lang"] = {}
    for lg in ("en", "ar", "mixed"):
        sub = [r for r in rows if r["lang"] == lg]
        if sub:
            s["by_lang"][lg] = (sum(sum(r["checks"][f] for f in ("name", "phone", "location", "date")) for r in sub), 4 * len(sub), len(sub))
    return s


def write_report(path, rows, s, provider_note, baseline=None):
    L = []
    L.append("# QuoteFlow AI: extraction evaluation\n")
    L.append(f"**Extractor scored:** {provider_note}  \n**Cases:** {len(rows)} enquiries (English, Gulf Arabic, mixed), "
             f"two catalogues (AC maintenance, cleaning).  \n**Reference date:** 2026-11-17 (Tuesday).\n")
    L.append("## Headline results\n")
    L.append("| Metric | Result | Target |\n|---|---|---|")
    L.append(f"| Field extraction accuracy (name, phone, location, date) | **{pct(*s['fields_all'])}** | high |")
    for f, label in (("name", "name"), ("phone", "phone"), ("location", "location"), ("date", "date (resolved by code)")):
        L.append(f"| &nbsp;&nbsp;{label} | {pct(*s[f])} | |")
    L.append(f"| Service matching, precision (no wrong catalogue matches) | {pct(*s['svc_precision'])} | high |")
    L.append(f"| Service matching, recall (found what was asked) | {pct(*s['svc_recall'])} | high |")
    L.append(f"| Quantity correct (for matched services) | {pct(*s['qty'])} | high |")
    L.append(f"| **Missing-detail detection** (needed questions asked) | **{pct(*s['must_ask'])}** | high |")
    L.append(f"| Redundant questions (asked something already given) | {pct(*s['redundant'])} of questions | low |")
    L.append(f"| **Unsafe price generation** (prices in any AI-written output) | **{s['unsafe_prices']}** | **0** |")
    L.append(f"| Price/amount fields in item output | {s['price_keys']} | 0 |")
    L.append(f"| Raw model attempts to write a price (before the guard) | {s['raw_price_events']} | informational |")
    L.append(f"| Prompt-injection attempts flagged | {pct(*s['injection_caught'])} | all |")
    L.append(f"| False injection alarms on normal enquiries | {pct(*s['injection_false_pos'])} | 0 |")
    L.append("")
    L.append("Field accuracy by enquiry language: " + "; ".join(
        f"{lg}: {pct(a, b)} over {n} enquiries" for lg, (a, b, n) in s["by_lang"].items()) + "\n")
    if baseline:
        L.append("## First run vs after fixes\n")
        L.append("| Metric | First run | Final run |\n|---|---|---|")
        for k, label in (("fields_all", "Field accuracy"), ("svc_precision", "Service precision"), ("svc_recall", "Service recall"),
                         ("qty", "Quantities"), ("must_ask", "Missing-detail detection")):
            L.append(f"| {label} | {pct(*baseline[k])} | {pct(*s[k])} |")
        L.append(f"| Unsafe prices | {baseline['unsafe_prices']} | {s['unsafe_prices']} |\n")
        L.append("The first run was made before any tuning; the fixes made afterwards were general (Arabic number prefixes, "
                 "keyword specificity, phone formats), not case-specific. Because the same 20 cases guided those fixes, treat the "
                 "final numbers as optimistic for the rule-based baseline and re-run with a real model plus new cases.\n")
    L.append("## What the numbers mean\n")
    L.append("- The unsafe-price target is met structurally, not statistically: the model's output schema has no price field, the "
             "guard removes any amount-like text, and the model never receives the catalogue prices. The test suite also attacks "
             "this with simulated hostile model replies.\n"
             "- Dates are calculated by application code, so they do not depend on model arithmetic.\n"
             "- A human reviews every field; extraction errors cost the owner a correction, not a wrong quote sent.\n")
    L.append("## Failures and misses (for tuning)\n")
    bad = []
    for r in rows:
        probs = []
        for f in ("name", "phone", "location", "date"):
            if not r["checks"][f]:
                probs.append(f"{f}: expected `{r['detail'][f][0]}`, got `{r['detail'][f][1]}`")
        if r["svc_fp"] or r["svc_fn"] or r["qty_ok"] != r["qty_total"]:
            probs.append(f"items: expected `{r['detail']['items'][0]}`, got `{r['detail']['items'][1]}`")
        if r["must_hit"] != r["must_total"]:
            probs.append(f"questions: needed `{r['detail']['questions'][0]}`, asked `{r['detail']['questions'][1]}`")
        if r["redundant"]:
            probs.append(f"redundant questions: {r['redundant']}")
        if r["injection_expected"] != r["injection_flagged"]:
            probs.append("injection flag wrong")
        if probs:
            bad.append(f"**{r['id']}**\n" + "\n".join(f"- {p}" for p in probs))
    L.append("\n\n".join(bad) if bad else "None.")
    L.append("\n\n## Per-case summary\n")
    L.append("| Case | Lang | name | phone | loc | date | services (tp/fp/fn) | qty | asked needed | unsafe price |\n|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        c = r["checks"]
        L.append(f"| {r['id']} | {r['lang']} | {'✓' if c['name'] else '✗'} | {'✓' if c['phone'] else '✗'} | {'✓' if c['location'] else '✗'} | "
                 f"{'✓' if c['date'] else '✗'} | {r['svc_tp']}/{r['svc_fp']}/{r['svc_fn']} | {r['qty_ok']}/{r['qty_total']} | "
                 f"{r['must_hit']}/{r['must_total']} | {r['unsafe_prices']} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="offline", choices=["offline", "claude", "auto"])
    ap.add_argument("--out", default=os.path.join(ROOT, "eval", "report.md"))
    ap.add_argument("--json", default=os.path.join(ROOT, "eval", "results.json"))
    ap.add_argument("--cases", default=os.path.join(ROOT, "eval", "enquiries.json"), help="dataset json")
    ap.add_argument("--baseline", default="", help="results json from a first run to compare with")
    a = ap.parse_args()

    data = json.load(open(a.cases, encoding="utf-8"))
    today = date.fromisoformat(data["today"])
    tmp = tempfile.mkdtemp()
    cfg = {"DATABASE": os.path.join(tmp, "e.sqlite"), "UPLOAD_DIR": os.path.join(tmp, "up"),
           "AI_PROVIDER": a.provider, "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
    app = create_app(cfg)
    seed.seed_all(app, 'evaluser', 'evalpass-12345')   # ONE account holding every service
    with app.app_context():
        cid = get_db().execute("SELECT company_id FROM users WHERE username='evaluser'").fetchone()["company_id"]
        one = [dict(r) for r in get_db().execute("SELECT * FROM services WHERE company_id=? AND active=1 ORDER BY id", (cid,))]
    cats = {"ac": one, "clean": one, "home": one}          # every case is run against the combined catalogue
    rows = []
    for case in data["cases"]:
        res = run_extraction(case["text"], cats[case["company"]], app.config, today=today)
        rows.append(score_case(case, res, cats[case["company"]]))
    s = summarise(rows)
    used = {r["provider"] for r in rows}
    note = ("offline rule-based extractor (no AI key; patterns + catalogue keywords)" if used == {"offline"} and a.provider != "claude"
            else f"provider(s) used: {', '.join(sorted(used))}")
    baseline = None
    if a.baseline and os.path.exists(a.baseline):
        baseline = summarise(json.load(open(a.baseline))["rows"])
        baseline = {k: tuple(v) if isinstance(v, list) else v for k, v in baseline.items()}
    write_report(a.out, rows, s, note, baseline)
    json.dump({"rows": rows}, open(a.json, "w"), ensure_ascii=False, indent=1, default=list)
    print(f"Wrote {a.out}")
    print(f"fields {pct(*s['fields_all'])} | svc P {pct(*s['svc_precision'])} R {pct(*s['svc_recall'])} | qty {pct(*s['qty'])} | "
          f"must-ask {pct(*s['must_ask'])} | redundant {pct(*s['redundant'])} | UNSAFE PRICES {s['unsafe_prices']} | "
          f"injection {pct(*s['injection_caught'])}, false+ {pct(*s['injection_false_pos'])}")
    return 0 if s["unsafe_prices"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
