from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.vat import to_vat_inclusive


def D(value: str) -> Decimal:
    return Decimal(value)


def test_an_already_inclusive_amount_is_untouched():
    amount = D("24000")
    assert to_vat_inclusive(amount, vat_inclusive=True, vat_pct=D("16")) == amount


def test_an_exclusive_amount_is_grossed_up():
    assert to_vat_inclusive(D("20000"), vat_inclusive=False, vat_pct=D("16")) == D("23200")


def test_normalisation_is_idempotent():
    once = to_vat_inclusive(D("20000"), vat_inclusive=False, vat_pct=D("16"))
    twice = to_vat_inclusive(once, vat_inclusive=True, vat_pct=D("16"))
    assert once == twice == D("23200")


def test_a_zero_rated_supplier_needs_no_special_case():
    assert to_vat_inclusive(D("5000"), vat_inclusive=False, vat_pct=D("0")) == D("5000")


def test_a_negative_vat_rate_is_refused_rather_than_applied():
    with pytest.raises(ValueError):
        to_vat_inclusive(D("5000"), vat_inclusive=False, vat_pct=D("-16"))


def test_normalisation_stays_decimal():
    result = to_vat_inclusive(D("13333.33"), vat_inclusive=False, vat_pct=D("16"))
    assert isinstance(result, Decimal)
    assert result == D("15466.6628")


@pytest.mark.parametrize("pct", ["0", "8", "16", "18.5"])
def test_the_rate_is_a_parameter_not_a_constant(pct):
    grossed = to_vat_inclusive(D("1000"), vat_inclusive=False, vat_pct=D(pct))
    assert grossed == D("1000") * (Decimal(1) + D(pct) / Decimal(100))
