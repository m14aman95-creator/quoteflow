# QuoteFlow AI (MVP)

Turn a messy WhatsApp or email enquiry into a reviewed, priced, bilingual (Arabic/English) quotation.

**AI writes language. Application code calculates money. A human always approves.**

## Try it in 2 minutes (no AI key needed)

```bash
pip install -r requirements.txt
python seed.py --username yourname --password 'YourStrongPassword'   # one account with every service
python run.py             # open http://localhost:5000
```

Create the demo account with your own username and password (it holds all four service packs: AC, cleaning, household, furniture moving, plus sample quote history):

```bash
python seed.py --username yourname --password 'YourStrongPassword'
```

If you leave out the password, one is generated and printed once. Then log in with that **username** and password. You can change both later under your name at the top right (*Account*).

Without an API key the app uses a built-in rule-based reader ("demo mode"). It handles common requests in English, Gulf Arabic and mixed text. Add a key for full accuracy.

## What it does

1. Paste a customer message. The app extracts name, phone, location, date, services, quantities and special requirements.
2. Every field is tagged: **Customer said**, **AI inferred**, **Uncertain/missing**, **You approved**.
3. Missing details become bilingual clarification questions, with a copy-ready WhatsApp message (nothing is sent automatically).
4. Matching services come from your catalogue with your standard descriptions and your prices.
5. You edit items, prices, discount and VAT treatment; totals update live.
6. You tick each item as checked, then approve. Only approved quotes can be previewed, exported to PDF (English, Arabic or both) or shared.
7. History with search and statuses: Draft, Sent, Follow-up, Accepted, Rejected, Expired.
8. A monthly quote counter per plan (Free 5, Starter 30, Professional 150, Business 500). Limits are enforced; payments are not built.

## Safety rules, and where they live

| Rule | How it is enforced |
|---|---|
| AI never invents prices | The model's output schema has no price field and rejects unknown keys (`quoteflow/ai/schema.py`). Any amount-like text in model output is removed (`ai/guard.py`). The catalogue sent to the model contains no prices. Prices come only from your catalogue or manual entry. |
| Money is computed by code | `quoteflow/money.py`: integer fils, half-up rounding, no floats (floats are rejected). The browser asks the server for live totals, so there is one copy of the maths. 23 unit tests including 2,000 random quotes. |
| VAT is yours | Rate (default 10%), registered/not, and per-item standard / zero-rated / exempt. You must confirm VAT settings before approving. The app states it is not tax advice. |
| Customer text is untrusted | No tools are given to the extraction step, output is validated, catalogue ids are checked against your catalogue, customer-sourced fields are checked against the message, relative dates are resolved by code, and instruction-like text is flagged. |
| Tenant isolation | Every table has `company_id` and every query is scoped by it. Tests try cross-tenant access on every route. |
| Minimal retention | Raw enquiry text is deleted after your retention setting (default 30 days). |
| Audit log | Edits (with price/quantity changes), approvals, unlocks, exports and plan changes. See *Settings > activity log*. |
| Secrets | Only from environment variables. A local dev key is generated into `instance/` if `SECRET_KEY` is unset. |

## Environment variables

See `.env.example`. The important ones:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required in production. Long random string. |
| `ANTHROPIC_API_KEY` | Optional. Enables the Claude reader. Without it the offline reader is used. |
| `QF_ANTHROPIC_MODEL` | Default `claude-sonnet-5-5`. A smaller model is cheaper for extraction. |
| `QF_AI_PROVIDER` | `auto` (default), `claude` or `offline`. |
| `QF_DATABASE`, `QF_INSTANCE_DIR` | Point at a persistent disk in production. |
| `QF_SECURE_COOKIES` | Set `1` behind HTTPS. |
| `QF_CHROME_BIN` | Chrome/Chromium path for PDFs, if not auto-detected. |

## Run the tests and the evaluation

```bash
python -m pytest -q                         # 104 tests
python eval/run_eval.py                     # tuned set, 20 enquiries -> eval/report.md
python eval/run_eval.py --cases eval/holdout.json --out eval/report_holdout.md
ANTHROPIC_API_KEY=... python eval/run_eval.py --provider claude   # score the real model
```

The evaluation exits with an error if any unsafe price is found.

