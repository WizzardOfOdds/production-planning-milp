"""Scenario definition: everything the optimizer needs to know about the plant.

A scenario is read from a TOML file. Production is described as a set of
*processes*. Each process turns input items into one output item and draws
on machine and worker capacity. Car assembly, remanufacturing and quality
inspection are all just processes with different inputs, so new game
mechanics are added in the config file rather than in the model code.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Item:
    name: str
    stock: int = 0
    holding_cost: float = 0.0
    scrap_price: float | None = None   # None = cannot be sold back


@dataclass
class Process:
    name: str
    output: str
    inputs: dict[str, int]
    machines: dict[str, float] = field(default_factory=dict)  # machine -> units per machine per period
    workers: dict[str, float] = field(default_factory=dict)   # role -> units per worker per period
    available_from: int = 1
    co2_per_unit: float = 0.0          # tonnes


@dataclass
class Machine:
    name: str
    owned: int
    price: float
    floor_space: float
    co2_at_purchase: float = 0.0
    co2_per_period: float = 0.0


@dataclass
class Role:
    name: str
    count: int
    salary: float
    fire_cost: float = 0.0
    hire_cost: float = 0.0


@dataclass
class Supplier:
    item: str
    name: str
    price: float
    delivery_fee: float = 0.0
    co2_per_unit: float = 0.0
    min_qty: int = 0


@dataclass
class Loan:
    name: str
    max_amount: float
    rate: float        # interest per period, e.g. 0.05
    disagio: float = 0.0


@dataclass
class Market:
    item: str
    demand: dict[int, int]     # period -> units
    price: dict[int, float]    # period -> EUR per unit


@dataclass
class Scenario:
    period: int
    cash: float
    last_period: int
    horizon: int
    min_cash: float
    fixed_cost_per_period: float
    floor_space: float
    co2_price: dict[int, float]
    items: dict[str, Item]
    processes: list[Process]
    machines: dict[str, Machine]
    roles: dict[str, Role]
    suppliers: list[Supplier]
    markets: dict[str, Market]
    loans: list[Loan] = field(default_factory=list)
    loan_repayments: dict[int, float] = field(default_factory=dict)

    @property
    def periods(self) -> list[int]:
        """Periods in the planning window. Stops at the last period of the game."""
        end = min(self.period + self.horizon - 1, self.last_period)
        return list(range(self.period, end + 1))

    def validate(self) -> None:
        for p in self.processes:
            for name in [p.output, *p.inputs]:
                if name not in self.items:
                    raise ValueError(f"process '{p.name}' uses unknown item '{name}'")
            for m in p.machines:
                if m not in self.machines:
                    raise ValueError(f"process '{p.name}' uses unknown machine '{m}'")
            for r in p.workers:
                if r not in self.roles:
                    raise ValueError(f"process '{p.name}' uses unknown role '{r}'")
        for s in self.suppliers:
            if s.item not in self.items:
                raise ValueError(f"supplier '{s.name}' sells unknown item '{s.item}'")
        for t in self.periods:
            if t not in self.co2_price:
                raise ValueError(f"no CO2 price for period {t}")
            for mk in self.markets.values():
                if t not in mk.demand or t not in mk.price:
                    raise ValueError(f"market '{mk.item}' has no data for period {t}")


def _by_period(values: list, first: int = 1) -> dict:
    return {first + i: v for i, v in enumerate(values)}


def from_dict(d: dict) -> Scenario:
    g = d["game"]
    first = g.get("first_period", 1)
    sc = Scenario(
        period=g["period"],
        cash=g["cash"],
        last_period=g["last_period"],
        horizon=g.get("horizon", 3),
        min_cash=g.get("min_cash", 0),
        fixed_cost_per_period=g.get("fixed_cost_per_period", 0),
        floor_space=g.get("floor_space", float("inf")),
        co2_price=_by_period(g["co2_price"], first),
        items={k: Item(k, **v) for k, v in d.get("items", {}).items()},
        processes=[Process(name=k, **v) for k, v in d.get("processes", {}).items()],
        machines={k: Machine(k, **v) for k, v in d.get("machines", {}).items()},
        roles={k: Role(k, **v) for k, v in d.get("roles", {}).items()},
        suppliers=[Supplier(**s) for s in d.get("suppliers", [])],
        markets={
            k: Market(k, _by_period(v["demand"], first), _by_period(v["price"], first))
            for k, v in d.get("markets", {}).items()
        },
        loans=[Loan(**x) for x in d.get("loans", [])],
        loan_repayments={int(k): v for k, v in g.get("loan_repayments", {}).items()},
    )
    sc.validate()
    return sc


def load(path: str | Path) -> Scenario:
    with open(path, "rb") as f:
        return from_dict(tomllib.load(f))
