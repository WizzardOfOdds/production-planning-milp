"""Turns a solved Plan into the checklist you type into the game each period."""

from __future__ import annotations

from .model import Plan
from .scenario import Scenario


def _eur(x: float) -> str:
    return f"EUR {x:>12,.0f}"


def action_plan(sc: Scenario, plan: Plan) -> str:
    t = plan.periods[0]
    out = [f"PERIOD {t}  (planning {plan.periods[0]}-{plan.periods[-1]}, starting cash {_eur(sc.cash).strip()})", ""]

    def section(title, lines):
        out.append(title)
        out.extend(f"  {line}" for line in lines) if lines else out.append("  -")
        out.append("")

    section("1. Invest and staff", [
        *(f"buy  {m:<20} x{n}" for (u, m), n in plan.buy.items() if u == t and n),
        *(f"hire {r:<20} +{n}" for (u, r), n in plan.hire.items() if u == t and n),
        *(f"fire {r:<20} -{n}" for (u, r), n in plan.fire.items() if u == t and n),
        *(f"take loan {k:<15} {_eur(v)}" for k, v in plan.loans.items() if v > 1),
    ])
    section("2. Order parts", [
        f"{sc.suppliers[s].item:<14} from {sc.suppliers[s].name:<14} {n:>6}"
        for (u, s), n in plan.order.items() if u == t and n
    ])
    section("3. Produce", [
        f"{p:<20} {n:>6}" for (u, p), n in plan.run.items() if u == t and n
    ])
    section("4. Sell", [
        *(f"{i:<20} {n:>6} @ {sc.markets[i].price[t]:,.0f}" for (u, i), n in plan.sell.items() if u == t and n),
        *(f"scrap {i:<14} {n:>6}" for (u, i), n in plan.scrap.items() if u == t and n),
    ])

    out.append("Outlook")
    for u in plan.periods:
        made = ", ".join(f"{p} {n}" for (w, p), n in plan.run.items() if w == u and n) or "nothing"
        out.append(f"  P{u}: produce {made}; cash at end {_eur(plan.cash[u])}")
    out.append("")
    out.append(f"Objective (end cash + sellable stock - loans): {_eur(plan.objective).strip()}")
    return "\n".join(out)
