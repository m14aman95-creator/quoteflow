# QuoteFlow AI (MVP)

Turn a messy WhatsApp or email enquiry into a reviewed, priced, bilingual (Arabic/English) quotation.

**AI writes language. Application code calculates money. A human always approves.**

## Try it in 2 minutes (no AI key needed)

```bash
pip install -r requirements.txt
python seed.py --username yourname --password 'YourStrongPassword'   # one account with every service
python run.py             # open http://localhost:5000
```

Create your owner account with your own username and password. It is a normal business account that offers all four starter service packs (AC, cleaning, household, furniture moving). There is no built-in or default login:

```bash
python seed.py --username yourname --password 'YourStrongPassword'
```

Add `--sample` to also load a few past quotations so the dashboard is not empty. Log in with that **username** and password; you can change both later under your name at the top right (*Account*). Anyone can also create their own business account at `/register`.

Without an API key the app uses a built-in rule-based reader (no AI key connected). It handles common requests in English, Gulf Arabic and mixed text. Add a key for full accuracy.

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

Create the first owner with `python seed.py --username ... --password ...` once inside the container, or just use `/register`.

## Project layout

```
quoteflow/            app package (Flask)
  money.py            calculation engine (the only place money is computed)
  ai/                 schema, price guard, offline reader, Claude adapter, pipeline
  docs.py             bilingual quotation HTML, PDF (headless Chrome), WhatsApp text
  views_*.py          routes: auth, company/settings, catalogue, enquiries/quotes
  templates/ static/  mobile-first UI
tests/                178 tests
eval/                 evaluation sets and reports
seed.py seed_quotes.py  first owner account and optional sample quotations
```

## Catalogue keyword tips

In each service's keywords: `clean+ac` means both words close together; `~not cooling` is a weak symptom word used only if nothing else matches; `!move out` means never match when that phrase appears.

## Free hosting on Render
1. Put the project in a GitHub repository (the folder contents, not the zip).
2. On render.com: **New > Blueprint**, pick the repository. `render.yaml` sets everything up.
3. Optional: paste `ANTHROPIC_API_KEY` in the service's Environment tab.
4. Render asks for `ADMIN_USERNAME` and `ADMIN_PASSWORD`: type the username and password you want. Open the `.onrender.com` link and log in with them. If both are set, that owner account is re-created on every start (the free disk resets); if you leave them out, nothing is created and you sign up at `/register`. Set `QF_SAMPLE_DATA=1` only if you want sample quotations.
The free plan sleeps after 15 minutes idle and its disk resets, so data you add is lost. Use it for trials only.

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

## Customer portal (customers submit and track requests)

Each business has its own portal at `/c/<business-address>/`, for example `https://your-app.onrender.com/c/al-noor-home-services/`. Find the link, a printable QR code and the address setting under **Requests > Portal & QR code**.

**What customers do:** create an account with a mobile number (email optional) and a password, send a request (service, details, location, preferred date), and track it: status, the quotation once you approve it, the scheduled date, and messages. The portal is bilingual (English/Arabic, right-to-left).

**What you do:** new requests appear in **Requests** (with a badge). Open one, review the AI's draft, price it and approve it as usual. Approving publishes the quotation to the customer's portal and emails them if they gave an address and SMTP is set up. The customer accepts or declines on the interactive quote page; you then schedule the job and mark it in progress and completed, and the customer sees each step.

Rules that stay in force: the AI never sets prices, customer text is untrusted, nothing reaches the customer until you approve the quotation, and a customer sees only their own requests. Limits: 10 requests per customer per day; login attempts are throttled per account and per address.

**Verification:** when outgoing email (SMTP) is set up, a new customer must confirm their email with a 6-digit code before they can send requests (the code expires after 15 minutes, allows 5 wrong tries and is stored only as a hash). Updates are emailed only to confirmed addresses, and an unconfirmed address can neither block nor steal the real owner's. If SMTP is not set up, verification is off and the Portal page says so.

Not built yet: SMS verification of the mobile number (needs a paid SMS provider, so the mobile number is not confirmed), photo uploads, self-service password reset by email (the owner can set a temporary password from the request page), WhatsApp Business API messages.


## Email on Render (read this if sign-up codes do not arrive)
- Render's **free** web services block SMTP ports (25/465/587), so Gmail/SMTP cannot work there. Use the **Brevo email API** instead:
  1. Create a free Brevo account, verify a sender address, create an API key (SMTP & API > API keys).
  2. In Render > Environment add `BREVO_API_KEY` and `MAIL_FROM` (the verified sender).
  3. Open **Portal** in the app and press **Send test email**. It tells you plainly if something is wrong.
- Gmail SMTP (paid Render plan or your own server): the App Password is 16 letters with **no spaces**.
- If email is not working yet, untick "Require customers to confirm their email" on the Portal page so sign-up still works.
- Any unexpected error now shows a short reference code; the full detail is in the Render log under that code.

## Business or customer
Signed-out visitors see **I run a business / I am a customer** tabs (`/start`). Customers find their provider by short name or link (`/find`) and are sent straight to it when only one business has its portal on.
