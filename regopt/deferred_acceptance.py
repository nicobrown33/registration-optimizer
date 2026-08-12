"""The deferred-acceptance engine: Gale-Shapley, adapted for course
registration, consuming the same Policy as the ILP engine.

Why have a second mechanism at all: Diebold/Bichler et al. (BISE 2014,
"Course Allocation via Stable Matching") argue FCFS registration is
neither stable nor strategy-proof, and that deferred acceptance fixes
both — students propose in their own preference order, courses hold the
best proposals *tentatively* and bump weaker ones when better ones
arrive, so nobody gains by lying about their list. The course-side notion
of "best" is exactly where institutional policy plugs in: here it's
policy.priority_score — the same weights, requirement bonuses, tiers, and
bins the ILP uses as objective coefficients become the order in which a
full course keeps students.

Honesty note (also in POLICY_ENGINE_EXPLAINED.md): the clean theory
covers each student wanting ONE course. Wanting k courses at once with
time conflicts makes this a many-to-many matching with complementarities,
where stability and strategy-proofness are no longer guaranteed in
general — this implementation keeps the spirit (tentative holds, bumping,
priority cutoffs that only rise) but is a principled heuristic, not a
theorem-backed mechanism.
"""

import random
from collections import deque

import networkx as nx

from regopt.models import Course, Student
from regopt.policy import Policy, priority_score


def _course_choice(
    candidates: list[Student],
    course: Course,
    policy: Policy,
    requirements: dict[str, set[str]],
    lottery: dict[str, float],
) -> set[str]:
    """Which of these candidates does the course keep? Without bins: the
    top `capacity` by priority score. With bins: first fill each group's
    reserved seats from that group's best members, then fill whatever
    capacity remains from everyone left over by open priority — the
    matching-with-reserves counterpart of the ILP's bin constraints."""
    def score(s: Student):
        return priority_score(s, course, policy, requirements, lottery[s.name])

    ranked = sorted(candidates, key=score, reverse=True)
    bins = policy.seat_bins.get(course.id)
    if not bins:
        return {s.name for s in ranked[: course.capacity]}

    accepted: list[Student] = []
    leftovers: list[Student] = []
    taken = {grp: 0 for grp in bins}
    for s in ranked:
        grp = next(
            (g for g in bins
             if (s.class_year == g or s.major == g) and taken[g] < bins[g]),
            None,
        )
        if grp is not None and len(accepted) < course.capacity:
            taken[grp] += 1
            accepted.append(s)
        else:
            leftovers.append(s)
    open_left = course.capacity - len(accepted)
    accepted.extend(leftovers[:max(0, open_left)])
    return {s.name for s in accepted}


def solve_deferred_acceptance(
    students: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    policy: Policy,
    requirements: dict[str, set[str]] | None = None,
) -> dict[str, list[str]]:
    """Student-proposing deferred acceptance. Returns
    {student_name: [assigned course ids]}, up to policy.k each."""
    requirements = requirements or {}
    by_name = {s.name: s for s in students}

    # One lottery number per student, fixed for the whole run: the final
    # component of every priority comparison, so ties break randomly but
    # identically at every course (a single lottery, like Wesleyan's
    # randomized order, not a fresh coin flip per course).
    rng = random.Random(policy.seed)
    lottery = {s.name: rng.random() for s in students}

    holds: dict[str, set[str]] = {s.name: set() for s in students}
    course_holds: dict[str, set[str]] = {c_id: set() for c_id in courses}
    # Once a course has rejected (or bumped) a student, re-proposing is
    # pointless: a course's pool only ever grows, so its cutoff only
    # rises. This is also what guarantees termination — each (student,
    # course) proposal can happen at most once.
    rejected: dict[str, set[str]] = {s.name: set() for s in students}

    queue = deque(students)
    while queue:
        student = queue.popleft()
        mine = holds[student.name]
        # Scan the preference list top-down for the best course still
        # worth proposing to; repeat until the schedule is full or the
        # list is exhausted. The conflict check is against *current*
        # holds — if a held course is bumped later, this student re-enters
        # the queue and re-scans, so earlier conflict-skips get another
        # chance.
        for c_id in student.prefs:
            if len(mine) >= policy.k:
                break
            if (c_id not in courses or courses[c_id].capacity <= 0
                    or c_id in mine or c_id in rejected[student.name]):
                continue
            if any(conflict_graph.has_edge(c_id, held) for held in mine):
                continue

            pool = [by_name[n] for n in course_holds[c_id]] + [student]
            accepted = _course_choice(pool, courses[c_id], policy,
                                      requirements, lottery)
            if student.name not in accepted:
                rejected[student.name].add(c_id)
                continue

            for bumped_name in course_holds[c_id] - accepted:
                holds[bumped_name].discard(c_id)
                rejected[bumped_name].add(c_id)
                queue.append(by_name[bumped_name])
            course_holds[c_id] = accepted
            mine.add(c_id)

    return {s.name: sorted(holds[s.name], key=s.prefs.index)
            for s in students}
