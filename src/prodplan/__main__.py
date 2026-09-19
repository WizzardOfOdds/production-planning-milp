import argparse

from . import model, report, scenario


def main() -> None:
    ap = argparse.ArgumentParser(prog="prodplan", description="Plan one period of the production game.")
    ap.add_argument("scenario", help="path to a scenario .toml file")
    ap.add_argument("--period", type=int, help="override the current period")
    ap.add_argument("--cash", type=float, help="override the cash at the start of the period")
    args = ap.parse_args()

    sc = scenario.load(args.scenario)
    if args.period is not None:
        sc.period = args.period
    if args.cash is not None:
        sc.cash = args.cash
    sc.validate()

    print(report.action_plan(sc, model.solve(sc)))


if __name__ == "__main__":
    main()
