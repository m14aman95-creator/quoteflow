# QuoteFlow AI: extraction evaluation

**Extractor scored:** offline rule-based extractor (no AI key; patterns + catalogue keywords)  
**Cases:** 12 enquiries (English, Gulf Arabic, mixed), two catalogues (AC maintenance, cleaning).  
**Reference date:** 2026-11-17 (Tuesday).

## Headline results

| Metric | Result | Target |
|---|---|---|
| Field extraction accuracy (name, phone, location, date) | **94% (45/48)** | high |
| &nbsp;&nbsp;name | 83% (10/12) | |
| &nbsp;&nbsp;phone | 100% (12/12) | |
| &nbsp;&nbsp;location | 100% (12/12) | |
| &nbsp;&nbsp;date (resolved by code) | 92% (11/12) | |
| Service matching, precision (no wrong catalogue matches) | 91% (10/11) | high |
| Service matching, recall (found what was asked) | 83% (10/12) | high |
| Quantity correct (for matched services) | 100% (10/10) | high |
| **Missing-detail detection** (needed questions asked) | **100% (13/13)** | high |
| Redundant questions (asked something already given) | 3% (1/31) of questions | low |
| **Unsafe price generation** (prices in any AI-written output) | **0** | **0** |
| Price/amount fields in item output | 0 | 0 |
| Raw model attempts to write a price (before the guard) | 0 | informational |
| Prompt-injection attempts flagged | 100% (1/1) | all |
| False injection alarms on normal enquiries | 0% (0/11) | 0 |

Field accuracy by enquiry language: en: 94% (30/32) over 8 enquiries; ar: 92% (11/12) over 3 enquiries; mixed: 100% (4/4) over 1 enquiries

## What the numbers mean

- The unsafe-price target is met structurally, not statistically: the model's output schema has no price field, the guard removes any amount-like text, and the model never receives the catalogue prices. The test suite also attacks this with simulated hostile model replies.
- Dates are calculated by application code, so they do not depend on model arithmetic.
- A human reviews every field; extraction errors cost the owner a correction, not a wrong quote sent.

## Failures and misses (for tuning)

**h-01-noise-notcooling**
- name: expected `None`, got `Location Zinj`

**h-04-two-leaking-ar**
- name: expected `بوسلمان`, got `None`
- redundant questions: ['name']

**h-07-villa-ar-6rooms**
- items: expected `[('Villa deep cleaning', 1)]`, got `[]`

**h-08-hourly-house**
- date: expected `None`, got `2026-11-22`
- items: expected `[('Regular home cleaning', 1)]`, got `[('Cleaner by the hour', 4.0)]`


## Per-case summary

| Case | Lang | name | phone | loc | date | services (tp/fp/fn) | qty | asked needed | unsafe price |
|---|---|---|---|---|---|---|---|---|---|
| h-01-noise-notcooling | en | ✗ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| h-02-five-acs | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| h-03-install-ar | ar | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| h-04-two-leaking-ar | ar | ✗ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| h-05-gas-en | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| h-06-sofa-carpet | en | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 2/2 | 1/1 | 0 |
| h-07-villa-ar-6rooms | ar | ✓ | ✓ | ✓ | ✓ | 0/0/1 | 0/0 | 1/1 | 0 |
| h-08-hourly-house | en | ✓ | ✓ | ✓ | ✗ | 0/1/1 | 0/0 | 1/1 | 0 |
| h-09-move-in | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| h-10-chatter | en | ✓ | ✓ | ✓ | ✓ | 0/0/0 | 0/0 | 1/1 | 0 |
| h-11-injection-mixed | mixed | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| h-12-customer-price | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 2/2 | 0 |
