import pytest
from price_tracker.scrapers.base import normalize_price


# ---------------------------------------------------------------------------
# Happy-path cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        # Plain integers
        ("249", 249.0),
        ("0", 0.0),
        # US/UK format: comma=thousands, dot=decimal
        ("1,299.99", 1299.99),
        ("$1,299.99", 1299.99),
        ("1,000.00", 1000.0),
        # European format: dot=thousands, comma=decimal
        ("1.299,99 €", 1299.99),
        ("1.299,99", 1299.99),
        ("249,99", 249.99),
        # European thousands, no decimal
        ("1.299", 1299.0),
        ("2.000", 2000.0),
        # Dot decimal, no thousands
        ("249.99", 249.99),
        ("0.99", 0.99),
        # Currency symbols and whitespace stripped
        ("€ 249,99", 249.99),
        (" $1,299.00 ", 1299.0),
        ("£999.99", 999.99),
        # Large numbers with both separators
        ("10.299,99", 10299.99),
        ("10,299.99", 10299.99),
    ],
)
def test_normalize_price_happy(raw: str, expected: float) -> None:
    assert normalize_price(raw) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Edge cases that should raise ValueError
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "N/A",
        "—",
        "price unavailable",
    ],
)
def test_normalize_price_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_price(raw)


# ---------------------------------------------------------------------------
# Ambiguous single-separator cases
# ---------------------------------------------------------------------------

def test_european_decimal_comma_no_thousands() -> None:
    # "249,99" → comma is decimal separator (only 2 digits after)
    assert normalize_price("249,99") == pytest.approx(249.99)


def test_us_thousands_comma() -> None:
    # "1,299" → comma is thousands (3 digits after)
    assert normalize_price("1,299") == pytest.approx(1299.0)


def test_european_thousands_dot() -> None:
    # "1.299" → dot is thousands (3 digits after)
    assert normalize_price("1.299") == pytest.approx(1299.0)


def test_us_decimal_dot() -> None:
    # "1.99" → dot is decimal (2 digits after)
    assert normalize_price("1.99") == pytest.approx(1.99)
