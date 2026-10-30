"""Regression tests for credit-card statement safety. No private statements in source control."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from types import SimpleNamespace
from unittest.mock import patch
from backend import parse_card

def fake_pages(texts):
    return [SimpleNamespace(lines=[SimpleNamespace(text=line) for line in text.splitlines()]) for text in texts]

def test_supercard_repayments_refunds_wrapped_fuel_and_illustration_excluded():
    header = """Utkarsh Small Finance Bank
super.money
xxxx xxxx xxxx 0103
Total Limit: ₹9,000.00
15th Sep, 2026 ₹202.18 ₹10.11
Transactions and EMIs ₹202.18
Repayments ₹150.00
Transaction Reversals and Refunds ₹30.00"""
    transactions = """Utkarsh Small Finance Bank
All Transactions
Date Mode Description Amount (INR)
1st Sep, 2026 Payment - ₹150.00
2nd Sep, 2026 UPI Shop ₹71.00
3rd Sep, 2026 UPI Shop - ₹30.00
CITY FUELS ₹100.00
4th Sep, 2026 UPI
Fuel Surcharge ₹1.18
5th Sep, 2026 UPI Bakery ₹30.00"""
    illustration = """May 10, 2023 Purchase ₹20,000.00
Payment Due Date ₹1,000.00"""
    pages=fake_pages([header,transactions,illustration])
    with patch.object(parse_card,"group_lines",side_effect=lambda page,i:page.lines):
        info=parse_card.detect_card(pages)
        rows,warnings,meta=parse_card.parse_card(pages)
    assert info["last4"]=="0103"
    assert info["limit_minor"]==900000
    assert len(rows)==6
    assert sum(r["amount_minor"] for r in rows if r["direction"]=="debit")==20218
    assert sum(r["amount_minor"] for r in rows if "Credit card repayment" in r["flags"])==15000
    assert sum(r["amount_minor"] for r in rows if "Credit card refund" in r["flags"])==3000
    assert all(r["date"].startswith("2026-") for r in rows)
    assert not warnings

def test_unsupported_is_not_silently_treated_as_supercard():
    pages=fake_pages(["Example Bank", "All Transactions\n1st Sep, 2026 Payment - ₹100.00"])
    with patch.object(parse_card,"group_lines",side_effect=lambda page,i:page.lines):
        assert parse_card.detect_card(pages) is None

if __name__ == "__main__":
    test_supercard_repayments_refunds_wrapped_fuel_and_illustration_excluded()
    test_unsupported_is_not_silently_treated_as_supercard()
    print("Credit card parser checks passed")
