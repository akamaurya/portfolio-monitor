"""Offline checks for the Zerodha → Firefly sync maths and payloads."""

import pytest

from firefly_sync import plan, transaction, zerodha_total


def test_total_counts_t1_shares_mfs_and_cash():
    data = {
        "holdings": [{"quantity": 10, "t1_quantity": 2, "last_kite_price": 100.0}],
        "mf_holdings": [{"current_value": 5000.0}],
    }
    assert zerodha_total(data, cash=250.5) == 1200 + 5000 + 250.5


def test_plan_posts_normal_moves_and_skips_noise():
    assert plan(105_000, 100_000) == 5_000
    assert plan(96_000, 100_000) == -4_000
    assert plan(100_000.4, 100_000) == 0.0
    assert plan(0, 0) == 0.0


@pytest.mark.parametrize("total, balance", [
    (0, 50_000),       # Kite returned nothing
    (10_000, 0),       # money moved in but booked as spend, not a transfer
    (150_000, 100_000),
])
def test_plan_refuses_big_gaps(total, balance):
    with pytest.raises(RuntimeError):
        plan(total, balance)


def test_transaction_sides():
    gain = transaction(500, "7", "2026-10-10")["transactions"][0]
    assert (gain["type"], gain["amount"], gain["destination_id"], gain["source_name"]) == \
        ("deposit", "500.00", "7", "Market gains")
    loss = transaction(-500, "7", "2026-10-10")["transactions"][0]
    assert (loss["type"], loss["amount"], loss["source_id"], loss["destination_name"]) == \
        ("withdrawal", "500.00", "7", "Market losses")
