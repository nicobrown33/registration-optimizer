"""The neutral yardstick: score any assignment, whoever produced it.

Every engine optimizes its own policy-shaped objective (weighted,
discounted, exponent-curved). If metrics used those same numbers,
"policy A beats policy B" would be circular — each policy wins on its own
scale. So this module scores everything on one fixed, policy-independent
scale: the plain linear rank cost Nico proposed ("Bob = one 2nd choice +
one 5th choice = 7"), plus a fixed charge per empty schedule slot so that
getting shut out reads as the bad outcome it is, never as a low score.
"""

import pandas as pd

from regopt.models import Course, Student

# Deliberately NOT policy.unassigned_penalty: metrics stay identical
# across policies, or comparisons mean nothing.
UNASSIGNED_COST = 15.0
K = 4  # slots per student on the neutral scale


def student_cost(student: Student, assigned: list[str]) -> float:
    """The linear score: sum of the ranks the student gave what they got
    (1 = first choice), plus UNASSIGNED_COST per empty slot. Lower is
    better; a full schedule of top-4 choices scores 1+2+3+4 = 10."""
    ranks = [student.prefs.index(c_id) + 1 for c_id in assigned]
    return sum(ranks) + UNASSIGNED_COST * (K - len(ranks))


def gini(values: list[float]) -> float:
    """Gini coefficient of the cost distribution: 0 = everyone bears the
    same cost, 1 = one student bears everything. The standard sorted-array
    formula: G = (2 * sum(i * x_i) / (n * sum(x))) - (n + 1) / n, with x
    ascending and i counted from 1."""
    xs = sorted(values)
    n = len(xs)
    total = sum(xs)
    if n == 0 or total == 0:
        return 0.0
    weighted = sum(i * x for i, x in enumerate(xs, start=1))
    return (2 * weighted) / (n * total) - (n + 1) / n


def compute_metrics(
    assignment: dict[str, list[str]],
    students: list[Student],
    courses: dict[str, Course],
    requirements: dict[str, set[str]] | None = None,
) -> dict:
    """One row of the comparison table: satisfaction, fill, equality, and
    requirement-access numbers for a single allocation."""
    requirements = requirements or {}

    # Long form first — one row per (student, assigned course) — then let
    # pandas aggregate, per the Milestone 9 pattern.
    rows = []
    for s in students:
        for c_id in assignment.get(s.name, []):
            rows.append({"student": s.name,
                         "rank": s.prefs.index(c_id) + 1})
    df = pd.DataFrame(rows)

    costs = [student_cost(s, assignment.get(s.name, [])) for s in students]
    cost_series = pd.Series(costs)

    # Requirement access: of the students who ranked at least one section
    # satisfying one of their major's requirements (cross-department ones
    # included), how many actually received one?
    eligible = got = 0
    for s in students:
        required_codes = requirements.get(s.major, set())
        ranked_req = {
            c_id for c_id in s.prefs
            if c_id in courses and courses[c_id].subject_course in required_codes
        }
        if not ranked_req:
            continue
        eligible += 1
        if ranked_req & set(assignment.get(s.name, [])):
            got += 1

    n = len(students)
    return {
        "slots_filled": len(df),
        "fill_rate": len(df) / (n * K),
        "pct_shut_out": sum(1 for s in students
                            if not assignment.get(s.name)) / n,
        "pct_first_choice": (df["rank"] == 1).mean() if not df.empty else 0.0,
        "pct_top3": (df["rank"] <= 3).mean() if not df.empty else 0.0,
        "avg_rank": df["rank"].mean() if not df.empty else float("nan"),
        "worst_rank": int(df["rank"].max()) if not df.empty else 0,
        "avg_cost": cost_series.mean(),
        "median_cost": cost_series.median(),
        "worst_cost": cost_series.max(),
        "std_cost": cost_series.std(),
        "gini_cost": gini(costs),
        "pct_got_required": got / eligible if eligible else float("nan"),
    }


def class_year_breakdown(
    assignment: dict[str, list[str]],
    students: list[Student],
) -> pd.DataFrame:
    """Who a policy actually serves: average neutral cost and fill rate
    per class year. This is the table where a seniority policy's skew (or
    an equality policy's flatness) becomes visible at a glance."""
    rows = []
    for s in students:
        got = assignment.get(s.name, [])
        rows.append({
            "class_year": s.class_year,
            "cost": student_cost(s, got),
            "courses": len(got),
            "first_choice": any(s.prefs.index(c) == 0 for c in got),
        })
    df = pd.DataFrame(rows)
    out = df.groupby("class_year").agg(
        avg_cost=("cost", "mean"),
        fill_rate=("courses", lambda c: c.sum() / (len(c) * K)),
        pct_first_choice=("first_choice", "mean"),
    )
    # Fixed seniority order beats alphabetical for reading the skew.
    order = ["Senior", "Junior", "Sophomore", "First-Year"]
    return out.reindex([y for y in order if y in out.index])


def comparison_table(
    runs: dict[tuple[str, str], dict[str, list[str]]],
    students: list[Student],
    courses: dict[str, Course],
    requirements: dict[str, set[str]] | None = None,
) -> pd.DataFrame:
    """The headline deliverable: one row per (policy, engine) run, all
    metrics side by side. `runs` maps (policy_name, engine_name) to an
    assignment dict."""
    records = []
    for (policy_name, engine), assignment in runs.items():
        m = compute_metrics(assignment, students, courses, requirements)
        records.append({"policy": policy_name, "engine": engine, **m})
    return pd.DataFrame(records).set_index(["policy", "engine"])
