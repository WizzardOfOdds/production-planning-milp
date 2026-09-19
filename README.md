# production-planning-milp

*Built with the help of Claude Code.*

A mixed-integer optimizer for a 16-period production business game. In the
game you run an electric-car plant. Each period you decide what to buy, whom
to hire, what to build and what to sell. The optimizer tells you what to do
this period to end up with the most money when the company is sold.

I originally wrote this during a university business simulation.
The first version grew by adding one special case per new game
rule, until the model was a 1,000-line script. This is a rewrite around one
idea that made most of the special cases go away (see [Design](#design)).

## What it decides

For the current period and the next two (the game announces prices two
periods ahead):

- how many units each process runs (build axles, chassis, bodies, assemble cars, ...)
- how much to order from which supplier (with minimum order sizes and delivery fees)
- how many cars and parts to sell, and which leftover parts to scrap
- machines to buy, workers to hire or fire, loans to take

subject to machine and staff capacity, floor space, stock balances, and a
cash floor of EUR 50,000 at the end of every period.

## Run it

```
pip install -e .
python -m prodplan scenarios/example.toml
python -m prodplan scenarios/example.toml --period 12 --cash 1500000
```

```
PERIOD 9  (planning 9-11, starting cash EUR      900,000)

2. Order parts
  motor          from Voltwerk          273
  battery        from CellCo            273
  ...
3. Produce
  axle                    273
  assembly                273
  remanufacture            50
  quality_check            50

4. Sell
  car                     150 @ 22,500

Outlook
  P9:  ... cash at end EUR       50,000
  P10: ... cash at end EUR    1,006,177
```

In this example period, cash is the binding constraint. The plant could build
300 cars, but only 273 batteries can be paid for without dropping below the
cash floor. Chassis and bodies are still built to capacity, because they are
cheap and next period's cash will cover the batteries for them.

## The model

Sets: periods `t` in the window, items `i`, processes `p`, machines `m`,
roles `r`, suppliers `s`.

| | |
|---|---|
| stock balance | `stock[t,i] = stock[t-1,i] + made + ordered - consumed - sold - scrapped` |
| sell only old stock | `sell[t,i] <= stock[t-1,i]` and `<= demand[t,i]` |
| machine capacity | `sum_p run[t,p] / rate[p,m] <= owned[m] + bought up to t` |
| staff capacity | `sum_p run[t,p] / rate[p,r] <= headcount[r] + hired - fired` |
| minimum order | `min_qty[s] * uses[t,s] <= order[t,s] <= M * uses[t,s]` |
| cash | `cash[t] = cash[t-1] + revenue - costs >= min_cash` |
| objective | `max cash[T] + value of stock the market can take next period - loan principal` |

Integer variables: production, orders, sales, purchases, hires. The binary
`uses[t,s]` switches on the delivery fee and the minimum order. Solved with
[HiGHS](https://highs.dev) through PuLP. The example scenario solves in a few seconds.

## Design

In the game, new rules showed up mid-semester: first you could sell
axles on their own, then remanufacture old axles, then put remanufactured
axles through a quality check so they count as new ones. Each rule
used to get its own variables and its own `if` branches.

Here, all of them are a **process**: it consumes some items, produces one
item, and uses some machine and worker capacity.

```toml
[processes.quality_check]
output = "e_axle"
inputs = { reman_axle = 1 }
workers = { inspector = 50 }   # inspectors are half as fast here as on the line
available_from = 9
```

Machines and workers are treated as pooled budgets. A welding robot
used by both the body shop and final assembly, or an inspector who splits
time between the line and the quality check, needs no extra code. The
same stock-balance constraint covers raw parts, intermediates and finished
cars.

Two end-of-game details matter a lot in practice:

- **The game ends.** The planning window stops at period 16, and stock left
  after that is worth nothing. Without this, the model fires everyone in the
  last period to save on salaries for a period that never happens.
- **Terminal value is capped.** Stock at the end of the window is valued
  at the next price, but only up to one period of demand. Otherwise the
  solver builds a warehouse full of cars to "sell" just past the horizon.

## Tests

```
pip install -e .[dev]
pytest
```

The tests use a toy two-item plant and check behaviour rather than numbers:
nothing is sold in the period it is made, nothing is built in the final
period, the cash floor holds, minimum orders are all-or-nothing, shared
workers are not double-counted, and processes stay off until they unlock.

## Limitations

- Loans are taken only in the current period and never repaid inside the window.
  Existing repayments are entered as fixed outflows.
- Machines don't depreciate and can't be sold.
- Demand is treated as known. In the game it is, for two periods. Beyond that
  it isn't, which is why the model is re-run every period.
- The numbers in `scenarios/example.toml` are made up. They are not the game's data.
