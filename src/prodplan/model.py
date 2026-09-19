"""Mixed-integer model of the production game.

Rolling horizon: we plan the current period plus the next few whose market
data is already known, commit to the first period, and re-run next period
with fresh numbers.

Timing rules of the game:
  * everything produced in period t can only be sold from period t+1 on
  * cash may never fall below `min_cash` at the end of any period
  * the company is sold after `last_period`, so stock left over then is worthless
"""

from __future__ import annotations

from dataclasses import dataclass

import pulp

from .scenario import Scenario


@dataclass
class Plan:
    status: str
    objective: float
    periods: list[int]
    run: dict[tuple[int, str], int]            # (t, process) -> units
    order: dict[tuple[int, int], int]          # (t, supplier index) -> units
    sell: dict[tuple[int, str], int]
    scrap: dict[tuple[int, str], int]
    buy: dict[tuple[int, str], int]
    hire: dict[tuple[int, str], int]
    fire: dict[tuple[int, str], int]
    loans: dict[str, float]
    stock: dict[tuple[int, str], float]
    cash: dict[int, float]


def build(sc: Scenario) -> tuple[pulp.LpProblem, dict]:
    T = sc.periods
    last = T[-1]
    items = list(sc.items)
    procs = [p for p in sc.processes]
    S = range(len(sc.suppliers))
    scrappable = [i for i, it in sc.items.items() if it.scrap_price is not None]

    prob = pulp.LpProblem("production_plan", pulp.LpMaximize)
    Int = dict(lowBound=0, cat="Integer")

    run = {(t, p.name): pulp.LpVariable(f"run_{t}_{p.name}", **Int) for t in T for p in procs}
    order = {(t, s): pulp.LpVariable(f"order_{t}_{s}", **Int) for t in T for s in S}
    uses = {(t, s): pulp.LpVariable(f"uses_{t}_{s}", cat="Binary") for t in T for s in S}
    sell = {(t, i): pulp.LpVariable(f"sell_{t}_{i}", **Int) for t in T for i in sc.markets}
    scrap = {(t, i): pulp.LpVariable(f"scrap_{t}_{i}", **Int) for t in T for i in scrappable}
    buy = {(t, m): pulp.LpVariable(f"buy_{t}_{m}", **Int) for t in T for m in sc.machines}
    hire = {(t, r): pulp.LpVariable(f"hire_{t}_{r}", **Int) for t in T for r in sc.roles}
    fire = {(t, r): pulp.LpVariable(f"fire_{t}_{r}", **Int) for t in T for r in sc.roles}
    loan = {l.name: pulp.LpVariable(f"loan_{l.name}", 0, l.max_amount) for l in sc.loans}
    stock = {(t, i): pulp.LpVariable(f"stock_{t}_{i}", lowBound=0) for t in T for i in items}
    cash = {t: pulp.LpVariable(f"cash_{t}", lowBound=sc.min_cash) for t in T}

    def machines(t, m):
        return sc.machines[m].owned + pulp.lpSum(buy[u, m] for u in T if u <= t)

    def staff(t, r):
        return sc.roles[r].count + pulp.lpSum(hire[u, r] - fire[u, r] for u in T if u <= t)

    def start_stock(t, i):
        return sc.items[i].stock if t == T[0] else stock[t - 1, i]

    for t in T:
        for p in procs:
            if t < p.available_from:
                prob += run[t, p.name] == 0, f"not_yet_{t}_{p.name}"

        # Minimum order quantity, and the delivery fee is due whenever we order at all.
        for s, sup in enumerate(sc.suppliers):
            big_m = 100_000
            prob += order[t, s] >= sup.min_qty * uses[t, s]
            prob += order[t, s] <= big_m * uses[t, s]

        # Machines and workers are pooled: a welding robot or a machinist can be
        # split across every process that needs one. Capacity is a budget of
        # "machine-periods", and each unit of a process spends 1/rate of it.
        for m in sc.machines:
            load = pulp.lpSum(run[t, p.name] * (1 / p.machines[m]) for p in procs if m in p.machines)
            prob += load <= machines(t, m), f"machine_cap_{t}_{m}"
        for r in sc.roles:
            load = pulp.lpSum(run[t, p.name] * (1 / p.workers[r]) for p in procs if r in p.workers)
            prob += load <= staff(t, r), f"staff_cap_{t}_{r}"
            prob += staff(t, r) >= 0

        if sc.floor_space != float("inf"):
            prob += pulp.lpSum(machines(t, m) * mc.floor_space for m, mc in sc.machines.items()) <= sc.floor_space

        for i in items:
            made = pulp.lpSum(run[t, p.name] for p in procs if p.output == i)
            used = pulp.lpSum(run[t, p.name] * p.inputs[i] for p in procs if i in p.inputs)
            bought = pulp.lpSum(order[t, s] for s, sup in enumerate(sc.suppliers) if sup.item == i)
            sold = sell.get((t, i), 0) + scrap.get((t, i), 0)
            prob += stock[t, i] == start_stock(t, i) + made + bought - used - sold, f"balance_{t}_{i}"

        for i, mk in sc.markets.items():
            prob += sell[t, i] <= mk.demand[t]
            prob += sell[t, i] <= start_stock(t, i), f"sell_from_old_stock_{t}_{i}"

        co2 = sc.co2_price[t]
        revenue = (
            pulp.lpSum(sell[t, i] * mk.price[t] for i, mk in sc.markets.items())
            + pulp.lpSum(scrap[t, i] * sc.items[i].scrap_price for i in scrappable)
        )
        if t == T[0]:
            revenue += pulp.lpSum(loan[l.name] * (1 - l.disagio) for l in sc.loans)

        costs = (
            pulp.lpSum(order[t, s] * (sup.price + sup.co2_per_unit * co2) + uses[t, s] * sup.delivery_fee
                       for s, sup in enumerate(sc.suppliers))
            + pulp.lpSum(run[t, p.name] * p.co2_per_unit * co2 for p in procs)
            + pulp.lpSum(machines(t, m) * mc.co2_per_period * co2 for m, mc in sc.machines.items())
            + pulp.lpSum(buy[t, m] * (mc.price + mc.co2_at_purchase * co2) for m, mc in sc.machines.items())
            + pulp.lpSum(staff(t, r) * ro.salary + hire[t, r] * ro.hire_cost + fire[t, r] * ro.fire_cost
                         for r, ro in sc.roles.items())
            + pulp.lpSum(stock[t, i] * it.holding_cost for i, it in sc.items.items())
            + pulp.lpSum(loan[l.name] * l.rate for l in sc.loans)
            + sc.fixed_cost_per_period
            + sc.loan_repayments.get(t, 0)
        )
        prev_cash = sc.cash if t == T[0] else cash[t - 1]
        prob += cash[t] == prev_cash + revenue - costs, f"cash_{t}"

    # What is still in stock at the end of the window is worth something, but
    # only as much as the market can absorb one period later, and nothing at
    # all once the game is over. Without the cap the solver would happily
    # build a warehouse full of cars to "sell" at the horizon.
    terminal = {}
    if last < sc.last_period:
        for i, mk in sc.markets.items():
            terminal[i] = pulp.LpVariable(f"terminal_{i}", lowBound=0)
            prob += terminal[i] <= stock[last, i]
            prob += terminal[i] <= mk.demand[last]

    # Loan principal is subtracted so borrowing only happens when it pays for itself.
    prob += (
        cash[last]
        + pulp.lpSum(terminal[i] * sc.markets[i].price[last] for i in terminal)
        - pulp.lpSum(loan.values())
    )

    variables = dict(run=run, order=order, sell=sell, scrap=scrap, buy=buy,
                     hire=hire, fire=fire, loan=loan, stock=stock, cash=cash)
    return prob, variables


def solve(sc: Scenario, time_limit: int = 60) -> Plan:
    prob, v = build(sc)
    prob.solve(pulp.HiGHS(msg=False, timeLimit=time_limit))
    status = pulp.LpStatus[prob.status]
    if status != "Optimal":
        raise RuntimeError(f"solver finished with status '{status}' - check cash and market data")

    def ints(d):
        return {k: int(round(x.value() or 0)) for k, x in d.items()}

    return Plan(
        status=status,
        objective=pulp.value(prob.objective),
        periods=sc.periods,
        run=ints(v["run"]), order=ints(v["order"]), sell=ints(v["sell"]),
        scrap=ints(v["scrap"]), buy=ints(v["buy"]), hire=ints(v["hire"]), fire=ints(v["fire"]),
        loans={k: x.value() or 0.0 for k, x in v["loan"].items()},
        stock={k: x.value() or 0.0 for k, x in v["stock"].items()},
        cash={k: x.value() for k, x in v["cash"].items()},
    )
