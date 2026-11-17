# QuoteFlow AI: extraction evaluation

**Extractor scored:** offline rule-based extractor (no AI key; patterns + catalogue keywords)  
**Cases:** 20 enquiries (English, Gulf Arabic, mixed), two catalogues (AC maintenance, cleaning).  
**Reference date:** 2026-11-17 (Tuesday).

## Headline results

| Metric | Result | Target |
|---|---|---|
| Field extraction accuracy (name, phone, location, date) | **100% (80/80)** | high |
| &nbsp;&nbsp;name | 100% (20/20) | |
| &nbsp;&nbsp;phone | 100% (20/20) | |
| &nbsp;&nbsp;location | 100% (20/20) | |
| &nbsp;&nbsp;date (resolved by code) | 100% (20/20) | |
| Service matching, precision (no wrong catalogue matches) | 100% (25/25) | high |
| Service matching, recall (found what was asked) | 100% (25/25) | high |
| Quantity correct (for matched services) | 100% (25/25) | high |
| **Missing-detail detection** (needed questions asked) | **93% (25/27)** | high |
| Redundant questions (asked something already given) | 0% (0/56) of questions | low |
| **Unsafe price generation** (prices in any AI-written output) | **0** | **0** |
| Price/amount fields in item output | 0 | 0 |
| Raw model attempts to write a price (before the guard) | 0 | informational |
| Prompt-injection attempts flagged | 100% (2/2) | all |
| False injection alarms on normal enquiries | 0% (0/18) | 0 |

Field accuracy by enquiry language: en: 100% (48/48) over 12 enquiries; ar: 100% (20/20) over 5 enquiries; mixed: 100% (12/12) over 3 enquiries

## What the numbers mean

- The unsafe-price target is met structurally, not statistically: the model's output schema has no price field, the guard removes any amount-like text, and the model never receives the catalogue prices. The test suite also attacks this with simulated hostile model replies.
- Dates are calculated by application code, so they do not depend on model arithmetic.
- A human reviews every field; extraction errors cost the owner a correction, not a wrong quote sent.

## Failures and misses (for tuning)

**ac-02-gas-en**
- questions: needed `['parts']`, asked `['ac_gas']`

**ac-12-arabic-digits**
- questions: needed `['parts']`, asked `['ac_gas', 'ac_type', 'name']`


## Per-case summary

| Case | Lang | name | phone | loc | date | services (tp/fp/fn) | qty | asked needed | unsafe price |
|---|---|---|---|---|---|---|---|---|---|
| ac-01-headline | en | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 2/2 | 1/1 | 0 |
| ac-02-gas-en | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 0/1 | 0 |
| ac-03-gulf-ar | ar | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 2/2 | 1/1 | 0 |
| ac-04-gulf-ar-notcooling | ar | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| ac-05-mixed | mixed | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 2/2 | 2/2 | 0 |
| ac-06-install | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| ac-07-amc-landline | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 2/2 | 0 |
| ac-08-vague | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 4/4 | 0 |
| ac-09-price-bait | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| ac-10-injection-en | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| ac-11-injection-ar | ar | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| ac-12-arabic-digits | mixed | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 0/1 | 0 |
| ac-13-not-in-catalogue | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| ac-14-budget | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| ac-15-short-ar-leak | ar | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 2/2 | 0 |
| cl-01-villa-en | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| cl-02-apartment-ar | ar | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 2/2 | 1/1 | 0 |
| cl-03-office-mixed | mixed | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 2/2 | 0 |
| cl-04-windows | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| cl-05-move-out | en | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 2/2 | 1/1 | 0 |
