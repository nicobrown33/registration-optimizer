"""Build data/major_requirements.csv: which courses each major *requires*.

DISCLOSURE: the mapping below is invented (plausible approximations of
real requirements, not scraped from the catalog — the Banner export
carries no requirement data at all). What matters for the experiments is
its *shape*: requirements deliberately cross department lines, because
that's the case Nico called out — an ECON major must be able to get into
intro MATH, a BIOL major into intro CHEM. A policy that only boosts
"courses in your own department" misses exactly these.

Requirements live at the subject_course level (e.g. "MATH0121"), not the
CRN/section level: any section of MATH0121 satisfies the requirement.
Engines resolve subject_course -> CRNs via Course.subject_course.

Two sources, hand-picked first:
1. HAND_PICKED: ~17 majors with explicitly chosen requirement lists,
   emphasizing cross-department entries. Codes are validated against the
   real catalog; anything not offered this term is dropped with a warning.
2. Fallback for every other declared major: the two lowest-numbered
   courses under 0500 in the major's own department this term (0500+ are
   independent study / thesis numbers, never intro requirements).
"Undeclared" students have no major, hence no requirements.

Usage:  python preprocessing/build_major_requirements.py
Re-runnable; regenerates the CSV from scratch. No regopt import on
purpose, same as the other preprocessing scripts.
"""

import sys

import pandas as pd

COURSES_PATH = "data/courses_real.csv"
PREFERENCES_PATH = "data/preferences_real.csv"
OUT_PATH = "data/major_requirements.csv"

# major -> required subject_course codes (cross-department where natural)
HAND_PICKED: dict[str, list[str]] = {
    "ECON": ["ECON0150", "ECON0155", "MATH0121"],
    "CSCI": ["CSCI0145", "CSCI0200", "CSCI0201", "MATH0200"],
    "BIOL": ["BIOL0140", "BIOL0145", "CHEM0102"],
    "CHEM": ["CHEM0102", "MATH0121", "PHYS0109"],
    "PHYS": ["PHYS0109", "MATH0121", "MATH0122"],
    "NSCI": ["PSYC0105", "BIOL0145", "CHEM0102"],
    "MBBC": ["BIOL0145", "CHEM0102", "MATH0121"],
    "PSYC": ["PSYC0105", "STAT0116"],
    "MATH": ["MATH0121", "MATH0122", "MATH0200"],
    "STAT": ["STAT0116", "STAT0201", "MATH0121"],
    "ENVS": ["ENVS0112", "BIOL0140", "ECON0150"],
    "ECSC": ["ECSC0112", "MATH0121", "CHEM0102"],
    "GEOG": ["GEOG0100", "STAT0116"],
    "SOCI": ["SOCI0101", "STAT0116"],
    "IPEC": ["ECON0150", "ECON0155", "PSCI0109"],
    "GHLT": ["BIOL0140", "STAT0116"],
    "EDST": ["EDST0115", "PSYC0105"],
}

THESIS_NUMBER_FLOOR = 500  # course numbers >= 0500 are ind. study/thesis


def course_number(subject_course: str, department: str) -> int | None:
    """Numeric part of a code like 'MATH0121' -> 121; None if not numeric
    (a few real codes like 'MUSCJAZZ' have no number)."""
    tail = subject_course[len(department):]
    return int(tail) if tail.isdigit() else None


def main() -> None:
    catalog = pd.read_csv(COURSES_PATH, dtype=str, keep_default_na=False)
    offered = set(catalog["subject_course"])
    majors = sorted(pd.read_csv(PREFERENCES_PATH)["major"].unique())

    rows: list[dict[str, str]] = []
    for major in majors:
        if major == "Undeclared":
            continue

        if major in HAND_PICKED:
            required = []
            for code in HAND_PICKED[major]:
                if code in offered:
                    required.append(code)
                else:
                    print(f"warning: {major} requirement {code} not offered "
                          f"this term, dropped", file=sys.stderr)
        else:
            # Fallback: two lowest-numbered sub-0500 courses in own dept.
            dept_codes = {
                sc for sc, dept in zip(catalog["subject_course"],
                                       catalog["department"])
                if dept == major
            }
            numbered = [
                (num, sc) for sc in dept_codes
                if (num := course_number(sc, major)) is not None
                and num < THESIS_NUMBER_FLOOR
            ]
            required = [sc for _, sc in sorted(numbered)[:2]]
            if not required:
                print(f"warning: no catalog courses found for major {major}",
                      file=sys.stderr)

        rows.extend({"major": major, "subject_course": code}
                    for code in required)

    pd.DataFrame(rows).to_csv(OUT_PATH, index=False)
    n_majors = len({r["major"] for r in rows})
    print(f"wrote {len(rows)} (major, course) requirement pairs for "
          f"{n_majors} majors to {OUT_PATH}")


if __name__ == "__main__":
    main()
