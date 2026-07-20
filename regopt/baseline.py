import random

import networkx as nx
from regopt.models import Student, Course
from regopt.io import load_courses, load_students
from regopt.graphs import build_conflict_graph

# Per Part I research on Middlebury's real registration system: seniority
# (credits earned) is a hard gate, not a tiebreaker — a senior registers
# before every sophomore, full stop. Our synthetic Student only carries a
# class_year category, not an exact credit count, so class_year stands in
# as the seniority signal.
SENIORITY_RANK = {"Senior": 4, "Junior": 3, "Sophomore": 2, "First-Year": 1}

# Within the same class year, priority comes down to who logs in/refreshes
# fastest at the registration window opens — not something this simulation
# can predict, so it's modeled as random rather than pretending otherwise.

# Majors can sometimes negotiate their way into an already-full course in
# their own department by emailing the instructor — modeled as a per-
# attempt probability, not a guarantee ("sometimes... at times").
MAJOR_OVERRIDE_PROBABILITY = 0.3


def compute_priority_order(students: list[Student], seed: int = 0) -> list[Student]:
    """Seniority tier (Senior first) strictly trumps everything; students
    within the same tier are shuffled, since real ordering there is
    effectively a race this simulation has no signal to predict."""
    rng = random.Random(seed)
    tiers: dict[int, list[Student]] = {}
    for s in students:
        tiers.setdefault(SENIORITY_RANK[s.class_year], []).append(s)

    order = []
    for tier in sorted(tiers, reverse=True):  # Senior (4) first, First-Year (1) last
        group = tiers[tier]
        rng.shuffle(group)
        order.extend(group)
    return order


def run_baseline(
    students: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    priority_order: list[Student],
    k: int = 4,   # courses each student needs this term
    seed: int = 0,
) -> dict[str, list[str]]:
    """Returns {student_name: [assigned course ids]}."""
    rng = random.Random(seed)
    remaining_seats = {cid: c.capacity for cid, c in courses.items()}
    assignment = {s.name: [] for s in students}

    for student in priority_order:
        accepted = assignment[student.name]
        for course_id in student.prefs:
            if len(accepted) >= k:
                break
            if course_id not in courses:
                continue
            if any(conflict_graph.has_edge(course_id, taken) for taken in accepted):
                continue

            course_full = remaining_seats[course_id] <= 0
            if course_full:
                is_major_match = courses[course_id].department == student.major
                negotiated_in = is_major_match and rng.random() < MAJOR_OVERRIDE_PROBABILITY
                if not negotiated_in:
                    continue
                # Instructor override: admitted despite the course being at
                # capacity — remaining_seats can go negative, which is itself
                # a signal worth reporting (how often majors get squeezed in
                # over nominal capacity).

            accepted.append(course_id)
            remaining_seats[course_id] -= 1

    return assignment


def summarize(assignment: dict[str, list[str]], students: list[Student]) -> dict:
    """Quick satisfaction summary: % 1st choice, % top-3, average rank."""
    ranks = []
    for student in students:
        for course_id in assignment[student.name]:
            ranks.append(student.prefs.index(course_id) + 1)

    return {
        "num_assigned_slots": len(ranks),
        "pct_first_choice": sum(r == 1 for r in ranks) / len(ranks),
        "pct_top3": sum(r <= 3 for r in ranks) / len(ranks),
        "avg_rank": sum(ranks) / len(ranks),
    }


if __name__ == "__main__":
    courses = load_courses()
    students = load_students()
    conflict_graph = build_conflict_graph(courses)

    priority_order = compute_priority_order(students)
    assignment = run_baseline(students, courses, conflict_graph, priority_order)

    first = students[0]
    print(f"{first.name} assigned: {assignment[first.name]}")

    print(summarize(assignment, students))