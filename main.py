"""Run registration policies through the allocation engines and compare.

The IT-department view of the project: pick a policy (a named preset or a
JSON file of slider settings), pick a mechanism, and read the tables.

    python main.py                             # all presets x both engines
    python main.py --preset rawlsian --engine ilp
    python main.py --policy policies/balanced.json
    python main.py --export-presets            # write policies/*.json
    python main.py --limit 400 --seed 7        # quicker, smaller run

The FCFS baseline (regopt/baseline.py — the simulation of how Middlebury
actually registers students today) is always included as the anchor row.
"""

import argparse
import os

import pandas as pd

from regopt.baseline import compute_priority_order, run_baseline
from regopt.deferred_acceptance import solve_deferred_acceptance
from regopt.graphs import build_conflict_graph
from regopt.io import load_courses, load_major_requirements, load_students
from regopt.metrics import class_year_breakdown, comparison_table
from regopt.policy import PRESETS, Policy
from regopt.policy_ilp import solve_policy_ilp


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--preset", default="all",
                   help=f"one of {', '.join(PRESETS)}, or 'all' (default)")
    p.add_argument("--policy", metavar="FILE",
                   help="load a Policy from a JSON file instead of a preset")
    p.add_argument("--engine", choices=["ilp", "da", "both"], default="both")
    p.add_argument("--k", type=int, help="override courses per student")
    p.add_argument("--seed", type=int, help="override tie-breaking seed")
    p.add_argument("--limit", type=int,
                   help="only use the first N students (faster experiments)")
    p.add_argument("--time-limit", type=int, default=300,
                   help="CBC time limit per solve, seconds")
    p.add_argument("--export-presets", action="store_true",
                   help="write every preset to policies/<name>.json and exit")
    p.add_argument("--chart", metavar="FILE",
                   help="also save the rank-distribution chart as a PNG")
    return p.parse_args()


def selected_policies(args, courses) -> list[Policy]:
    if args.policy:
        policies = [Policy.from_json(args.policy)]
    elif args.preset == "all":
        policies = [factory(courses) for factory in PRESETS.values()]
    else:
        policies = [PRESETS[args.preset](courses)]
    # CLI overrides beat whatever the preset/file said.
    for pol in policies:
        if args.k is not None:
            pol.k = args.k
        if args.seed is not None:
            pol.seed = args.seed
    return policies


def main() -> None:
    args = parse_args()
    courses = load_courses()
    students = load_students()
    if args.limit:
        students = students[: args.limit]
    conflict_graph = build_conflict_graph(courses)
    requirements = load_major_requirements()

    if args.export_presets:
        os.makedirs("policies", exist_ok=True)
        for name, factory in PRESETS.items():
            path = os.path.join("policies", f"{name}.json")
            factory(courses).to_json(path)
            print(f"wrote {path}")
        return

    policies = selected_policies(args, courses)
    engines = ["ilp", "da"] if args.engine == "both" else [args.engine]

    # The anchor: today's system, simulated (seniority gate + login race +
    # occasional instructor overrides for majors).
    runs: dict[tuple[str, str], dict[str, list[str]]] = {}
    priority_order = compute_priority_order(students)
    runs[("baseline_fcfs", "serial")] = run_baseline(
        students, courses, conflict_graph, priority_order)

    for pol in policies:
        for engine in engines:
            print(f"running {pol.name} / {engine} ...", flush=True)
            if engine == "ilp":
                assignment = solve_policy_ilp(
                    students, courses, conflict_graph, pol, requirements,
                    time_limit=args.time_limit)
            else:
                assignment = solve_deferred_acceptance(
                    students, courses, conflict_graph, pol, requirements)
            runs[(pol.name, engine)] = assignment

    pd.set_option("display.width", 200)
    print("\n=== Comparison (neutral linear cost; lower cost = better; "
          "gini 0 = perfectly even) ===")
    table = comparison_table(runs, students, courses, requirements)
    print(table.round(3).to_string())

    # Second view: the same runs, but asking "who does each policy serve?"
    # — average neutral cost per class year, one column per year.
    print("\n=== Average cost by class year (rows = runs) ===")
    year_rows = {}
    for key, assignment in runs.items():
        breakdown = class_year_breakdown(assignment, students)
        year_rows[key] = breakdown["avg_cost"]
    print(pd.DataFrame(year_rows).T.round(2).to_string())

    if args.chart:
        from regopt.viz import plot_rank_distribution

        # One row per policy: the baseline plus each policy's ILP run
        # (fall back to DA rows when only DA was requested).
        preferred = "ilp" if args.engine in ("ilp", "both") else "da"
        chart_runs = {
            ("baseline (today's FCFS)" if pol == "baseline_fcfs" else pol): a
            for (pol, engine), a in runs.items()
            if engine in ("serial", preferred)
        }
        plot_rank_distribution(
            chart_runs, students, args.chart,
            subtitle=f"{len(students):,} students × 4 slots, real Fall 2026 "
                     f"catalog — {preferred.upper()} engine vs. FCFS baseline",
        )


if __name__ == "__main__":
    main()