## Deploy

**Docker (recommended):** the included `Dockerfile` installs Chromium and Noto fonts for correct Arabic PDFs.

```bash
docker build -t quoteflow .
docker run -p 8000:8000 -v qfdata:/data -e SECRET_KEY=$(openssl rand -hex 32) -e ANTHROPIC_API_KEY=sk-... quoteflow
```

**Render / Railway / Fly:** create a web service from this repo using the Dockerfile, attach a persistent disk mounted at `/data`, and set `SECRET_KEY` (and optionally `ANTHROPIC_API_KEY`). Put it behind HTTPS.

Run `python seed.py --username ... --password ...` once inside the container only if you want the demo account. Do not seed a production database.

## Project layout

```
quoteflow/            app package (Flask)
  money.py            calculation engine (the only place money is computed)
  ai/                 schema, price guard, offline reader, Claude adapter, pipeline
  docs.py             bilingual quotation HTML, PDF (headless Chrome), WhatsApp text
  views_*.py          routes: auth, company/settings, catalogue, enquiries/quotes
  templates/ static/  mobile-first UI
tests/                104 tests
eval/                 evaluation sets and reports
seed.py seed_quotes.py  demo data
```

## Catalogue keyword tips

In each service's keywords: `clean+ac` means both words close together; `~not cooling` is a weak symptom word used only if nothing else matches; `!move out` means never match when that phrase appears.

## Free demo hosting on Render
1. Put the project in a GitHub repository (the folder contents, not the zip).
2. On render.com: **New > Blueprint**, pick the repository. `render.yaml` sets everything up.
3. Optional: paste `ANTHROPIC_API_KEY` in the service's Environment tab.
4. Render asks for `ADMIN_USERNAME` and `ADMIN_PASSWORD`: type the username and password you want. Open the `.onrender.com` link and log in with them. The account is re-created on every start (`QF_SEED_DEMO=1`).
The free plan sleeps after 15 minutes idle and its disk resets, so data you add is lost. Use it for demos only.

## Sending quotes (email + WhatsApp)
After you approve a quote, the Share page offers **Send email with PDF** and **Send via WhatsApp**.
- Email needs SMTP settings (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`). For Gmail turn on 2-step verification, create an *App Password*, and use `smtp.gmail.com`, port 587.
- WhatsApp opens WhatsApp with the message ready; you press send there (fully automatic WhatsApp needs the paid WhatsApp Business API, which is out of scope).
- Nothing is ever sent before a human approves the quote. Sends are recorded in the activity log.

## Services included
- **AC / maintenance** (7), **Cleaning** (9), **Household** (13: plumbing, electrical, water heater, handyman, locks, painting, pest control, curtains, TV mounting, furniture assembly, water tank), **Furniture moving** (12: local moves by home size, few-item trips, packing, boxes, dismantle/reassemble, heavy items, extra movers, no-lift surcharge, waste removal, storage).
- Each pack has Arabic and English names, standard descriptions and keywords. In *Catalogue* you can load any pack without prices ("starter packs") and set your own prices.
- Moving and household enquiries trigger their own follow-up questions (from/to, floor and lift, packing, dismantling, access, who supplies the fitting).

## Look and fonts
The interface and the PDF use the Inter typeface (bundled in `quoteflow/static/fonts`) for Latin text and Noto Sans Arabic for Arabic. The Dockerfile installs Noto fonts, so Arabic looks right on the server. The app can be installed on a phone or computer from the browser menu.

## Interactive quotation (customer link)
After you approve a quote, open **Share** and press **Create customer link**. The customer gets a mobile-friendly page in Arabic or English where they can:
- read the quote and see the validity countdown;
- switch on **optional add-ons** (items you ticked *Optional add-on* in the editor). The total is recalculated by the server, never in the browser;
- **accept** (typing their name and ticking a box), **decline** (with an optional reason), ask a question on WhatsApp, or download the PDF (with their chosen add-ons).

You see when they opened it and how they answered (also in the quote list). If email is set up (SMTP_*), the owner also gets an email when the customer accepts or declines. The link is random and unguessable, works only for approved quotes, and stops working if you turn it off or edit the quote. Responses are final: a customer cannot flip a decision after the fact. All customer actions are written to the activity log.
