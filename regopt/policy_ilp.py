"""The ILP engine: turns any Policy into a PuLP model and solves it.

Differences from the fixed Model 1 in ilp_allocation.py:
- "get exactly k courses" became "get at most k, but every empty slot
  costs unassigned_penalty" — an == k constraint goes infeasible the
  moment one student's preferences can't yield k conflict-free seats,
  and at 2,000 students someone always can't.
- rank costs are weighted (who you are), discounted (what the course is
  to you), and blended with a max-min term (the equality dial).
- Wesleyan-style seat bins and the near-hard requirement guarantee add
  constraints/penalties.
- priority_mode="tiers" runs one solve per tier (seniors first), freezing
  each tier's seats before the next tier's solve — lexicographic hard
  priority rather than soft weights.
"""

from itertools import combinations

import networkx as nx
import pulp

from regopt.models import Course, Student
from regopt.policy import (
    GUARANTEE_PENALTY,
    Policy,
    edge_cost,
    required_course_ids,
    student_tier,
    student_weight,
)


def _in_group(student: Student, group: str) -> bool:
    """Bin groups are class years ('First-Year') or major codes ('ECON')."""
    return student.class_year == group or student.major == group


def _build_model(
    name: str,
    group: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    policy: Policy,
    requirements: dict[str, set[str]],
    remaining_cap: dict[str, int],
    remaining_bins: dict[str, dict[str, int]],
):
    """Everything except the objective: variables, per-student cost
    expressions, and all shared constraints. Both the main solve and the
    Rawlsian tiebreak re-solve call this, so they can never drift apart on
    which constraints exist.

    Returns (prob, x, cost_expr, guarantee_expr)."""
    prob = pulp.LpProblem(name, pulp.LpMinimize)

    # One binary per (student, ranked course) — same shape as Model 1, but
    # skipping courses with no seats left (matters in tier rounds, where
    # earlier tiers may have drained a course entirely).
    x = {
        s.name: {
            c_id: pulp.LpVariable(f"x_{i}_{c_id}", cat="Binary")
            for c_id in s.prefs
            if c_id in courses and remaining_cap.get(c_id, 0) > 0
        }
        for i, s in enumerate(group)
    }

    # Per-student cost as a linear expression. Algebra note: writing the
    # cost as  penalty*k + sum(x * (edge_cost - penalty))  is identical to
    # "sum of edge costs of what you got, plus penalty per empty slot" —
    # each assignment simultaneously adds its own cost and cancels one
    # slot's penalty. Since penalty > any edge cost, every assignment
    # strictly improves the objective; the solver never leaves a fillable
    # slot empty.
    cost_expr = {}
    for s in group:
        terms = []
        for c_id, var in x[s.name].items():
            rank = s.prefs.index(c_id) + 1
            cost = edge_cost(s, courses[c_id], rank, policy, requirements)
            terms.append(var * (cost - policy.unassigned_penalty))
        cost_expr[s.name] = policy.unassigned_penalty * policy.k + pulp.lpSum(terms)

    # Requirement guarantee: got_req can only reach 1 if the student holds
    # at least one section satisfying a requirement of their major; every
    # student stuck at 0 contributes GUARANTEE_PENALTY to guarantee_expr.
    # Soft-but-huge instead of a hard constraint so a student whose
    # required sections are all full degrades the objective rather than
    # making the whole model infeasible.
    guarantee_expr = 0
    if policy.guarantee_requirement:
        penalties = []
        for i, s in enumerate(group):
            req_ids = required_course_ids(s, courses, requirements)
            req_vars = [x[s.name][c] for c in req_ids if c in x[s.name]]
            if not req_vars:
                continue  # nothing required is attainable; nothing to press on
            got_req = pulp.LpVariable(f"req_{i}", cat="Binary")
            prob += got_req <= pulp.lpSum(req_vars)
            penalties.append(1 - got_req)
        guarantee_expr = GUARANTEE_PENALTY * pulp.lpSum(penalties)

    # At most k courses each; no two courses that meet at the same time.
    for s in group:
        prob += pulp.lpSum(x[s.name].values()) <= policy.k
        for c1, c2 in combinations(x[s.name].keys(), 2):
            if conflict_graph.has_edge(c1, c2):
                prob += x[s.name][c1] + x[s.name][c2] <= 1

    # Capacity, plus Wesleyan bins where configured. The bin encoding:
    # each reserved group may use its reserved seats plus the open pool;
    # everyone outside any bin may use only the open pool; the plain
    # capacity constraint stops two groups from both claiming the same
    # open seats.
    ranked_ids = {c_id for s in group for c_id in x[s.name]}
    for c_id in ranked_ids:
        takers = [s for s in group if c_id in x[s.name]]
        prob += pulp.lpSum(x[s.name][c_id] for s in takers) <= remaining_cap[c_id]

        bins = remaining_bins.get(c_id)
        if bins:
            open_seats = max(0, remaining_cap[c_id] - sum(bins.values()))
            for grp, reserved in bins.items():
                members = [s for s in takers if _in_group(s, grp)]
                if members:
                    prob += pulp.lpSum(
                        x[s.name][c_id] for s in members
                    ) <= reserved + open_seats
            outsiders = [
                s for s in takers if not any(_in_group(s, g) for g in bins)
            ]
            if outsiders:
                prob += pulp.lpSum(
                    x[s.name][c_id] for s in outsiders
                ) <= open_seats

    return prob, x, cost_expr, guarantee_expr


