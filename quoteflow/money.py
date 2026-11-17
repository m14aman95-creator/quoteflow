"""Deterministic calculation engine. THE ONLY PLACE MONEY IS COMPUTED.

Rules
- All amounts are integer fils (1 BHD = 1000 fils). No floats anywhere: float input is rejected.
- Quantities are integer thousandths (quantity_milli), so 2.5 m2 = 2500.
- Rates (VAT, % discount) are integer basis points (10% = 1000).
- Rounding is half-up to the nearest fil, applied once per step as documented below.
- The AI never touches this module's inputs or outputs.

Calculation order
 1. line_total      = round(quantity x unit_price) per line
 2. subtotal        = sum of line totals
 3. discount        = percent of subtotal (rounded) or fixed amount (capped at subtotal)
 4. discount is shared across lines in proportion to their value (largest-remainder, sums exactly)
 5. VAT             = rate x (sum of discounted STANDARD-rated line values), rounded once.
                      Zero-rated and exempt lines add no VAT. If the company is not VAT registered, VAT is 0.
 6. total           = subtotal - discount + VAT
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional, List

TAX_CLASSES = ("standard", "zero", "exempt")
FILS_PER_BHD = 1000


class MoneyError(ValueError):
    pass


def _require_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise MoneyError(f"{name} must be an integer (got {type(value).__name__}); floats are not allowed")
    return value


def round_div(numerator: int, denominator: int) -> int:
    """Integer division rounded half-up (numerator >= 0, denominator > 0)."""
    if denominator <= 0 or numerator < 0:
        raise MoneyError("round_div expects non-negative numerator and positive denominator")
    return (2 * numerator + denominator) // (2 * denominator)


# ---------- parsing / formatting (text <-> integers) ----------

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٫٬،", "0123456789.,,")


def _clean_number(text: str) -> str:
    s = str(text).strip().translate(_ARABIC_DIGITS).replace(",", "").replace(" ", "")
    for cur in ("BHD", "bhd", "BD", "bd", "د.ب"):
        s = s.replace(cur, "")
    return s.strip()


def parse_bhd(text) -> int:
    """'12.5' -> 12500 fils. Accepts Arabic-Indic digits. More than 3 decimals is an error (no silent rounding)."""
    s = _clean_number(text)
    if not s:
        raise MoneyError("Amount is empty")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise MoneyError(f"'{text}' is not a valid amount")
    if d < 0:
        raise MoneyError("Amount cannot be negative")
    fils = d * FILS_PER_BHD
    if fils != fils.to_integral_value():
        raise MoneyError("BHD amounts have at most 3 decimal places")
    return int(fils)


def parse_quantity(text) -> int:
    """'2.5' -> 2500 (thousandths). Must be > 0, max 3 decimals."""
    s = _clean_number(text)
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise MoneyError(f"'{text}' is not a valid quantity")
    if d <= 0:
        raise MoneyError("Quantity must be greater than zero")
    m = d * 1000
    if m != m.to_integral_value():
        raise MoneyError("Quantity has at most 3 decimal places")
    if m > 10**9:
        raise MoneyError("Quantity is too large")
    return int(m)


def parse_percent_bp(text) -> int:
    """'12.5' (percent) -> 1250 basis points, 0..100%."""
    s = _clean_number(text).rstrip("%")
    try:
        d = Decimal(s or "0")
    except InvalidOperation:
        raise MoneyError(f"'{text}' is not a valid percentage")
    bp = d * 100
    if bp != bp.to_integral_value() or bp < 0 or bp > 10000:
        raise MoneyError("Percentage must be between 0 and 100 with at most 2 decimals")
    return int(bp)


def format_bhd(fils: Optional[int]) -> str:
    if fils is None:
        return "—"
    _require_int(fils, "fils")
    sign = "-" if fils < 0 else ""
    fils = abs(fils)
    return f"{sign}{fils // 1000}.{fils % 1000:03d}"


def format_quantity(milli: int) -> str:
    _require_int(milli, "quantity_milli")
    whole, frac = divmod(milli, 1000)
    return str(whole) if frac == 0 else f"{whole}.{frac:03d}".rstrip("0")


# ---------- the engine ----------

@dataclass
class LineInput:
    quantity_milli: int
    unit_price_fils: Optional[int]          # None = not priced yet
    tax_class: str = "standard"


@dataclass
class LineResult:
    line_total_fils: int
    discount_share_fils: int
    net_fils: int
    priced: bool


@dataclass
class QuoteTotals:
    lines: List[LineResult]
    subtotal_fils: int
    discount_fils: int
    taxable_fils: int                       # discounted value of standard-rated lines
    zero_rated_fils: int
    exempt_fils: int
    vat_fils: int
    total_fils: int
    vat_applied: bool
    vat_rate_bp: int
    unpriced_lines: int
    discount_capped: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.unpriced_lines == 0

    def as_dict(self):
        return {k: getattr(self, k) for k in (
            "subtotal_fils", "discount_fils", "taxable_fils", "zero_rated_fils", "exempt_fils",
            "vat_fils", "total_fils", "vat_applied", "vat_rate_bp", "unpriced_lines")}


def line_total(quantity_milli: int, unit_price_fils: int) -> int:
    _require_int(quantity_milli, "quantity_milli")
    _require_int(unit_price_fils, "unit_price_fils")
    if quantity_milli < 0 or unit_price_fils < 0:
        raise MoneyError("Quantity and price cannot be negative")
    return round_div(quantity_milli * unit_price_fils, 1000)


def _allocate(total: int, weights: List[int]) -> List[int]:
    """Split `total` fils across lines in proportion to `weights`, exactly (largest remainder)."""
    wsum = sum(weights)
    if total == 0 or wsum == 0:
        return [0] * len(weights)
    base = [total * w // wsum for w in weights]
    rema = [(total * w) % wsum for w in weights]
    left = total - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-rema[i], i))
    for i in order[:left]:
        base[i] += 1
    return base


def compute_quote(lines: List[LineInput], discount_type: str = "none", discount_value: int = 0,
                  vat_registered: bool = False, vat_rate_bp: int = 1000) -> QuoteTotals:
    _require_int(discount_value, "discount_value")
    _require_int(vat_rate_bp, "vat_rate_bp")
    if discount_type not in ("none", "percent", "fixed"):
        raise MoneyError("Unknown discount type")
    if discount_value < 0:
        raise MoneyError("Discount cannot be negative")
    if not 0 <= vat_rate_bp <= 10000:
        raise MoneyError("VAT rate must be between 0% and 100%")

    totals, priced_flags = [], []
    for ln in lines:
        if ln.tax_class not in TAX_CLASSES:
            raise MoneyError(f"Unknown tax class '{ln.tax_class}'")
        if ln.unit_price_fils is None:
            _require_int(ln.quantity_milli, "quantity_milli")
            totals.append(0)
            priced_flags.append(False)
        else:
            totals.append(line_total(ln.quantity_milli, ln.unit_price_fils))
            priced_flags.append(True)

    subtotal = sum(totals)
    warnings: List[str] = []
    capped = False
    if discount_type == "none" or discount_value == 0:
        discount = 0
    elif discount_type == "percent":
        if discount_value > 10000:
            raise MoneyError("Percentage discount cannot exceed 100%")
        discount = round_div(subtotal * discount_value, 10000)
    else:
        discount = discount_value
        if discount > subtotal:
            discount, capped = subtotal, True
            warnings.append("Discount was larger than the subtotal and has been capped.")

    shares = _allocate(discount, totals)
    nets = [t - s for t, s in zip(totals, shares)]

    taxable = sum(n for n, ln in zip(nets, lines) if ln.tax_class == "standard")
    zero = sum(n for n, ln in zip(nets, lines) if ln.tax_class == "zero")
    exempt = sum(n for n, ln in zip(nets, lines) if ln.tax_class == "exempt")

    vat = round_div(taxable * vat_rate_bp, 10000) if vat_registered else 0
    total = subtotal - discount + vat
    unpriced = priced_flags.count(False)
    if unpriced:
        warnings.append(f"{unpriced} item(s) have no price yet; totals are incomplete.")

    return QuoteTotals(
        lines=[LineResult(t, s, n, p) for t, s, n, p in zip(totals, shares, nets, priced_flags)],
        subtotal_fils=subtotal, discount_fils=discount, taxable_fils=taxable if vat_registered else 0,
        zero_rated_fils=zero if vat_registered else 0, exempt_fils=exempt if vat_registered else 0,
        vat_fils=vat, total_fils=total, vat_applied=bool(vat_registered), vat_rate_bp=vat_rate_bp,
        unpriced_lines=unpriced, discount_capped=capped, warnings=warnings)
