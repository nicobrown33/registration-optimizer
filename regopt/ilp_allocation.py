from itertools import combinations

import pulp
import networkx as nx
from regopt.models import Student, Course
from regopt.io import load_courses, load_students
from regopt.graphs import build_conflict_graph

def solve_min_total_rank(
    students: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    k: int = 4,
) -> dict[str, list[str]]:
    """Solve the ILP to minimize total rank of assigned courses, subject to
    constraints: each student gets k courses, no conflicts, no overcapacity.
    Returns {student_name: [assigned course ids]}."""
    prob = pulp.LpProblem("CourseAssignment", pulp.LpMinimize)

    # Decision variables: only for (student, course) pairs the student
    # actually ranked — a student can never be assigned a course they didn't
    # rank, so there's no reason to create a variable for it. With 1,834
    # real courses in the catalog but only ~10 ranked per student, this is
    # the difference between ~230 variables and ~42,000.
    x = {
        s.name: {
            c_id: pulp.LpVariable(f"x_{s.name}_{c_id}", cat="Binary")
            for c_id in s.prefs if c_id in courses
        }
        for s in students
    }

    # Objective: minimize total rank of assigned courses
    prob += pulp.lpSum(
        (s.prefs.index(c_id) + 1) * var
        for s in students for c_id, var in x[s.name].items()
    )

    # Constraints:
    # 1. Each student gets exactly k courses, among the ones they ranked
    #    (previously summed over every course in the catalog, so unranked
    #    — free, since they're outside the objective — courses could fill
    #    a student's quota instead of their actual preferences).
    for s in students:
        prob += pulp.lpSum(x[s.name].values()) == k

    # 2. No conflicts: only need to check pairs within each student's own
    #    ranked list (at most 10 courses), not every pair in the whole
    #    catalog (previously O(courses^2) per student — ~77M iterations
    #    total against the real 1,834-course catalog).
    for s in students:
        for c1_id, c2_id in combinations(x[s.name].keys(), 2):
            if conflict_graph.has_edge(c1_id, c2_id):
                prob += x[s.name][c1_id] + x[s.name][c2_id] <= 1

    # 3. No overcapacity: only for courses somebody actually ranked.
    ranked_course_ids = {c_id for s in students for c_id in x[s.name]}
    for c_id in ranked_course_ids:
        prob += pulp.lpSum(
            x[s.name][c_id] for s in students if c_id in x[s.name]
        ) <= courses[c_id].capacity

    # Solve the problem
    prob.solve()

    # Extract the assignment from the solution. PuLP returns floats close to
    # 0/1, not exact — use > 0.5, not == 1.
    assignment = {
        s.name: [c_id for c_id, var in x[s.name].items() if pulp.value(var) > 0.5]
        for s in students
    }

    return assignment


if __name__ == "__main__":
    from regopt.baseline import summarize

    courses = load_courses()
    students = load_students()
    conflict_graph = build_conflict_graph(courses)

    assignment = solve_min_total_rank(students, courses, conflict_graph)

    first = students[0]
    print(f"{first.name} assigned: {assignment[first.name]}")

    print(summarize(assignment, students))