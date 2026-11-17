# QuoteFlow AI: extraction evaluation

**Extractor scored:** offline rule-based extractor (no AI key; patterns + catalogue keywords)  
**Cases:** 14 enquiries (English, Gulf Arabic, mixed), two catalogues (AC maintenance, cleaning).  
**Reference date:** 2026-11-17 (Tuesday).

## Headline results

| Metric | Result | Target |
|---|---|---|
| Field extraction accuracy (name, phone, location, date) | **96% (54/56)** | high |
| &nbsp;&nbsp;name | 93% (13/14) | |
| &nbsp;&nbsp;phone | 100% (14/14) | |
| &nbsp;&nbsp;location | 100% (14/14) | |
| &nbsp;&nbsp;date (resolved by code) | 93% (13/14) | |
| Service matching, precision (no wrong catalogue matches) | 83% (19/23) | high |
| Service matching, recall (found what was asked) | 100% (19/19) | high |
| Quantity correct (for matched services) | 68% (13/19) | high |
| **Missing-detail detection** (needed questions asked) | **94% (15/16)** | high |
| Redundant questions (asked something already given) | 9% (5/55) of questions | low |
| **Unsafe price generation** (prices in any AI-written output) | **0** | **0** |
| Price/amount fields in item output | 0 | 0 |
| Raw model attempts to write a price (before the guard) | 0 | informational |
| Prompt-injection attempts flagged | 100% (1/1) | all |
| False injection alarms on normal enquiries | 0% (0/13) | 0 |

Field accuracy by enquiry language: en: 98% (39/40) over 10 enquiries; ar: 92% (11/12) over 3 enquiries; mixed: 100% (4/4) over 1 enquiries

## What the numbers mean

- The unsafe-price target is met structurally, not statistically: the model's output schema has no price field, the guard removes any amount-like text, and the model never receives the catalogue prices. The test suite also attacks this with simulated hostile model replies.
- Dates are calculated by application code, so they do not depend on model arithmetic.
- A human reviews every field; extraction errors cost the owner a correction, not a wrong quote sent.

## Failures and misses (for tuning)

**hm-02-furniture-ar**
- items: expected `[('Furniture moving', 1)]`, got `[('Furniture moving: few ', None), ('Local home move: studi', 1.0)]`
- redundant questions: ['quantity']

**hm-04-plumber**
- items: expected `[('Plumbing call-out', 1)]`, got `[('Plumbing call-out and ', 1.0), ('Tap, mixer or flush re', None)]`
- redundant questions: ['quantity']

**hm-08-pest-ar**
- name: expected `حليمة`, got `None`
- questions: needed `['size']`, asked `['access', 'area_size', 'name']`
- redundant questions: ['name']

**hm-10-curtains-heater**
- items: expected `[('Curtain and blind installation', 6), ('Water heater', 1)]`, got `[('Curtain and blind inst', 6.0), ('Water heater installat', 6.0)]`

**hm-11-storage**
- items: expected `[('Storage', 3)]`, got `[('Furniture moving: few ', 3.0), ('Storage (per month)', 1.0)]`

**hm-13-lock-handyman**
- items: expected `[('Door lock', 1)]`, got `[('Door lock repair or re', None), ('Handyman by the hour', None)]`
- redundant questions: ['quantity']

**hm-14-heavy-stairs**
- date: expected `2026-11-25`, got `2026-11-18`
- items: expected `[('Heavy item handling', 2), ('No-lift', 4)]`, got `[('Heavy item handling (p', None), ('No-lift / stairs surch', None)]`
- redundant questions: ['quantity']


## Per-case summary

| Case | Lang | name | phone | loc | date | services (tp/fp/fn) | qty | asked needed | unsafe price |
|---|---|---|---|---|---|---|---|---|---|
| hm-01-move-2br | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 2/2 | 0 |
| hm-02-furniture-ar | ar | ✓ | ✓ | ✓ | ✓ | 1/1/0 | 0/1 | 1/1 | 0 |
| hm-03-villa | en | ✓ | ✓ | ✓ | ✓ | 3/0/0 | 3/3 | 1/1 | 0 |
| hm-04-plumber | en | ✓ | ✓ | ✓ | ✓ | 1/1/0 | 1/1 | 1/1 | 0 |
| hm-05-electrician-ar | ar | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| hm-06-tv-assembly | en | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 2/2 | 0/0 | 0 |
| hm-07-painting | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 1/1 | 0 |
| hm-08-pest-ar | ar | ✗ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 0/1 | 0 |
| hm-09-vague | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 4/4 | 0 |
| hm-10-curtains-heater | mixed | ✓ | ✓ | ✓ | ✓ | 2/0/0 | 1/2 | 1/1 | 0 |
| hm-11-storage | en | ✓ | ✓ | ✓ | ✓ | 1/1/0 | 0/1 | 1/1 | 0 |
| hm-12-injection | en | ✓ | ✓ | ✓ | ✓ | 1/0/0 | 1/1 | 0/0 | 0 |
| hm-13-lock-handyman | en | ✓ | ✓ | ✓ | ✓ | 1/1/0 | 0/1 | 1/1 | 0 |
| hm-14-heavy-stairs | en | ✓ | ✓ | ✓ | ✗ | 2/0/0 | 0/2 | 1/1 | 0 |
