import random
import pytest
from quoteflow.money import (compute_quote, LineInput, line_total, parse_bhd, parse_quantity, parse_percent_bp,
                             format_bhd, format_quantity, round_div, MoneyError, _allocate)


def L(q, p, tax="standard"):
    return LineInput(quantity_milli=q, unit_price_fils=p, tax_class=tax)


# ---- parsing / formatting ----
def test_parse_bhd():
    assert parse_bhd("12") == 12000
    assert parse_bhd("12.5") == 12500
    assert parse_bhd("0.005") == 5
    assert parse_bhd("1,250.750") == 1250750
    assert parse_bhd("٢٫٥٠٠") == 2500            # Arabic-Indic digits
    assert parse_bhd("BHD 7.500") == 7500


@pytest.mark.parametrize("bad", ["", "abc", "-1", "1.2345", "1.0005"])
def test_parse_bhd_rejects(bad):
    with pytest.raises(MoneyError):
        parse_bhd(bad)


def test_parse_quantity_and_percent():
    assert parse_quantity("3") == 3000 and parse_quantity("2.5") == 2500 and parse_quantity("٣") == 3000
    for bad in ("0", "-2", "x", "1.0001"):
        with pytest.raises(MoneyError):
            parse_quantity(bad)
    assert parse_percent_bp("10") == 1000 and parse_percent_bp("12.5%") == 1250
    with pytest.raises(MoneyError):
        parse_percent_bp("101")


def test_format():
    assert format_bhd(0) == "0.000" and format_bhd(12500) == "12.500" and format_bhd(5) == "0.005"
    assert format_bhd(None) == "—"
    assert format_quantity(3000) == "3" and format_quantity(2500) == "2.5" and format_quantity(1250) == "1.25"


def test_no_floats_accepted():
    with pytest.raises(MoneyError):
        line_total(1000, 12.5)
    with pytest.raises(MoneyError):
        compute_quote([L(1000, 1000)], "percent", 10.0)
    with pytest.raises(MoneyError):
        compute_quote([L(1000.0, 1000)])
    with pytest.raises(MoneyError):
        compute_quote([L(1000, 1000)], vat_rate_bp=10.0)


def test_round_half_up():
    assert round_div(5, 2) == 3 and round_div(4, 2) == 2 and round_div(1, 3) == 0 and round_div(3, 2) == 2


# ---- line totals ----
def test_line_total_rounding():
    assert line_total(3000, 12500) == 37500          # 3 x 12.500
    assert line_total(2500, 3333) == 8333            # 8332.5 -> half up
    assert line_total(1, 1) == 0                     # 0.001 x 0.001 fils rounds to 0
    assert line_total(500, 1) == 1                   # 0.5 fils rounds half up


# ---- quote totals ----
def test_simple_vat_registered():
    r = compute_quote([L(3000, 12500), L(1000, 5000)], vat_registered=True, vat_rate_bp=1000)
    assert r.subtotal_fils == 42500
    assert r.vat_fils == 4250
    assert r.total_fils == 46750
    assert r.complete


def test_not_vat_registered_no_vat():
    r = compute_quote([L(3000, 12500)], vat_registered=False)
    assert r.vat_fils == 0 and r.total_fils == 37500 and not r.vat_applied


def test_zero_rated_and_exempt_lines():
    r = compute_quote([L(1000, 10000, "standard"), L(1000, 20000, "zero"), L(1000, 30000, "exempt")],
                      vat_registered=True, vat_rate_bp=1000)
    assert r.taxable_fils == 10000 and r.zero_rated_fils == 20000 and r.exempt_fils == 30000
    assert r.vat_fils == 1000 and r.total_fils == 61000


def test_percent_discount_reduces_vat_base():
    r = compute_quote([L(1000, 100000)], "percent", 1000, True, 1000)   # 10% off 100.000
    assert r.discount_fils == 10000
    assert r.vat_fils == 9000              # 10% of 90.000
    assert r.total_fils == 99000


def test_fixed_discount_and_cap():
    r = compute_quote([L(1000, 50000)], "fixed", 5000, True, 1000)
    assert r.discount_fils == 5000 and r.vat_fils == 4500 and r.total_fils == 49500
    r = compute_quote([L(1000, 50000)], "fixed", 999999, True, 1000)
    assert r.discount_fils == 50000 and r.discount_capped and r.total_fils == 0 and r.warnings


def test_discount_shared_across_mixed_tax_classes():
    # 100 standard + 100 zero-rated, fixed discount 20 -> 10 off each; VAT only on 90
    r = compute_quote([L(1000, 100000, "standard"), L(1000, 100000, "zero")], "fixed", 20000, True, 1000)
    assert [ln.discount_share_fils for ln in r.lines] == [10000, 10000]
    assert r.taxable_fils == 90000 and r.vat_fils == 9000 and r.total_fils == 189000


def test_custom_vat_rate_and_unpriced_lines():
    r = compute_quote([L(1000, 10000), L(2000, None)], vat_registered=True, vat_rate_bp=500)
    assert r.vat_fils == 500 and r.unpriced_lines == 1 and not r.complete and r.warnings


def test_empty_quote():
    r = compute_quote([], vat_registered=True)
    assert r.total_fils == 0 and r.vat_fils == 0


def test_vat_rounding_once_on_total():
    # 3 lines of 0.333 BHD: per-line VAT rounding would give 3 x 33 = 99; total-level gives 100
    r = compute_quote([L(1000, 333)] * 3, vat_registered=True, vat_rate_bp=1000)
    assert r.subtotal_fils == 999 and r.vat_fils == 100 and r.total_fils == 1099


def test_invalid_inputs():
    with pytest.raises(MoneyError):
        compute_quote([L(1000, 100, "weird")])
    with pytest.raises(MoneyError):
        compute_quote([L(-1, 100)])
    with pytest.raises(MoneyError):
        compute_quote([L(1000, 100)], "percent", 10001)
    with pytest.raises(MoneyError):
        compute_quote([L(1000, 100)], vat_rate_bp=20000)
    with pytest.raises(MoneyError):
        compute_quote([L(1000, 100)], "bogus", 1)


def test_allocate_sums_exactly():
    assert sum(_allocate(100, [1, 1, 1])) == 100
    assert _allocate(100, [1, 1, 1]) == [34, 33, 33]
    assert _allocate(0, [5, 5]) == [0, 0] and _allocate(10, [0, 0]) == [0, 0]


def test_property_totals_always_consistent():
    rnd = random.Random(42)
    for _ in range(2000):
        n = rnd.randint(0, 6)
        lines = [L(rnd.randint(1, 20000), rnd.choice([None, rnd.randint(0, 900000)]),
                   rnd.choice(["standard", "zero", "exempt"])) for _ in range(n)]
        dtype = rnd.choice(["none", "percent", "fixed"])
        dval = rnd.randint(0, 10000) if dtype == "percent" else rnd.randint(0, 500000)
        r = compute_quote(lines, dtype, dval, rnd.choice([True, False]), rnd.choice([0, 500, 1000, 1500]))
        assert r.total_fils == r.subtotal_fils - r.discount_fils + r.vat_fils
        assert sum(x.line_total_fils for x in r.lines) == r.subtotal_fils
        assert sum(x.discount_share_fils for x in r.lines) == r.discount_fils
        assert r.discount_fils <= r.subtotal_fils and r.total_fils >= 0
        assert all(isinstance(v, int) for v in (r.subtotal_fils, r.discount_fils, r.vat_fils, r.total_fils))
        if not r.vat_applied:
            assert r.vat_fils == 0