def _solve_group(
    group: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    policy: Policy,
    requirements: dict[str, set[str]],
    remaining_cap: dict[str, int],
    remaining_bins: dict[str, dict[str, int]],
    time_limit: int,
) -> dict[str, list[str]]:
    """One ILP over one set of students against current remaining capacity.
    In weights mode this is called once with everybody; in tiers mode once
    per tier. Mutates remaining_cap/remaining_bins to reflect seats used."""
    prob, x, cost_expr, guarantee_expr = _build_model(
        f"policy_{policy.name}", group, courses, conflict_graph, policy,
        requirements, remaining_cap, remaining_bins,
    )

    # The equality blend: (1-λ) cares about the weighted total, λ cares
    # about the worst-off student (z bounds every student's cost from
    # above; minimizing it pushes the worst case down). z is deliberately
    # compared against UNWEIGHTED cost — "worst-off" means worst actual
    # experience, not worst importance-adjusted experience — so at λ=1 the
    # priority weights genuinely stop mattering, which is what a
    # full-equality slider should mean. The λ term is scaled by group size
    # so both halves of the blend have comparable magnitude and λ=0.5 is a
    # meaningful midpoint.
    lam = policy.equality
    total_term = pulp.lpSum(
        student_weight(s, policy) * cost_expr[s.name] for s in group
    )
    objective = (1 - lam) * total_term + guarantee_expr
    z = None
    if lam > 0:
        z = pulp.LpVariable("z_worst_cost", lowBound=0, cat="Continuous")
        for s in group:
            prob += z >= cost_expr[s.name]
        objective += lam * len(group) * z
    prob += objective

    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit)
    prob.solve(solver)
    status = pulp.LpStatus[prob.status]
    if status not in ("Optimal", "Not Solved"):  # Not Solved = hit time limit
        raise RuntimeError(f"ILP for policy {policy.name!r} ended {status}")

    # Rawlsian tiebreak: at λ=1 the solve above only optimized the worst
    # case, so many allocations tie — re-solve minimizing total cost among
    # allocations that never exceed the worst case just found. Built fresh
    # through the same _build_model, so bins/guarantee/conflicts all still
    # hold; only the objective and the per-student cost cap differ.
    if lam == 1.0 and policy.rawlsian_tiebreak and z is not None:
        z_star = z.value()
        prob2, x2, cost_expr2, guarantee_expr2 = _build_model(
            f"policy_{policy.name}_tiebreak", group, courses, conflict_graph,
            policy, requirements, remaining_cap, remaining_bins,
        )
        for s in group:
            prob2 += cost_expr2[s.name] <= z_star + 1e-6
        prob2 += pulp.lpSum(
            student_weight(s, policy) * cost_expr2[s.name] for s in group
        ) + guarantee_expr2
        prob2.solve(solver)
        if pulp.LpStatus[prob2.status] == "Optimal":
            x = x2  # read the assignment off the tiebreak solution instead

    assignment = {
        s.name: [c for c, var in x[s.name].items()
                 if var.value() is not None and var.value() > 0.5]
        for s in group
    }

    # Book the seats so a following tier sees what's left. Reserved-bin
    # bookkeeping: a group member's seat consumes that group's reservation
    # first; only overflow beyond the reservation came from the open pool.
    for s in group:
        for c_id in assignment[s.name]:
            remaining_cap[c_id] -= 1
    for c_id, bins in remaining_bins.items():
        for grp in bins:
            used = sum(
                1 for s in group
                if _in_group(s, grp) and c_id in assignment[s.name]
            )
            bins[grp] = max(0, bins[grp] - used)

    return assignment


def solve_policy_ilp(
    students: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    policy: Policy,
    requirements: dict[str, set[str]] | None = None,
    time_limit: int = 300,
) -> dict[str, list[str]]:
    """Entry point. Returns {student_name: [assigned course ids]} covering
    every student (possibly with fewer than k courses, or none)."""
    requirements = requirements or {}
    remaining_cap = {c_id: c.capacity for c_id, c in courses.items()}
    # Deep-copy the bins: the solver mutates its copy as seats are used.
    remaining_bins = {
        c_id: dict(groups) for c_id, groups in policy.seat_bins.items()
    }

    if policy.priority_mode != "tiers":
        return _solve_group(students, courses, conflict_graph, policy,
                            requirements, remaining_cap, remaining_bins,
                            time_limit)

    # Lexicographic tiers: fully allocate tier 0, freeze, then tier 1
    # against whatever seats remain, and so on. A later tier can never
    # displace an earlier one — that's the "hard gate" semantics.
    assignment: dict[str, list[str]] = {}
    tiers: dict[int, list[Student]] = {}
    for s in students:
        tiers.setdefault(student_tier(s, policy), []).append(s)
    for tier_index in sorted(tiers):
        assignment.update(
            _solve_group(tiers[tier_index], courses, conflict_graph, policy,
                         requirements, remaining_cap, remaining_bins,
                         time_limit)
        )
    return assignment
