import networkx as nx
from itertools import combinations
from collections import defaultdict

from regopt.models import Course, Student


def build_preference_graph(students: list[Student], courses: dict[str, Course]) -> nx.Graph:
    """Bipartite graph. Student nodes and course nodes, distinguished by a
    'bipartite' node attribute (0/1) per networkx convention. Each edge
    carries a 'rank' attribute (1..10)."""
    G = nx.Graph()
    for course in courses.values():
        G.add_node(f"course:{course.id}", bipartite=1)
    for student in students:
        G.add_node(f"student:{student.name}", bipartite=0)
        for rank, course_id in enumerate(student.prefs, start=1):
            if course_id in courses:  # only add edges to valid courses
                G.add_edge(f"student:{student.name}", f"course:{course_id}", rank=rank)
    return G


def build_conflict_graph(courses: dict[str, Course]) -> nx.Graph:
    """Nodes = course ids. Edge between two courses iff they share a
    meeting block."""
    by_block = defaultdict(list)
    for course in courses.values():
        by_block[course.block].append(course.id)
    # by_block now looks like {"TuTh0945": ["90079", "90362", ...], "Mo0900": [...], ...}
    G = nx.Graph()
    G.add_nodes_from(courses.keys())  # every course is a node, even ones with no conflicts
    for block, ids in by_block.items():
        for id1, id2 in combinations(ids, 2):
            G.add_edge(id1, id2, block=block)
    return G


if __name__ == "__main__":
    from regopt.io import load_courses, load_students

    courses = load_courses()
    students = load_students()

    G = build_preference_graph(students, courses)
    expected = len(students) + len(courses)
    print(f"preference graph nodes: {G.number_of_nodes()} (expected {expected})")

    ava_node = "student:Ava Thompson"
    print(f"{ava_node} neighbors:")
    for course_node, data in G[ava_node].items():
        print(f"  rank {data['rank']}: {course_node}")

    # Once build_conflict_graph returns something, test it here too:
    # conflict = build_conflict_graph(courses)
    # print(conflict.has_edge("90079", "90362"))  # CSCI0201 & PSCI0103, both TuTh0945 -> True
