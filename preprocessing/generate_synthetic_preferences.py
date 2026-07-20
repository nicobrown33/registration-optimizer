"""Generates data/preferences_real.csv: N fully synthetic students (names,
class year, major all invented) ranking real Fall 2026 courses from
data/courses_real.csv. Replaces whatever's currently in that file.

Preferences aren't uniform random — weighted by each course's real
`enrolled` count (so courses that are actually popular this term are also
popular in the synthetic rankings) and biased toward the student's own
major department and class-year-appropriate course level, so the result
looks like plausible registration demand rather than noise.

Re-run with a different --n or --seed to regenerate:
    python preprocessing/generate_synthetic_preferences.py --n 2000 --seed 0
"""

import argparse
import csv
import random

FIRST_NAMES = [
    "Ava","Marcus","Priya","Liam","Ines","Jamal","Yuki","Sofia","Devon","Chidinma",
    "Noah","Elena","Tomas","Grace","Owen","Fatima","Caleb","Zara","Lucas","Mei",
    "Benjamin","Ruth","Dylan","Amara","Hassan","Olivia","Kenji","Nadia","Ethan","Priyanka",
    "Diego","Freya","Isaiah","Mariam","Connor","Aaliyah","Felix","Ingrid","Malik","Sara",
    "Theo","Yara","Gabriel","Naomi","Rafael","Chloe","Amir","Leila","Oscar","Wren",
    "Julian","Zoe","Elias","Bianca","Kofi","Astrid","Rowan","Mila","Anders","Tanvi",
]
LAST_NAMES = [
    "Thompson","Idowu","Ramanathan","O'Connell","Duarte","Whitfield","Tanaka","Marchetti",
    "Marsh","Eze","Bergstrom","Petrova","Reyes","Nakamura","Fitzpatrick","Al-Sayed",
    "Whitmore","Hassan","Ferreira","Chow","Okafor","Alemayehu","Kowalski","Nguyen",
    "Osei","Larsson","Fontaine","Berg","Silva","Haddad","Volkov","Kim","Abara","Rossi",
    "Delacroix","Weiss","Okonkwo","Andersson","Castillo","Novak","Hansen","Popescu",
    "Diallo","Meyer","Suzuki","Klein","Moreau","Bakker","Costa","Lindqvist","Adeyemi",
]

CLASS_YEARS = ["First-Year", "Sophomore", "Junior", "Senior"]
CLASS_YEAR_TARGET_LEVEL = {"First-Year": 1, "Sophomore": 1, "Junior": 2, "Senior": 3}

UNDECLARED_PROB = {"First-Year": 0.9, "Sophomore": 0.6, "Junior": 0.05, "Senior": 0.00}


def is_labish(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in ["lab", "discussion", "recitation", "screening"])


def course_level(subject_course: str) -> int:
    """subject_course is like 'AMST0219' — the trailing digits are the
    course number; //100 gives a rough level (0219 -> 2)."""
    digits = "".join(ch for ch in subject_course if ch.isdigit())
    try:
        return int(digits) // 100
    except ValueError:
        return 1


def load_candidate_courses(path: str) -> list[dict]:
    rows = list(csv.DictReader(open(path)))
    return [
        r for r in rows
        if int(r["capacity"]) > 0 and not is_labish(r["title"])
    ]


def pick_major(rng: random.Random, courses: list[dict], class_year: str) -> str:
    if rng.random() < UNDECLARED_PROB[class_year]:
        return "Undeclared"
    dept_weights: dict[str, int] = {}
    for c in courses:
        dept_weights[c["department"]] = dept_weights.get(c["department"], 0) + int(c["enrolled"]) + 1
    depts = list(dept_weights.keys())
    weights = list(dept_weights.values())
    return rng.choices(depts, weights=weights, k=1)[0]


def pick_prefs(rng: random.Random, courses: list[dict], major: str, class_year: str, n: int = 10) -> list[str]:
    target_level = CLASS_YEAR_TARGET_LEVEL[class_year]
    weights = []
    for c in courses:
        w = int(c["enrolled"]) + 1
        if c["department"] == major:
            w *= 6  # students mostly pick courses in their own department
        level_distance = abs(course_level(c["subject_course"]) - target_level)
        w /= (1 + level_distance)  # prefer courses near the student's class-year level
        weights.append(w)

    chosen_idx = set()
    while len(chosen_idx) < n:
        idx = rng.choices(range(len(courses)), weights=weights, k=1)[0]
        chosen_idx.add(idx)
    # rng.choices with a set doesn't preserve draw order; re-rank by weight
    # (highest-weight pick = 1st choice) so preferences aren't arbitrary.
    ranked = sorted(chosen_idx, key=lambda i: weights[i], reverse=True)
    return [courses[i]["id"] for i in ranked]


def generate_name(rng: random.Random, used: set[str]) -> str:
    while True:
        name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if name not in used:
            used.add(name)
            return name


def generate_students(n: int, seed: int, courses_path: str) -> list[dict]:
    rng = random.Random(seed)
    courses = load_candidate_courses(courses_path)
    used_names: set[str] = set()

    students = []
    for _ in range(n):
        class_year = rng.choice(CLASS_YEARS)
        major = pick_major(rng, courses, class_year)
        prefs = pick_prefs(rng, courses, major, class_year)
        students.append({
            "name": generate_name(rng, used_names),
            "class_year": class_year,
            "major": major,
            **{f"rank{i+1}": prefs[i] for i in range(10)},
        })
    return students


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--courses", default="data/courses_real.csv")
    parser.add_argument("--out", default="data/preferences_real.csv")
    args = parser.parse_args()

    students = generate_students(args.n, args.seed, args.courses)

    fieldnames = ["name", "class_year", "major"] + [f"rank{i}" for i in range(1, 11)]
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(students)

    print(f"wrote {len(students)} synthetic students to {args.out}")


if __name__ == "__main__":
    main()
