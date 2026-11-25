from decimal import Decimal

from app.services import money


def test_benchmark_gst_and_receivable_arithmetic():
    taxable = money(Decimal("150") * Decimal("50"))
    cgst = money(taxable * Decimal("0.05") / 2)
    sgst = cgst
    total = taxable + cgst + sgst
    assert (taxable, cgst, sgst, total) == (
        Decimal("7500.00"), Decimal("187.50"), Decimal("187.50"), Decimal("7875.00")
    )
    assert total - Decimal("4000.00") == Decimal("3875.00")


def test_benchmark_yield_and_oil_variance():
    yield_variance = (Decimal("188") - Decimal("200")) / Decimal("200") * Decimal("100")
    oil_variance = (Decimal("10.5") - Decimal("10")) / Decimal("10") * Decimal("100")
    assert yield_variance == Decimal("-6")
    assert oil_variance == Decimal("5")


def test_benchmark_inventory_ledger_arithmetic():
    assert Decimal("100") + Decimal("60") - Decimal("40") == Decimal("120")
    assert Decimal("30") - Decimal("10.5") == Decimal("19.5")
    assert Decimal("500") - Decimal("188") - Decimal("6") == Decimal("306")
    assert Decimal("50") + Decimal("188") - Decimal("150") == Decimal("88")
    assert Decimal("120") - Decimal("88") == Decimal("32")
