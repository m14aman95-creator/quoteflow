# Status: done, deferred, next steps

## Done (all 11 scope items)
1. Auth and company profile: logo, CR, VAT status/number/rate with confirmation, BHD, default terms (EN/AR), validity, preferred language, retention.
2. Service catalogue: AR/EN names and descriptions, unit, optional price, tax treatment, keywords; starter packs load without prices.
3. Enquiry intake: paste WhatsApp/email/manual text.
4. AI extraction: strict-schema JSON (name, phone, location, service, quantities, dates, requirements, flags, questions); catalogue matching; Claude adapter plus offline reader.
5. Draft quotation: editable lines, AI-drafted bilingual descriptions, discount, per-item VAT, live totals.
6. Trust cues: Customer said / AI inferred / Uncertain / You approved.
7. Bilingual output with RTL, Gulf Arabic and code-switching handled in extraction.
8. Branded PDF (headless Chrome) and copy/share WhatsApp text (manual).
9. Customer and quote history, search, six statuses (Expired is computed from the validity date).
10. Quote counter per plan with enforced limits; billing stubbed.
11. Feedback prompt after approval (as-is / minor / major / unusable).
Plus: integer-fils money engine with unit tests, price guard, injection defences, tenant isolation, audit log, retention purge, 129 tests, evaluation sets, Dockerfile, README, demo script.

## Evaluation (offline reader; see eval/)
| Set | Fields | Service precision / recall | Quantities | Missing-detail questions | Unsafe prices |
|---|---|---|---|---|---|
| First run, 20 cases, before tuning | 90% | 68% / 88% | 76% | 96% | 0 |
| Same 20 cases after tuning (optimistic) | 100% | 100% / 100% | 100% | 93% | 0 |
| 12 held-out cases (fairer estimate) | 96% (94% before one bug fix) | 91% / 83% | 100% | 100% | 0 |
The real Claude model has NOT been scored: no API key or network was available in the build environment. Run `python eval/run_eval.py --provider claude` with a key.

## Known limits
- Claude adapter tested against simulated replies only, never against the live API.
- Offline reader misses some phrasings (e.g. "فيلتي", recurring schedules read as a one-off date).
- Arabic UI text covers navigation and main labels only; quote output is fully bilingual.
- PDF uses system fonts (DejaVu here, Noto in Docker); no custom Arabic font bundled.
- Free plan shows the logo (proposal reserves custom logo for Starter+); only the footer branding differs.
- SQLite, single server; no password reset, email verification, rate limiting, or MFA.

## Deferred (by design or time)
WhatsApp Business API, accounting/ERP integration, AI pricing, autonomous sending, payments, multi-user roles UI (data model is role-ready), email sending, customer portal/e-signature, analytics dashboard, quote versioning.

## Recommended next steps
1. Add an API key, run the evaluation with Claude, and add 30+ real anonymised enquiries from pilot businesses (especially voice-note transcripts and Gulf dialect).
2. Before real customers: password reset, email verification, login rate limiting, HTTPS-only cookies, backups, Postgres, and a Bahrain PDPL legal review of AI vendor data transfers.
3. Pilot with 5 to 10 businesses; track time-to-first-quote and the feedback ratings.
4. Then: multi-user approvals (Professional/Business), reminders for Follow-up quotes, vertical prompts (AC, cleaning).
