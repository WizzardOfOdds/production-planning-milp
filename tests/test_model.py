"""Behavioural tests on a two-item toy plant: buy widgets, assemble gadgets, sell gadgets."""

import copy
from pathlib import Path

import pytest

from prodplan import from_dict, load, solve

BASE = {
    "game": {
        "period": 1, "cash": 100_000, "last_period": 5, "horizon": 3,
        "min_cash": 1_000, "co2_price": [10] * 5,
    },
    "items": {
        "widget": {"holding_cost": 1},
        "gadget": {"holding_cost": 2},
    },
    "processes": {
        "assemble": {
            "output": "gadget", "inputs": {"widget": 2},
            "machines": {"bench": 100}, "workers": {"fitter": 50},
        },
    },
    "machines": {"bench": {"owned": 1, "price": 50_000, "floor_space": 10}},
    "roles": {"fitter": {"count": 2, "salary": 1_000, "fire_cost": 500}},
    "suppliers": [{"item": "widget", "name": "acme", "price": 10}],
    "markets": {"gadget": {"demand": [80] * 5, "price": [100] * 5}},
}


def scenario(**overrides):
    d = copy.deepcopy(BASE)
    for path, value in overrides.items():
        *keys, last = path.split("__")
        node = d
        for k in keys:
            node = node[k]
        node[last] = value
    return from_dict(d)


def test_nothing_is_sold_in_the_period_it_is_made():
    plan = solve(scenario())
    assert plan.sell[1, "gadget"] == 0          # empty warehouse at the start
    assert plan.run[1, "assemble"] >= 80        # build for next period's demand
    assert plan.sell[2, "gadget"] == 80


def test_no_production_in_the_last_period_of_the_game():
    plan = solve(scenario(game__period=4))
    assert plan.periods == [4, 5]
    assert plan.run[5, "assemble"] == 0


def test_cash_never_drops_below_the_floor():
    # Only enough money for about 20 gadgets' worth of widgets plus wages.
    plan = solve(scenario(game__cash=3_500, game__min_cash=1_000))
    assert all(c >= 1_000 - 1e-6 for c in plan.cash.values())
    assert plan.run[1, "assemble"] < 80


def test_minimum_order_quantity_is_all_or_nothing():
    sc = scenario()
    sc.suppliers[0].min_qty = 500
    plan = solve(sc)
    ordered = [n for (t, _), n in plan.order.items() if n]
    assert all(n >= 500 for n in ordered)


def test_worker_capacity_is_shared_between_processes():
    d = copy.deepcopy(BASE)
    d["items"]["kit"] = {}
    d["processes"]["pack"] = {
        "output": "kit", "inputs": {"gadget": 1},
        "machines": {}, "workers": {"fitter": 25},
    }
    d["markets"]["kit"] = {"demand": [100] * 5, "price": [1_000] * 5}
    d["markets"]["gadget"]["demand"] = [0] * 5
    d["roles"]["fitter"]["count"] = 3
    d["roles"]["fitter"]["salary"] = 0
    plan = solve(from_dict(d))
    # Each gadget takes 1/50 of a fitter-period, each kit 1/25, from one shared pool.
    fitters = 3 + plan.hire[1, "fitter"] - plan.fire[1, "fitter"]
    used = plan.run[1, "assemble"] / 50 + plan.run[1, "pack"] / 25
    assert plan.run[1, "pack"] > 0
    assert used <= fitters + 1e-6


def test_processes_stay_off_until_they_unlock():
    d = copy.deepcopy(BASE)
    d["processes"]["assemble"]["available_from"] = 2
    plan = solve(from_dict(d))
    assert plan.run[1, "assemble"] == 0
    assert plan.run[2, "assemble"] > 0


def test_expensive_loan_is_not_taken_when_not_needed():
    d = copy.deepcopy(BASE)
    d["loans"] = [{"name": "bank", "max_amount": 1_000_000, "rate": 0.1}]
    plan = solve(from_dict(d))
    assert plan.loans["bank"] == pytest.approx(0, abs=1)


def test_unknown_item_in_process_is_rejected():
    d = copy.deepcopy(BASE)
    d["processes"]["assemble"]["inputs"] = {"sprocket": 1}
    with pytest.raises(ValueError, match="sprocket"):
        from_dict(d)


def test_example_scenario_solves():
    sc = load(Path(__file__).parent.parent / "scenarios" / "example.toml")
    plan = solve(sc)
    assert plan.status == "Optimal"
    assert plan.run[sc.period, "assembly"] > 0
