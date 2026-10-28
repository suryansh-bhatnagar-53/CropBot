"""Offline tests for printed numbers (kg.extract.numbers)."""

import pytest

from kg.extract.numbers import parse_number, printed_numbers


@pytest.mark.parametrize("text, value", [
    ("1,00,000", 100000), ("10,00,000", 1000000), ("1,000", 1000), ("100,000", 100000),
    ("1.50", 1.5), ("16.67", 16.67), ("25", 25),
])
def test_parse_number(text, value):
    assert parse_number(text) == value


@pytest.mark.parametrize("text", ["1,0,00", "12,34", "1.5.0", "abc", ""])
def test_not_a_number(text):
    with pytest.raises(ValueError):
        parse_number(text)


def test_printed_numbers_in_a_phrase():
    assert printed_numbers("@ 1,00,000/ha each release") == [100000]
    assert printed_numbers("Fipronil 0.3% G 16.67 - 25 kg") == [0.3, 16.67, 25]
    assert printed_numbers("NPK @ 150:50:60 kg / ha") == [150, 50, 60]
