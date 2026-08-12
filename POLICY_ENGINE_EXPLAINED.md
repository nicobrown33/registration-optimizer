# The Policy Engine, Explained

This document does two things, per your request: **Part 1** walks through
the exact reasoning that produced this design — what the research said,
what each decision was, and what alternatives were rejected and why.
**Part 2** breaks down every line of new code. **Part 3** shows what the
numbers came out to and how each claim was verified.

What was built, in one paragraph: instead of the guide's four fixed
optimization models, there is now one `Policy` object holding every
"slider" an IT department might want to set (seniority weights, an
equality dial, major-requirement priority, seat reservations, and so on),
and **two independent allocation engines that both consume the same
Policy** — an integer-linear-programming engine (`regopt/policy_ilp.py`)
that computes a centrally optimal allocation, and a Gale-Shapley
deferred-acceptance engine (`regopt/deferred_acceptance.py`) that
computes a stable, hard-to-game one. A neutral metrics harness
(`regopt/metrics.py`) scores any allocation on the same fixed scale, so
policies and engines can be compared honestly. `main.py` runs it all:

```
python main.py                     # all 6 presets x both engines, full tables
python main.py --preset rawlsian --engine ilp
python main.py --policy policies/balanced.json   # a policy is just a JSON file
```

---

# Part 1 — The thinking

## 1.1 Why the pivot happened

The guide's Milestones 4–7 build four models (min total rank, max first
choices, lexicographic rounds, max-min) and then ask "which is best?" —
and the honest answer is *none of them*, because "best" smuggles in a
value judgment about who deserves what. Your framing was the right one:
the program shouldn't decide whether seniors matter more than equality —
it should expose those choices as configuration and show each school what
its settings cost. So the target changed from "find the best algorithm"
to "build the machine that makes the trade-offs visible."

## 1.2 What the research actually said

Three sources shaped the design, each contributing one structural idea.

**Diebold, Bichler, Matthes, Schneider & Aziz (2014), "Course Allocation
via Stable Matching," Business & Information Systems Engineering 6(2)
— https://aisel.aisnet.org/bise/vol6/iss2/5/.** The paper's core claims:
first-come-first-served registration (what the baseline simulates, and
roughly what Middlebury runs) is neither **stable** (there can exist a
student and a course who would both prefer to be matched with each other
over what they got — a legitimate grievance) nor **strategy-proof**
(students can do better by lying about their preferences — ranking a
"safe" course first instead of their true favorite). The Gale-Shapley
student-optimal stable mechanism (SOSM) is both; EADAM recovers some
efficiency SOSM leaves behind, at the cost of strategy-proofness. The
idea taken from this paper is architectural: **in deferred acceptance,
the course-side priority order is a pluggable input.** The mechanism
never changes; who a full course keeps is policy. That's your sliders
concept, already formalized in the matching literature — so the DA
engine's priority function is built from the exact same Policy fields the
ILP uses as objective weights.

**Bowdoin's retired Polaris system** (replaced by Workday in spring
2025): students submitted *ranked requests* in batch rounds, and an
algorithm distributed seats following a **faculty-set per-course
"registration preference order" by class standing**. Idea taken:
course-side policy is real and institutional — it's not always about
weighting students globally; sometimes the course itself declares who it
serves. (The Bowdoin Orient's coverage also noted students learned to
game it — which is exactly the strategy-proofness failure the BISE paper
formalizes.)

**Wesleyan's current pre-registration**: students rank up to 7 courses,
a batch scheduler assigns up to 4, explicitly *not* first-come-first-
served and never into time conflicts, using per-course **"bins" — seat
quotas by class year and major** ("if the class year or major bin is
zero, students have lower priority for the course"). Afterward, the
add/drop adjustment phase admits students in order of **how few credits
they got** — the worst-off go first. Two ideas taken: the `seat_bins`
slider is Wesleyan's bins directly; and staggered-by-outcome access is
the same moral instinct as the equality dial and the past-outcome
compensation slider (the system should owe you more when it served you
worse).

**"Something lexicographical"** turned out to mean two different things,
and both are in the engine:
1. **Leximin/max-min fairness** — judge an allocation by its worst-off
   student. This is the far end of the `equality` dial.
2. **Lexicographic priority ordering** — a strict sequence: fully serve
   group 1, freeze, then serve group 2 with what's left. This is
   `priority_mode="tiers"`, and it matches how Middlebury's seniority
   actually behaves (a hard gate, not a tiebreaker — a senior registers
   before every sophomore, full stop, which is exactly how
   `baseline.py` already modeled it).

## 1.3 The central design move: policy ≠ mechanism

Everything hangs on one separation:

- A **Policy** is pure data — a dataclass of numbers and switches,
  serializable to JSON (`policies/*.json`). It contains *no algorithm*.
- An **engine** is pure mechanism — it takes students, courses, the
  conflict graph, and a Policy, and returns `{student: [course ids]}`.
  It contains *no institutional values*; every value judgment it applies
  comes in through the Policy.

This is what makes "the IT department picks what to prioritize" real:
handing a school this system means handing them a JSON schema, not a
codebase to fork. And because *both* engines consume the same Policy, a
school can also compare mechanisms while holding values fixed: "with our
exact priorities, what do we lose by switching from the optimal-but-
gameable ILP to the stable-and-honest matching mechanism?"

## 1.4 The cost function — your linear fairness score, made load-bearing

You proposed scoring students linearly: Bob got his 2nd and 5th choices,
so Bob's score is 2 + 5 = 7; compare against the average to see who was
treated worse. That instinct is the standard one, and it became the
system's backbone in three places:

1. **The ILP objective** minimizes exactly this score (weighted and
   discounted per policy — see below).
2. **The metrics module** reports it per student, plus its mean, spread
   (standard deviation and Gini coefficient), and worst case.
3. **Past-term compensation** feeds last term's version of the same
   score (`prior_avg_rank`, averaged rather than summed so it's
   comparable across course loads) back in as a priority boost.

It needed two repairs to not mislead:

- **Empty slots must cost something.** Under a pure sum, a student who
  got *only* their 2nd choice (score 2) looks better-treated than one
  who got a full schedule of ranks 1,2,2,3 (score 8) — the metric would
  reward being shut out. Fix: every unfilled slot charges
  `unassigned_penalty` (default 15, worse than any real rank), so a full
  mediocre schedule always beats a half-empty good one.
- **Linearity is itself an assumption** — it says dropping from 1st to
  2nd choice hurts exactly as much as dropping from 9th to 10th. Often
  the deep list is disproportionately worse. Rather than decide that for
  every school, it's a slider: `rank_cost_exponent`. At 1.0 the cost of
  your 5th choice is 5 (your linear system); at 2.0 it's 25, and the
  solver fights much harder to keep anyone off the deep list.

## 1.5 What each slider means and why it exists

| Slider | The institutional question it answers |
|---|---|
| `class_year_weights` | Do seniors' preferences count more? How much more? (All 1.0 = seniority abolished.) |
| `past_outcome_weight` | Does the system owe you for serving you badly last term? (Wesleyan's staggered adjustment, as a weight.) |
| `major_match_bonus` | Do majors get an edge in their own department's courses? |
| `requirement_weight` | Do students get an edge in courses **required for their major — including other departments'** (the econ-major-needs-MATH case you raised)? |
| `guarantee_requirement` | Is at least one required course a near-promise rather than a preference? |
| `priority_mode` | Is priority a thumb on the scale (`weights`) or a hard gate (`tiers`, Middlebury-style)? |
| `tier_order` | If a gate — who goes first? (This is literally "order of who gets priority" as a config list.) |
| `equality` | The dial from "minimize total misery, whoever bears it" (0) to "judge only by the worst-off student" (1). |
| `rawlsian_tiebreak` | At full equality, break ties among equally-fair allocations by total happiness. |
| `seat_bins` | Wesleyan's per-course reserved seats by class year / major — course-side policy, like Bowdoin's preference orders. |
| `rank_cost_exponent` | How much worse is the deep list than the top of the list? |
| `unassigned_penalty` | How bad is an empty slot compared to a bad course? |
| `k`, `seed` | Mechanics: schedule size; lottery reproducibility. |

Why *requirement* and *major-match* are separate sliders: your point
exactly. `major_match_bonus` fires when the course's department equals
the student's major — an affinity signal. But an econ major's graduation
path runs through intro MATH, which that test can never see. Requirements
therefore live in their own table (`data/major_requirements.csv`, major →
required course codes, deliberately crossing departments), with their own
weight. A school can favor either, both, or neither.

## 1.6 Decisions made and alternatives rejected

**`≤ k` plus a penalty, not `== k`.** The Milestone-4 model constrains
every student to exactly k courses. At 24 students that's fine; at 2,000
it's a time bomb — the *entire model* becomes infeasible the moment one
student's ten preferences can't produce k conflict-free seats, and CBC
just reports "Infeasible" with no allocation at all. The fix: allow up to
k, and charge `unassigned_penalty` per empty slot. Because the penalty
exceeds any real course's cost, the solver fills every slot it possibly
can — same behavior where feasible, graceful degradation where not.

**The equality dial as a blended objective, not pure leximin.** True
leximin (optimize the worst-off, then the 2nd-worst, then the 3rd…)
needs up to n sequential solves — thousands of CBC runs at this scale.
The blend `(1−λ)·(total weighted cost) + λ·n·(worst cost)` gets the whole
slider range in one solve, with λ=1 being exact max-min and
`rawlsian_tiebreak` adding the one extra solve that picks the best total
among the max-min optima (Milestone 7's two-phase idea). Full leximin
remains the honest "future work" note.

**The worst-case variable `z` bounds *unweighted* cost.** A subtle values
question hidden in the algebra: should "the worst-off student" be
measured after multiplying by their priority weight? No — worst-off means
worst actual experience. Consequence: at λ=1 the priority weights
genuinely stop mattering, which is exactly what a full-equality slider
should mean.

**Tiers freeze assignments, not objective values.** The alternative
(re-solve globally each round, constrained to keep earlier tiers'
*objective totals*) can Pareto-improve — a junior might swap into a seat
a senior doesn't mind trading away. It's also harder to explain to a
student ("your seat moved because round 3 found a better global
arrangement") and harder to implement. Frozen assignments match how
registration actually feels: when your window closes, your schedule is
yours. The Pareto-improving version is noted as future work.

**Seat bins as "reserved caps + shared open pool."** Each reserved group
may use its reserved seats plus the open remainder; students outside
every bin may use only the open remainder; the ordinary capacity
constraint stops two groups from double-spending the open pool. This is
the cleanest LP encoding of "seats held for a group" and mirrors the
matching-with-reserves idea on the DA side (fill each group's reserve
from its best members first, then fill open seats by overall priority).

**`guarantee_requirement` is a huge penalty, not a hard constraint.** A
hard "every eligible student gets a required course" constraint goes
infeasible if one student's required sections are all full or all
conflict — killing the whole allocation for everyone. A penalty of 100
per violation (vs. rank costs of 1–15) means the solver treats it as
hard whenever satisfiable and degrades gracefully when not. The penalty
only applies to students who actually *ranked* a required course — the
engine never assigns anything a student didn't rank, so for students who
didn't rank one there is nothing to press on (a real system might handle
those with advising instead).

**Metrics are policy-independent.** Each engine optimizes its
policy-shaped objective (weighted, discounted, exponent-curved). If the
report card used the same numbers, every policy would win on its own
scale and comparisons would be circular. So `metrics.py` scores every
run on one fixed scale: plain linear rank cost + fixed penalty 15 per
empty slot. The policies disagree about what *should* happen; the
yardstick doesn't.

**DA honesty note.** The BISE paper's stability and strategy-proofness
theorems cover the one-course-per-student model. Wanting k courses at
once, under time conflicts, makes this many-to-many matching with
complementarities — the guarantees weaken to "in the spirit of": the
implementation keeps tentative holds, bumping, and cutoffs that only
rise, but a determined student could still find edge cases. It is
substantially harder to game than FCFS (there is no clock to race and no
reward for ranking safe courses first at the top of your list), and
that's the honest claim.

---

# Part 2 — Every line of new code

Format: each file is broken into short excerpts, in order, with every
line accounted for. Where several adjacent lines are the same move
repeated (a list of dataclass fields, a run of dict entries), they're
explained as the group they are, then any line doing something extra
gets its own note.

## 2.1 `preprocessing/add_past_outcomes.py`

```python
import random
import sys

import pandas as pd
```
`random` supplies the seeded generator, `sys` reads the optional
command-line argument, `pandas` reads/writes the CSV. The blank line
between the first two and `pandas` is the standard-library-vs-third-party
grouping convention the rest of the repo uses.

```python
SEED = 42
WORST_PLAUSIBLE_AVG = 8.0
BEST_PLAUSIBLE_AVG = 1.0
```
Module constants, named so the *meaning* of the numbers is in the code.
`SEED` makes the "randomness" reproducible: rerunning the script yields
byte-identical output, so experiments don't shift under you. 1.0 and 8.0
bound the invented "average rank received last term": a student's ranks
run 1–10, but an *average* at the extremes is rare, so 8 is used as the
plausible worst. **These two numbers are mirrored by `PRIOR_BEST` /
`PRIOR_WORST` in `regopt/policy.py`** — that's the contract that lets the
policy layer normalize the column to a 0–1 scale.

```python
def main(path: str) -> None:
    df = pd.read_csv(path, dtype={f"rank{i}": str for i in range(1, 11)})
    rng = random.Random(SEED)
```
Line 1: the whole script as one function taking the CSV path. Line 2:
load the CSV, forcing the ten `rank1..rank10` columns to strings — CRNs
like `90079` are identifiers, not numbers, and letting pandas guess would
turn them into integers (identical dtype trick to `regopt/io.py`).
Line 3: a *local* `Random` instance rather than `random.seed(...)` — the
global generator stays untouched for any other code.

```python
    values: list[float | None] = []
    for class_year in df["class_year"]:
        if class_year == "First-Year":
            values.append(None)
        else:
            values.append(
                round(rng.uniform(BEST_PLAUSIBLE_AVG, WORST_PLAUSIBLE_AVG), 2)
            )
```
Build the new column value-by-value, in row order (which, with the fixed
seed, is what makes it deterministic). First-Years have no prior term, so
they get `None` — pandas writes that as an empty cell, and
`io.load_students` turns it back into `None`. Everyone else draws a
uniform value in [1, 8], rounded to 2 decimals so the CSV stays readable.

```python
    df["prior_avg_rank"] = values
    df.to_csv(path, index=False)
```
Attach the list as a new column and write the file back in place.
`index=False` stops pandas from adding its row-number index as a spurious
first column.

```python
    n_blank = sum(v is None for v in values)
    print(f"wrote prior_avg_rank to {path}: {len(values)} rows, "
          f"{n_blank} blank (First-Years), seed={SEED}")
```
`sum` over a generator of booleans counts the `True`s (True == 1) — the
same idiom the guide's Milestone 9 notes. The print is the script's
receipt: row count, blank count, and the seed, so a log of the run is
self-describing.

```python
if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/preferences_real.csv")
```
Standard entry-point guard; first CLI argument overrides the default
path, so the script can also be pointed at a different preferences file.

## 2.2 `preprocessing/build_major_requirements.py`

```python
import sys

import pandas as pd

COURSES_PATH = "data/courses_real.csv"
PREFERENCES_PATH = "data/preferences_real.csv"
OUT_PATH = "data/major_requirements.csv"
```
Imports as before; the three paths as named constants — this script is a
fixed pipeline step, not a general tool, so hardcoded-but-named is right.

```python
HAND_PICKED: dict[str, list[str]] = {
    "ECON": ["ECON0150", "ECON0155", "MATH0121"],
    "CSCI": ["CSCI0145", "CSCI0200", "CSCI0201", "MATH0200"],
    ...
    "EDST": ["EDST0115", "PSYC0105"],
}
```
The heart of the file: 17 majors mapped to required course *codes*
(not sections). Every line is one major; the deliberate pattern is that
most lists contain at least one **out-of-department** code — `ECON` needs
`MATH0121`, `NSCI` needs `PSYC0105`/`BIOL0145`/`CHEM0102`, `SOCI` needs
`STAT0116` — because that's precisely the case a naive "same department
as your major" bonus can't see. The choices are plausible approximations
of real Middlebury requirements, invented and disclosed as such.

```python
THESIS_NUMBER_FLOOR = 500
```
Course numbers ≥ 0500 at Middlebury are independent study / thesis
work — never intro requirements — so the fallback below refuses them.

```python
def course_number(subject_course: str, department: str) -> int | None:
    tail = subject_course[len(department):]
    return int(tail) if tail.isdigit() else None
```
Extracts `121` from `"MATH0121"` by slicing off the department prefix.
The `isdigit` guard exists because a few real codes have no number at all
(`MUSCJAZZ`, `MUSCORCH`) — those return `None` and are excluded.

```python
def main() -> None:
    catalog = pd.read_csv(COURSES_PATH, dtype=str, keep_default_na=False)
    offered = set(catalog["subject_course"])
    majors = sorted(pd.read_csv(PREFERENCES_PATH)["major"].unique())
```
Load the real catalog (all strings, blanks kept as `""` — same flags and
same reason as `io.load_courses`); collect the set of course codes
actually offered this term; list every distinct major that actually
appears among the 2,000 students, sorted so the output file is stable.

```python
    rows: list[dict[str, str]] = []
    for major in majors:
        if major == "Undeclared":
            continue
```
Accumulate output rows; Undeclared students have no major and therefore
no requirements — skipping them here means `load_major_requirements`
simply has no key for them, and callers use `.get(major, set())`.

```python
        if major in HAND_PICKED:
            required = []
            for code in HAND_PICKED[major]:
                if code in offered:
                    required.append(code)
                else:
                    print(f"warning: {major} requirement {code} not offered "
                          f"this term, dropped", file=sys.stderr)
```
Hand-picked majors: keep each code only if some section of it actually
runs this term; otherwise warn on **stderr** (so warnings never
contaminate stdout if the output were ever piped) and drop it.

```python
        else:
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
```
The fallback for the other ~35 majors. First set-comprehension: all
course codes whose department equals the major (majors in this dataset
*are* department codes, so this join is direct). Second: pair each code
with its number, using the walrus operator `:=` to compute
`course_number` once and test it in the same expression, keeping only
real, sub-0500 numbers. Third: sort the `(number, code)` tuples — tuples
sort by first element, so this is "lowest-numbered first" — and take two:
the department's two most introductory offerings stand in as its
requirements.

```python
            if not required:
                print(f"warning: no catalog courses found for major {major}",
                      file=sys.stderr)
```
A major with nothing suitable (INDE and LITS, whose only offerings this
term are 0500+) just ends up with no requirements, loudly.

```python
        rows.extend({"major": major, "subject_course": code}
                    for code in required)

    pd.DataFrame(rows).to_csv(OUT_PATH, index=False)
    n_majors = len({r["major"] for r in rows})
    print(f"wrote {len(rows)} (major, course) requirement pairs for "
          f"{n_majors} majors to {OUT_PATH}")
```
One output row per (major, code) pair — "long" form, the easiest shape
for pandas to read back. Then write, count distinct majors via a set
comprehension, and print the receipt. The `__main__` guard follows as in
every script.

## 2.3 The `models.py` / `io.py` changes

`models.py` — one addition to `Student`:
```python
    prior_avg_rank: float | None = None
```
Optional with a `None` default, so every existing call site that builds a
`Student` without it keeps working, and data files without the column
still load. The comment above it in the file points at the generating
script — the field is meaningless without knowing it's synthetic.

`io.py` — inside `load_students`:
```python
    has_prior = "prior_avg_rank" in df.columns
    ...
        prior = row["prior_avg_rank"] if has_prior else None
        if prior is not None and pd.isna(prior):
            prior = None
```
Backward compatibility, twice over: the column may be absent entirely
(old file → `None` for everyone), and where present, blank cells arrive
as `NaN` — `pd.isna` catches that and collapses it to `None`, so
downstream code has exactly one "no history" value to check, not two.
The `Student(...)` construction then passes `prior_avg_rank=prior` as a
keyword.

`io.py` — new loader:
```python
def load_major_requirements(
    path: str = "data/major_requirements.csv",
) -> dict[str, set[str]]:
    df = pd.read_csv(path, dtype=str)
    requirements: dict[str, set[str]] = {}
    for row in df.itertuples():
        requirements.setdefault(row.major, set()).add(row.subject_course)
    return requirements
```
Reads the long-form CSV back into the shape the engines want: major →
*set* of codes (sets because the only operations ever needed are
membership tests and intersections). `setdefault(key, set())` returns the
existing set or installs an empty one — the same "auto-create on first
touch" move as the guide's `defaultdict`, without importing it for one
use. Majors with no rows simply aren't keys; the docstring tells callers
to use `.get(major, set())`.

## 2.4 `regopt/policy.py`

```python
import json
from dataclasses import asdict, dataclass, field

from regopt.models import Course, Student
```
`json` for serialization, the three dataclass tools (`asdict` converts a
dataclass instance to a plain dict, `field` supplies per-field options
like default factories), and the two data types the helper functions
take.

```python
PRIOR_BEST = 1.0
PRIOR_WORST = 8.0
```
The mirror of the generator script's bounds (§2.1) — the two files agree
on the meaning of `prior_avg_rank` through these constants.

```python
GUARANTEE_PENALTY = 100.0
```
The "soft constraint that behaves hard" magnitude. Scale reasoning: real
per-course costs run 1–10 (ranks), empty slots cost 15, so one violated
guarantee at 100 dwarfs any rearrangement of ordinary costs — the solver
only accepts a violation when no feasible schedule can avoid it.

```python
CLASS_YEARS = ["Senior", "Junior", "Sophomore", "First-Year"]

def _equal_weights() -> dict[str, float]:
    return {year: 1.0 for year in CLASS_YEARS}
```
The canonical year list (seniority order — reused for tier defaults and
bins), and a *factory function* for the all-equal weights dict. It must
be a function because of the mutable-default-argument trap the guide's
refresher warns about: writing `= {...}` directly in the dataclass would
share one dict across every Policy instance, and mutating one policy's
weights would silently mutate them all. `field(default_factory=...)`
calls the factory once per instance.

The `Policy` dataclass itself — each field is one slider; the meaning
table lives in Part 1 §1.5, so here just the implementation notes:
```python
    class_year_weights: dict[str, float] = field(default_factory=_equal_weights)
    tier_order: list[str] = field(default_factory=lambda: list(CLASS_YEARS))
    seat_bins: dict[str, dict[str, int]] = field(default_factory=dict)
```
Every mutable-typed field uses `default_factory` (the trap above);
`tier_order`'s factory copies `CLASS_YEARS` via `list(...)` so a policy
that reorders its tiers doesn't rewrite the module constant. Scalar
fields (`major_match_bonus: float = 0.0` and friends) can take plain
defaults safely — floats and bools are immutable. The defaults as a set
are chosen so that **`Policy()` with no arguments is the neutral
policy**: nobody weighted, nothing discounted, no tiers, no equality
correction, no bins — every slider at "off."

```python
    def to_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def from_json(cls, path: str) -> "Policy":
        with open(path) as f:
            return cls(**json.load(f))
```
Serialization is what turns a Policy from "a Python object" into "a
config file an IT department edits." `asdict` recurses into the nested
dicts; `indent=2` makes the JSON diffable in git. Loading is the
reverse: parse the JSON into a dict, splat it into the constructor with
`**` — unknown keys fail loudly (a typo in a config file should not be
silently ignored), missing keys fall back to the field defaults.

```python
def prior_shortfall(student: Student) -> float:
    if student.prior_avg_rank is None:
        return 0.0
    span = PRIOR_WORST - PRIOR_BEST
    return max(0.0, min(1.0, (student.prior_avg_rank - PRIOR_BEST) / span))
```
Normalizes history to "how much does the system owe you," 0–1. `None`
(First-Years, missing column) → 0: no history, no debt. Otherwise a
linear rescale of [1, 8] onto [0, 1], with `max(0, min(1, ...))`
clamping in case a hand-edited file holds an out-of-range value —
defensive, because this multiplies into an objective.

```python
def student_weight(student: Student, policy: Policy) -> float:
    base = policy.class_year_weights.get(student.class_year, 1.0)
    return base * (1.0 + policy.past_outcome_weight * prior_shortfall(student))
```
The one number that says how much a student's happiness counts. Class
year sets the base (`.get(..., 1.0)` so an unexpected year string
degrades to neutral instead of crashing); the compensation term scales
it up — at `past_outcome_weight=0.5`, a student with the worst possible
prior term counts 1.5× a comparable student with a clean history.
Multiplicative composition means the two signals stack sensibly.

```python
def student_tier(student: Student, policy: Policy) -> int:
    try:
        return policy.tier_order.index(student.class_year)
    except ValueError:
        return len(policy.tier_order)
```
Position in the tier list (0 = served first). `list.index` raises
`ValueError` for a year not in the list; the except turns that into "one
past the end" — a catch-all last tier — so a partial `tier_order` like
`["Senior"]` means "seniors first, everyone else together after."

```python
def edge_cost(student, course, rank, policy, requirements):
    cost = float(rank) ** policy.rank_cost_exponent
    if course.department == student.major:
        cost -= policy.major_match_bonus
    if course.subject_course in requirements.get(student.major, set()):
        cost -= policy.requirement_weight
    return cost
```
The cost of one specific (student, course) match, before the student
weight multiplies it. Line 1 is the rank curved by the exponent slider
(`float(...)` so `**` never surprises with integer semantics). The two
`if`s are the two affinity discounts: same-department, and
on-the-requirement-list (looked up by *code*, so any section counts, and
via `.get` so majors without requirements are just "no discount"). The
result may go negative under large discounts — deliberately: negative
cost means the institution actively rewards this match, which is how
`graduation_first` drags requirement seats to the right students.

```python
def required_course_ids(student, courses, requirements):
    required_codes = requirements.get(student.major, set())
    return {
        c_id for c_id in student.prefs
        if c_id in courses and courses[c_id].subject_course in required_codes
    }
```
Resolves requirements from code-space into this student's *own ranked
CRNs* — the engine never assigns unranked courses, so only ranked
sections can carry the guarantee. The `c_id in courses` guard tolerates a
preference for a CRN missing from the catalog.

```python
def priority_score(student, course, policy, requirements, lottery):
    tier = -float(student_tier(student, policy)) \
        if policy.priority_mode == "tiers" else 0.0
    score = student_weight(student, policy)
    if course.department == student.major:
        score += policy.major_match_bonus
    if course.subject_course in requirements.get(student.major, set()):
        score += policy.requirement_weight
    return (tier, score, lottery)
```
The DA engine's course-side ranking, built from the same Policy fields
the ILP consumes — this symmetry is the whole "one policy, two
mechanisms" claim, in code. It returns a *tuple* because Python compares
tuples element-by-element: tier dominates absolutely (negated, since
tier 0 must sort *highest*), then the weighted-and-discounted score, then
the per-student lottery number as final tiebreak. In weights mode the
tier component is a constant 0.0 and decides nothing. Note the discounts
that *subtract* from ILP cost *add* to DA score — both directions mean
"prefer this match."

```python
def make_class_year_bins(courses, fraction=0.2):
    bins = {}
    for c_id, course in courses.items():
        per_year = int(course.capacity * fraction)
        if per_year >= 1:
            bins[c_id] = {year: per_year for year in CLASS_YEARS}
    return bins
```
Convenience builder for the Wesleyan preset: reserve 20% of every
course's seats for each class year (4 × 20% reserved, 20% open).
`int(...)` truncates; the `>= 1` guard skips courses too small for a
whole reserved seat per year (tiny seminars stay fully open rather than
getting meaningless zero-bins).

The six `preset_*` functions each return one configured `Policy` with a
`name` matching its registry key; their institutional meaning is in each
docstring and Part 1. Implementation notes: all take an optional
`courses` argument they may ignore — the uniform signature lets `main.py`
call `factory(courses)` without caring which preset needs the catalog
(only `wesleyan_like` does, to build bins). The closing `PRESETS` dict
maps CLI names to factories — adding a preset is one function plus one
entry.

## 2.5 `regopt/policy_ilp.py`

```python
from itertools import combinations

import networkx as nx
import pulp

from regopt.models import Course, Student
from regopt.policy import (
    GUARANTEE_PENALTY, Policy, edge_cost, required_course_ids,
    student_tier, student_weight,
)
```
`combinations` for conflict pairs (the Milestone 2/4 pattern), `pulp` is
the ILP layer, and the policy helpers are imported by name — the engine
never reaches into Policy internals beyond these functions plus plain
fields, which keeps the policy/mechanism boundary honest.

```python
def _in_group(student: Student, group: str) -> bool:
    return student.class_year == group or student.major == group
```
Bin-group membership: a bin key is either a class year or a major code,
so one string test each. (A student can match at most one of the two —
class years and department codes don't collide.)

### `_build_model` — everything except the objective

Why this function exists: the Rawlsian tiebreak needs a *second* solve
over the *same* constraints. If both solves built constraints
independently, any future edit could change one and not the other —
they'd drift. One builder, called twice, makes drift impossible.

```python
    prob = pulp.LpProblem(name, pulp.LpMinimize)
```
A fresh minimization problem (a *new* problem object per solve — the
guide's Milestone 6 warning about reusing PuLP problems applies).

```python
    x = {
        s.name: {
            c_id: pulp.LpVariable(f"x_{i}_{c_id}", cat="Binary")
            for c_id in s.prefs
            if c_id in courses and remaining_cap.get(c_id, 0) > 0
        }
        for i, s in enumerate(group)
    }
```
The decision variables, as a two-level dict: `x[student_name][course_id]`
is a binary "does this student get this course." Only pairs the student
*ranked* get a variable (the Milestone 4 economy — ~20k variables instead
of ~3.7M), and courses with no seats left are skipped too — that second
filter is what keeps the tier rounds small, since a course seniors
drained generates no variables at all for the sophomore round. Variables
are named by the student's *index* `i` rather than their name — names
contain spaces and could in principle collide; an index can't do either.

```python
    cost_expr = {}
    for s in group:
        terms = []
        for c_id, var in x[s.name].items():
            rank = s.prefs.index(c_id) + 1
            cost = edge_cost(s, courses[c_id], rank, policy, requirements)
            terms.append(var * (cost - policy.unassigned_penalty))
        cost_expr[s.name] = policy.unassigned_penalty * policy.k + pulp.lpSum(terms)
```
Each student's cost as a linear expression, exactly the Part 1 §1.4
score. The algebra deserves spelling out: "cost of what you got + 15 per
empty slot" equals "15·k, minus 15 per filled slot, plus the edge cost of
each filled slot" — i.e. the constant `penalty * k` plus, per assignment,
`(edge_cost − penalty)`. That coefficient is always negative (penalty
exceeds any edge cost), so every assignment strictly improves the
objective and the solver never leaves a fillable slot empty.
`s.prefs.index(c_id) + 1` converts list position to 1-based rank
(Milestone 4's helper idiom); `edge_cost` applies the exponent and the
two discounts.

```python
    guarantee_expr = 0
    if policy.guarantee_requirement:
        penalties = []
        for i, s in enumerate(group):
            req_ids = required_course_ids(s, courses, requirements)
            req_vars = [x[s.name][c] for c in req_ids if c in x[s.name]]
            if not req_vars:
                continue
            got_req = pulp.LpVariable(f"req_{i}", cat="Binary")
            prob += got_req <= pulp.lpSum(req_vars)
            penalties.append(1 - got_req)
        guarantee_expr = GUARANTEE_PENALTY * pulp.lpSum(penalties)
```
The near-hard requirement guarantee. Per eligible student: gather the
variables for their ranked required sections (`if c in x[s.name]` filters
out sections dropped by the zero-capacity filter above); skip students
with none (nothing attainable to press on). Otherwise mint an indicator
variable `got_req` with the one-way constraint `got_req ≤ Σ req_vars`:
the solver may only set it to 1 if at least one required section is
assigned. Minimization then pushes `got_req` up (each `1 − got_req` in
the objective costs 100 while it's 0), which drags some required section
in — unless doing so is impossible, in which case the model stays
feasible and just eats the penalty. That one-way trick — indicator
bounded by a sum, objective pressure supplying the other direction — is
the standard way to encode "reward achieving X" without hard constraints.
`guarantee_expr` starts as plain `0` so the no-guarantee case adds
nothing to the objective and no variables to the model.

```python
    for s in group:
        prob += pulp.lpSum(x[s.name].values()) <= policy.k
        for c1, c2 in combinations(x[s.name].keys(), 2):
            if conflict_graph.has_edge(c1, c2):
                prob += x[s.name][c1] + x[s.name][c2] <= 1
```
Per student: at most k courses (`≤`, not `==` — Part 1 §1.6), and for
every pair of their ranked courses that share a time block, at most one
of the two — the Milestone 4 conflict scope (pairs within one student's
list, never across the whole catalog).

```python
    ranked_ids = {c_id for s in group for c_id in x[s.name]}
    for c_id in ranked_ids:
        takers = [s for s in group if c_id in x[s.name]]
        prob += pulp.lpSum(x[s.name][c_id] for s in takers) <= remaining_cap[c_id]
```
Capacity: only courses somebody in this group ranked need a constraint;
`takers` is everyone with a variable for the course; their sum can't
exceed the seats this solve is allowed to hand out (`remaining_cap`, not
`course.capacity` — in tier rounds those differ).

```python
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
```
The Wesleyan bins, encoded per Part 1 §1.6: `open_seats` is capacity not
reserved by anyone (clamped at 0 in case earlier tiers left less capacity
than the bins promise); each reserved group may take its reservation plus
open seats; students matching *no* bin may take only open seats; and the
plain capacity constraint above prevents the open pool being spent twice.
The `if members:` / `if outsiders:` guards skip constraints over empty
sums — harmless mathematically, noise in the model otherwise.

### `_solve_group` — objective, solve, tiebreak, bookkeeping

```python
    prob, x, cost_expr, guarantee_expr = _build_model(...)
    lam = policy.equality
    total_term = pulp.lpSum(
        student_weight(s, policy) * cost_expr[s.name] for s in group
    )
    objective = (1 - lam) * total_term + guarantee_expr
```
Build the shared model, then the objective's utilitarian half: each
student's cost expression scaled by their policy weight, summed. The
guarantee term rides outside the λ blend — a school that wants both full
equality *and* the requirement guarantee shouldn't have λ=1 silently
erase the guarantee.

```python
    z = None
    if lam > 0:
        z = pulp.LpVariable("z_worst_cost", lowBound=0, cat="Continuous")
        for s in group:
            prob += z >= cost_expr[s.name]
        objective += lam * len(group) * z
    prob += objective
```
The Rawlsian half, only materialized when the dial is actually turned
(λ=0 skips 2,000 constraints). `z` is continuous with a floor of 0; one
constraint per student forces it to sit at or above *every* student's
cost, so minimizing it minimizes the maximum — Milestone 7's exact
construction. It bounds **unweighted** cost (the values call in Part 1
§1.6). The `len(group)` scaling puts the two halves on comparable
magnitude (a sum over n students vs. one worst case), making λ=0.5 a real
midpoint rather than a rounding error. Finally `prob += objective` — the
first bare (non-inequality) expression added to a PuLP problem becomes
*the* objective, per the guide's PuLP crash course.

```python
    solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=time_limit)
    prob.solve(solver)
    status = pulp.LpStatus[prob.status]
    if status not in ("Optimal", "Not Solved"):
        raise RuntimeError(f"ILP for policy {policy.name!r} ended {status}")
```
CBC with its console spew silenced (`msg=0` — otherwise the comparison
tables drown in solver logs) and a time cap. Status discipline per
Milestone 4's warning — but "Not Solved" (the time-limit status) is
tolerated: CBC still returns its best incumbent solution, and a good
allocation now beats a perfect one never. Anything else ("Infeasible",
"Unbounded") is a real bug and raises.

```python
    if lam == 1.0 and policy.rawlsian_tiebreak and z is not None:
        z_star = z.value()
        prob2, x2, cost_expr2, guarantee_expr2 = _build_model(...)
        for s in group:
            prob2 += cost_expr2[s.name] <= z_star + 1e-6
        prob2 += pulp.lpSum(
            student_weight(s, policy) * cost_expr2[s.name] for s in group
        ) + guarantee_expr2
        prob2.solve(solver)
        if pulp.LpStatus[prob2.status] == "Optimal":
            x = x2
```
The two-phase Rawlsian tiebreak (Milestone 7's hint, realized): read the
optimal worst case `z*`, rebuild the *whole* model fresh through the same
builder (so bins, conflicts, and the guarantee all still hold), cap every
student's cost at `z*` (`+ 1e-6` of float slack — solver arithmetic isn't
exact), and minimize the plain utilitarian objective among allocations
that never exceed the fairness optimum. If the second solve succeeds, the
assignment is read from its variables (`x = x2`); if not, the first
solution stands.

```python
    assignment = {
        s.name: [c for c, var in x[s.name].items()
                 if var.value() is not None and var.value() > 0.5]
        for s in group
    }
```
Extraction, with both PuLP gotchas: `> 0.5` because binaries come back as
floats like `0.9999999`, and the `is not None` guard because a
time-limited solve can leave variables valueless.

```python
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
```
Seat bookkeeping for the next tier: decrement general capacity per
assignment, then shrink each bin by the seats its group's members took
(a member's seat consumes the reservation first; `max(0, ...)` because a
group can take more than its reservation via the open pool, and a
reservation can't go negative). In weights mode there is no next solve
and this is harmless. This mutation is the *point* of these two dicts —
they're the thread connecting tier rounds, the explicit-copy pattern
Milestone 3 uses for `remaining_seats`.

```python
def solve_policy_ilp(students, courses, conflict_graph, policy,
                     requirements=None, time_limit=300):
    requirements = requirements or {}
    remaining_cap = {c_id: c.capacity for c_id, c in courses.items()}
    remaining_bins = {
        c_id: dict(groups) for c_id, groups in policy.seat_bins.items()
    }
```
The public entry point. `requirements or {}` gives the no-requirements
default (the falsy-`None` idiom); fresh capacity dict copied off the
`Course` objects (never mutate the catalog — Milestone 3's warning); and
the bins are copied **one level deep on purpose** (`dict(groups)` per
course) — the solver decrements individual bin counts, and mutating
`policy.seat_bins` itself would corrupt the Policy across runs.

```python
    if policy.priority_mode != "tiers":
        return _solve_group(students, ...)

    assignment: dict[str, list[str]] = {}
    tiers: dict[int, list[Student]] = {}
    for s in students:
        tiers.setdefault(student_tier(s, policy), []).append(s)
    for tier_index in sorted(tiers):
        assignment.update(_solve_group(tiers[tier_index], ...))
    return assignment
```
Weights mode: one solve, everybody. Tiers mode: bucket students by tier
index (the `setdefault` grouping idiom again), then solve in ascending
tier order — each `_solve_group` call sees only the capacity its
predecessors left behind, and `assignment.update` merges the rounds.
That ordering **is** the lexicographic hard gate: nothing a later tier
does can touch an earlier tier's seats.

## 2.6 `regopt/deferred_acceptance.py`

```python
import random
from collections import deque

import networkx as nx

from regopt.models import Course, Student
from regopt.policy import Policy, priority_score
```
`deque` gives O(1) pops from the left for the proposal queue. Note the
engine imports exactly *one* policy function — `priority_score`. The
entire institutional value system enters this mechanism through that
single door.

### `_course_choice` — who does a full course keep?

```python
    def score(s: Student):
        return priority_score(s, course, policy, requirements, lottery[s.name])

    ranked = sorted(candidates, key=score, reverse=True)
```
A closure binding the course and policy so `sorted` can rank candidates;
`reverse=True` puts the highest-priority student first (tuple comparison:
tier, then score, then lottery — §2.4).

```python
    bins = policy.seat_bins.get(course.id)
    if not bins:
        return {s.name for s in ranked[: course.capacity]}
```
No bins: the choice function is simply "top `capacity` by priority" — a
list slice of the sorted candidates, returned as a set of names (the
caller does set arithmetic to find who got bumped).

```python
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
```
With bins: matching-with-reserves. Walk candidates best-first; `next()`
with a generator and a `None` default finds the first bin this student
belongs to that still has reservation left. Students claiming a live
reservation are accepted immediately (up to physical capacity); everyone
else — wrong group, or their bin already full — falls into `leftovers`,
still in priority order. Then whatever capacity remains fills from the
leftovers by open priority. Same semantics as the ILP's bin constraints,
expressed as a selection procedure instead of inequalities.

### `solve_deferred_acceptance` — the mechanism

```python
    by_name = {s.name: s for s in students}
    rng = random.Random(policy.seed)
    lottery = {s.name: rng.random() for s in students}
```
A name→Student lookup (course holds store names), and **one** lottery
number per student for the whole run — a single campus-wide lottery like
Wesleyan's randomized ordering, not a fresh coin flip per course, so ties
break consistently everywhere and reruns with the same seed reproduce
exactly.

```python
    holds: dict[str, set[str]] = {s.name: set() for s in students}
    course_holds: dict[str, set[str]] = {c_id: set() for c_id in courses}
    rejected: dict[str, set[str]] = {s.name: set() for s in students}
```
The three state tables: what each student tentatively holds, who each
course tentatively holds (the same facts indexed both ways), and which
courses have rejected/bumped each student. The `rejected` table encodes
the key theoretical fact making this terminate: a course's candidate pool
only ever grows, so its cutoff only rises — once rejected, re-proposing
can never succeed, so each (student, course) proposal happens at most
once, bounding the whole run at n×10 proposals.

```python
    queue = deque(students)
    while queue:
        student = queue.popleft()
        mine = holds[student.name]
        for c_id in student.prefs:
            if len(mine) >= policy.k:
                break
```
Process students until nobody needs anything. Each turn scans the
student's preference list top-down, stopping the moment their schedule is
full — so students always chase the best courses they might still get.

```python
            if (c_id not in courses or courses[c_id].capacity <= 0
                    or c_id in mine or c_id in rejected[student.name]):
                continue
            if any(conflict_graph.has_edge(c_id, held) for held in mine):
                continue
```
Skip rules: unknown CRN, zero-capacity section (real reserved sections
exist in the catalog), already held, already rejected. Then the conflict
skip — against *current* holds, which matters: if a held course is bumped
away later, this student re-enters the queue, re-scans from the top, and
a course previously skipped for conflicting gets a second chance.

```python
            pool = [by_name[n] for n in course_holds[c_id]] + [student]
            accepted = _course_choice(pool, courses[c_id], policy,
                                      requirements, lottery)
            if student.name not in accepted:
                rejected[student.name].add(c_id)
                continue
```
The proposal: current holders plus the proposer go through the choice
function together — "deferred" acceptance means holders enjoy no tenure;
they're re-evaluated against every newcomer. A proposer who doesn't make
the cut is rejected permanently (the monotone-cutoff fact above) and the
scan moves to their next choice.

```python
            for bumped_name in course_holds[c_id] - accepted:
                holds[bumped_name].discard(c_id)
                rejected[bumped_name].add(c_id)
                queue.append(by_name[bumped_name])
            course_holds[c_id] = accepted
            mine.add(c_id)
```
A successful proposal may displace someone: set difference finds the
bumped, who lose the hold, are marked rejected there, and rejoin the
queue to hunt further down their lists (duplicate queue entries are
harmless — a student with a full schedule scans and does nothing). Both
state tables update; the scan continues for the proposer's remaining
slots.

```python
    return {s.name: sorted(holds[s.name], key=s.prefs.index)
            for s in students}
```
When the queue empties, tentative holds become final — that's deferred
acceptance. Each student's course list is sorted by their own preference
order (`key=s.prefs.index`) purely for human-readable output.

## 2.7 `regopt/metrics.py`

```python
UNASSIGNED_COST = 15.0
K = 4
```
The yardstick's own constants, deliberately **not** read from any policy
(the circularity argument, Part 1 §1.6). Every allocation ever produced
is scored with slot penalty 15 against a 4-slot schedule, full stop.

```python
def student_cost(student: Student, assigned: list[str]) -> float:
    ranks = [student.prefs.index(c_id) + 1 for c_id in assigned]
    return sum(ranks) + UNASSIGNED_COST * (K - len(ranks))
```
Your linear score, verbatim: sum the ranks of what they got, add 15 per
missing course. The floor is 10 (a perfect 1+2+3+4); an empty schedule
scores 60.

```python
def gini(values: list[float]) -> float:
    xs = sorted(values)
    n = len(xs)
    total = sum(xs)
    if n == 0 or total == 0:
        return 0.0
    weighted = sum(i * x for i, x in enumerate(xs, start=1))
    return (2 * weighted) / (n * total) - (n + 1) / n
```
The Gini coefficient via the sorted-array identity (O(n log n), no n²
pair loop): sort ascending, weight each value by its 1-based position —
the more the big values cluster at the top positions, the bigger the
weighted sum — then normalize so "all equal" gives 0 and "one student
bears everything" approaches 1. The guard returns 0 for empty or all-zero
input (degenerate but defined).

```python
def compute_metrics(assignment, students, courses, requirements=None):
    requirements = requirements or {}
    rows = []
    for s in students:
        for c_id in assignment.get(s.name, []):
            rows.append({"student": s.name,
                         "rank": s.prefs.index(c_id) + 1})
    df = pd.DataFrame(rows)
    costs = [student_cost(s, assignment.get(s.name, [])) for s in students]
    cost_series = pd.Series(costs)
```
Milestone 9's long-form pattern: one row per (student, assigned course)
with its rank, letting pandas aggregate; `assignment.get(s.name, [])`
tolerates engines omitting a student entirely. Costs are computed per
student (including the shut-out, who has no rows in `df` but a very real
cost of 60) and wrapped in a Series for `.mean()/.median()/.std()`.

```python
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
```
The requirement-access metric your econ-needs-math point demanded: among
students who *ranked* at least one section satisfying one of their
major's requirements, what fraction received one? Set intersection (`&`)
between ranked-required CRNs and assigned CRNs answers "got at least
one." Students who ranked none are excluded from the denominator — the
allocator can't be blamed for a list it never saw.

The return dict computes each headline number, with `if not df.empty`
guards so a pathological empty allocation yields NaN/0 instead of
crashing; `(df["rank"] == 1).mean()` is the bool-mean-as-proportion idiom
from the guide's Milestone 9 notes.

```python
def class_year_breakdown(assignment, students):
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
    order = ["Senior", "Junior", "Sophomore", "First-Year"]
    return out.reindex([y for y in order if y in out.index])
```
One row per student with their year, cost, course count, and a
got-first-choice flag; `groupby("class_year").agg` with named
aggregations produces the per-year table (the fill-rate lambda: total
courses received over total slots available to that year). `reindex`
forces seniority order — alphabetical would put First-Year first and make
every table harder to read; the comprehension keeps it robust if a year
is absent from a filtered dataset.

```python
def comparison_table(runs, students, courses, requirements=None):
    records = []
    for (policy_name, engine), assignment in runs.items():
        m = compute_metrics(assignment, students, courses, requirements)
        records.append({"policy": policy_name, "engine": engine, **m})
    return pd.DataFrame(records).set_index(["policy", "engine"])
```
The headline table: score every run, splat the metrics dict into a row
alongside its identifiers (`**m`), and set a two-level index so the
printed table groups engines under each policy.

## 2.8 `main.py`

```python
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
```
The module docstring doubles as `--help` text; `RawDescriptionHelpFormatter`
stops argparse from re-wrapping it into soup. The eight `add_argument`
calls each map to one CLI flag: `--preset` (default `"all"`), `--policy`
(a JSON file path — the "IT department hands you a config" path),
`--engine` with `choices=` validation, `--k`/`--seed` overrides (default
`None`, meaning "don't override"), `--limit` for fast experiments,
`--time-limit` forwarded to CBC, and the `--export-presets`
`store_true` flag.

```python
def selected_policies(args, courses) -> list[Policy]:
    if args.policy:
        policies = [Policy.from_json(args.policy)]
    elif args.preset == "all":
        policies = [factory(courses) for factory in PRESETS.values()]
    else:
        policies = [PRESETS[args.preset](courses)]
    for pol in policies:
        if args.k is not None:
            pol.k = args.k
        if args.seed is not None:
            pol.seed = args.seed
    return policies
```
Resolution order: an explicit JSON file wins; otherwise "all" expands
every preset factory (passing `courses`, which only `wesleyan_like`
uses); otherwise the one named preset. CLI overrides are applied *after*
construction so they beat whatever the preset or file said — the
`is not None` test distinguishes "flag absent" from a legitimate 0.

```python
def main() -> None:
    args = parse_args()
    courses = load_courses()
    students = load_students()
    if args.limit:
        students = students[: args.limit]
    conflict_graph = build_conflict_graph(courses)
    requirements = load_major_requirements()
```
Load everything once, up front; slicing students implements `--limit`;
the conflict graph and requirements are shared by every run.

```python
    if args.export_presets:
        os.makedirs("policies", exist_ok=True)
        for name, factory in PRESETS.items():
            path = os.path.join("policies", f"{name}.json")
            factory(courses).to_json(path)
            print(f"wrote {path}")
        return
```
The export mode: materialize every preset as a JSON file under
`policies/` (`exist_ok=True` makes reruns idempotent) and exit — these
files are the templates a school would copy and edit.

```python
    runs: dict[tuple[str, str], dict[str, list[str]]] = {}
    priority_order = compute_priority_order(students)
    runs[("baseline_fcfs", "serial")] = run_baseline(
        students, courses, conflict_graph, priority_order)
```
The anchor row: the untouched Milestone 3 simulation of today's system
(seniority gate, randomized within-tier order, occasional instructor
overrides), keyed like every other run so it lands in the same tables.

```python
    for pol in policies:
        for engine in engines:
            print(f"running {pol.name} / {engine} ...", flush=True)
            if engine == "ilp":
                assignment = solve_policy_ilp(...)
            else:
                assignment = solve_deferred_acceptance(...)
            runs[(pol.name, engine)] = assignment
```
The experiment grid. `flush=True` matters because CBC solves can take a
while — without it the progress line sits in the buffer and the program
looks hung.

```python
    pd.set_option("display.width", 200)
    print("\n=== Comparison ... ===")
    table = comparison_table(runs, students, courses, requirements)
    print(table.round(3).to_string())
```
Widen pandas' print limit so the 13-column table doesn't wrap;
`.round(3)` for legibility; `.to_string()` prints every row and column
(the default `print(df)` elides).

```python
    year_rows = {}
    for key, assignment in runs.items():
        breakdown = class_year_breakdown(assignment, students)
        year_rows[key] = breakdown["avg_cost"]
    print(pd.DataFrame(year_rows).T.round(2).to_string())
```
The second table pivots the per-run class-year breakdowns into one frame:
each run contributes its `avg_cost` column, keyed by `(policy, engine)`;
building the DataFrame from that dict makes runs the *columns*, so `.T`
transposes to runs-as-rows, years-as-columns — the layout where the
seniority skew (or its erasure) reads left to right.

```python
    if args.chart:
        from regopt.viz import plot_rank_distribution
        preferred = "ilp" if args.engine in ("ilp", "both") else "da"
        chart_runs = {
            ("baseline (today's FCFS)" if pol == "baseline_fcfs" else pol): a
            for (pol, engine), a in runs.items()
            if engine in ("serial", preferred)
        }
        plot_rank_distribution(chart_runs, students, args.chart, subtitle=...)
```
The optional chart hook: import inside the branch so matplotlib only
loads when asked; keep one row per *policy* by filtering to the baseline
plus a single engine's runs (ILP when available, since it's the
policy-expression benchmark; DA when it's all that was run); relabel the
baseline key for humans. The `__main__` guard closes the file.

## 2.9 `regopt/viz.py`

Design decisions first, because they're not arbitrary (they follow the
data-viz method, and the ramp was machine-validated, not eyeballed):

- **Form**: one horizontal 100%-stacked bar per run. The question is
  part-to-whole ("of all 8,000 slots, how many landed at each preference
  depth?") across long-named categories — the textbook case for
  horizontal stacked bars.
- **Color**: the buckets (1st, 2nd, 3rd, 4th–10th) are *ordered*, so
  they get a single-hue ordinal ramp — dark blue = best, lighter =
  deeper in the list — **not** four unrelated hues. The ramp
  (`#184f95 → #2a78d6 → #5598e7 → #86b6ef`) passed the palette
  validator's ordinal checks (monotone lightness, single hue, adjacent
  step gaps, light end ≥ 2:1 against the surface). "No course" is
  deliberately **outside** the ramp — neutral gray `#898781` — because
  absence is not a fifth rank, and a gray endpoint on a blue ramp reads
  as "nothing," the same reasoning as a diverging scale's gray midpoint.

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
```
`Agg` is matplotlib's render-to-file backend, selected *before* pyplot
loads — the script then works over SSH/CI with no display attached.

```python
BUCKETS = ["1st choice", "2nd", "3rd", "4th–10th", "no course"]
RAMP = ["#184f95", "#2a78d6", "#5598e7", "#86b6ef"]
NO_COURSE = "#898781"
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
```
The buckets and every color as named module constants — the palette
roles (surface, primary/secondary/muted ink, hairline grid, baseline)
come straight from the reference palette's chrome table, so text is
always ink-colored, never series-colored. Bucketing past 3rd into one
segment is deliberate: the reader's question deep in the list is "how
deep?", not "exactly which rank?".

```python
def bucket_shares(assignment, students):
    counts = [0] * len(BUCKETS)
    for s in students:
        got = assignment.get(s.name, [])
        for c_id in got:
            rank = s.prefs.index(c_id) + 1
            if rank <= 3:
                counts[rank - 1] += 1
            else:
                counts[3] += 1
        counts[4] += K - len(got)
    total = len(students) * K
    return [c / total for c in counts]
```
Turns an assignment into five fractions that sum to 1: ranks 1–3 to
their own buckets, everything deeper to the fourth, and — the part a
naive version forgets — each student's *missing* slots (`K - len(got)`)
to "no course," so a policy that fills fewer schedules can't look better
by omission. Dividing by `n*K` makes rows comparable across runs.

`plot_rank_distribution` walks through in order:

```python
    labels = list(runs)
    shares = {label: bucket_shares(runs[label], students) for label in labels}
```
`list(runs)` keeps the caller's insertion order — the story order
(baseline first, then presets) is the caller's to choose.

```python
    plt.rcParams["font.family"] = ["Helvetica Neue", "Arial", "sans-serif"]
    fig_h = 1.1 + 0.52 * len(labels)
    fig, ax = plt.subplots(figsize=(9.6, fig_h), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
```
System sans per the method's type rule; figure height *derived from row
count* so bars stay the same thickness however many runs are plotted;
dpi 200 for a crisp PNG; both figure and axes painted the chart surface.

```python
    colors = RAMP + [NO_COURSE]
    ys = range(len(labels) - 1, -1, -1)
    for y, label in zip(ys, labels):
        left = 0.0
        for share, color in zip(shares[label], colors):
            ax.barh(y, share, left=left, height=0.55, color=color,
                    edgecolor=SURFACE, linewidth=1.4)
            left += share
```
The stacking loop. Matplotlib's y-axis grows upward, so `ys` counts
*down* to put the first run at the top where a reader starts. Each
segment is drawn at the running `left` offset; `height=0.55` keeps the
marks thin, and the surface-colored edge (`linewidth=1.4` at this dpi ≈
a 2px gap) is the spacer that separates stacked segments — the method's
"2px surface gap between fills," done with an edge instead of geometry.

```python
        first = shares[label][0]
        ax.text(first / 2, y, f"{first:.0%}", va="center", ha="center",
                color="#ffffff", fontsize=8.5)
        none_share = shares[label][4]
        if none_share >= 0.002:
            ax.text(1.005, y, f"{none_share:.1%} none", va="center",
                    ha="left", color=INK_SECONDARY, fontsize=8)
```
Selective direct labels — the two numbers each row is *about*, not a
number on every segment: the 1st-choice share centered inside its dark
segment (white ink clears `#184f95` comfortably), and the shutout share
just past the bar's right end, in secondary ink, skipped entirely when
it rounds to nothing (a "0.0% none" label would be noise).

```python
    ax.set_yticks(list(ys)); ax.set_yticklabels(labels, ...)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", ...], fontsize=8.5, color=INK_MUTED)
    ax.set_xlabel("share of all schedule slots", ...)
```
Row names in primary ink at readable size; the x-axis pinned to exactly
[0, 1] (a 100%-stack that doesn't end at 100% is lying); quarter ticks
in muted ink — axis chrome stays recessive.

```python
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(length=0)
```
Recessive chrome: hairline vertical gridlines *behind* the bars
(`set_axisbelow`), three of matplotlib's four default box sides removed,
the remaining bottom spine as the baseline, tick marks (the little
protruding dashes) removed since the labels alone suffice.

```python
    ax.set_title(..., loc="left", fontsize=12, color=INK, pad=32)
    if subtitle:
        ax.text(0, 1.14, subtitle, transform=ax.transAxes, ...)
```
Left-aligned title (charts are read left-to-right from the top-left);
`pad` pushes it above the legend row; the subtitle in secondary ink,
positioned in axes coordinates so it tracks the plot area.

```python
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors]
    ax.legend(handles, BUCKETS, ncol=len(BUCKETS), loc="lower left",
              bbox_to_anchor=(0, 1.005), frameon=False, fontsize=8,
              handlelength=1.1, handleheight=1.1, labelcolor=INK_SECONDARY)
```
Five buckets means a legend is mandatory. Hand-built rectangle handles
give square swatches; one row (`ncol=5`) directly above the plot,
frameless, legend text in ink with the swatch carrying the color — text
never wears the series color.

```python
    fig.tight_layout()
    fig.savefig(out_path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")
```
`tight_layout` resolves label geometry; `facecolor` must be repeated at
save time (savefig otherwise repaints the figure white);
`bbox_inches="tight"` trims dead margins — needed because the "% none"
labels sit outside the axes; `close` frees the figure (matters if called
in a loop); and the receipt print says where the file went.

Generated with `python main.py --engine ilp --chart
figures/rank_distribution.png`.

---

# Part 3 — What the numbers show

All runs: 2,000 synthetic students × 10 ranked real Fall 2026 sections
each, k=4, full catalog (1,834 sections). Reproduce with `python main.py`
(≈10–15 minutes; the DA engine takes ~0.2s per run, CBC solves take the
rest). Numbers below are from the run of 2026-08-12.

## 3.1 The headline table (abridged)

| policy / engine | fill | %1st | avg cost | worst | Gini | %required |
|---|---|---|---|---|---|---|
| baseline_fcfs (serial) | .976 | .171 | 16.53 | 55 | .256 | .835 |
| status_quo / ilp | .991 | .174 | 16.00 | 51 | .231 | .851 |
| status_quo / da | .975 | .168 | 16.76 | 55 | .258 | .799 |
| flat_utilitarian / ilp | **1.000** | .207 | **13.98** | 26 | .122 | .754 |
| flat_utilitarian / da | .975 | .163 | 16.97 | 55 | .262 | .686 |
| rawlsian / ilp | 1.000 | .206 | 13.99 | **21** | .117 | .754 |
| balanced / ilp | 1.000 | .203 | 14.11 | 22 | .127 | .883 |
| wesleyan_like / ilp | 1.000 | .189 | 15.31 | 21 | **.115** | .832 |
| graduation_first / ilp | 1.000 | .204 | 14.09 | 24 | .117 | **1.000** |
| graduation_first / da | .978 | .164 | 16.87 | 55 | .256 | .883 |

What each claim in Part 1 looks like in the data:

- **The baseline is genuinely bad at the tail**: worst student cost 55
  (of a possible 60 — near-total shutout), Gini 0.256. Every optimized
  policy beats it on almost every column.
- **`status_quo` ≈ the baseline's values, executed better.** The hard
  seniority gate keeps the same *shape* (see 3.2) while optimization
  within each tier trims waste (worst 51 vs 55, avg 16.00 vs 16.53). The
  difference between these two rows is pure mechanism; the difference
  between them and the rest is pure policy.
- **`flat_utilitarian` shows the price of seniority**: dropping it buys
  a huge global improvement (avg 13.98, everyone's fill 100%) — the
  seniors were being paid for out of a large systemwide deadweight loss.
- **`rawlsian` is almost free here**: the worst case improves 26 → 21
  for +0.013 average cost. This dataset does not force a harsh
  efficiency/fairness trade at the tail — a genuinely useful finding an
  IT department could act on.
- **`graduation_first` delivers exactly its promise**: 100% of the 1,247
  students who ranked a section required for their major received one
  (vs 75.4% when nobody's looking), at +0.11 avg cost.
- **The DA rows are consistently worse on totals than ILP rows under the
  same policy** (avg ~+2.9, fill ~97.5%) — that's the measured price of
  stability/honesty, the BISE paper's trade-off in one column. Note DA
  still responds to policy (its `graduation_first` row hits .883 on
  requirements vs .686 flat).

## 3.2 Who each policy serves (avg cost by class year, ILP rows)

| policy | Senior | Junior | Sophomore | First-Year |
|---|---|---|---|---|
| baseline_fcfs | 11.16 | 13.11 | 14.74 | **27.64** |
| status_quo | 10.97 | 12.60 | 14.01 | **26.94** |
| flat_utilitarian | 13.13 | 13.31 | 14.72 | **14.81** |
| rawlsian | 13.14 | 13.37 | 14.77 | **14.75** |
| balanced | 12.45 | 12.87 | 14.39 | **16.89** |
| wesleyan_like | 15.61 | 14.30 | 15.44 | **15.88** |

The First-Year column is the whole story of the seniority slider:
27.6 → 26.9 → 14.8 as the gate goes from "raced FCFS" to "optimized
tiers" to "abolished." `balanced` (soft weights, λ=0.5) lands where its
sliders point — seniors keep a visible but bounded edge (12.45 vs 16.89).
`wesleyan_like` is the most *level* row of all (spread of 1.6 between
best- and worst-served year, Gini 0.115) and even inverts the gradient —
seat reservations protect first-years better than weights do, at the
highest flat-policy average cost (15.31). Every institutional philosophy
is legible in its row; none of them is "correct." That's the point.

## 3.3 The equality dial, swept (flat weights, ILP)

| λ | worst cost | avg cost | Gini |
|---|---|---|---|
| 0.00 | 26 | 13.979 | 0.121 |
| 0.25 | 21 | 13.991 | 0.116 |
| 0.50 | 21 | 13.991 | 0.115 |
| 0.75 | 21 | 13.991 | 0.115 |
| 1.00 | 21 | 16.106 | 0.113 |

Worst cost falls monotonically and hits its floor (21) by λ=0.25 — on
this data, protecting the tail is cheap and saturates early. The λ=1.00
row is instructive: with *only* the worst case in the objective, average
cost drifts to 16.1 because the solver stops caring about everything
below the maximum — which is precisely why `rawlsian_tiebreak` exists
(the `rawlsian` preset, with tiebreak, gets worst 21 **and** avg 13.99).

## 3.4 Stability spot-check (justified envy)

Counting (student, course) pairs where the student prefers the course to
the worst thing they got, the course is full, and it holds someone with
strictly lower priority under the `graduation_first` policy's own
priority function:

- baseline FCFS: **23** envy pairs
- deferred acceptance: **13** envy pairs

DA roughly halves justified envy but does not eliminate it — the honest
outcome Part 1 predicted for many-to-many matching with time conflicts
(the clean zero-envy theorem only covers one-course-per-student). Both
counts slightly overstate: the check doesn't verify the envied seat would
fit the student's schedule after a swap.

## 3.5 Requirement access, cross-department (the econ→math case)

Of the ECON majors who ranked a MATH0121 section: 2/3 received one under
`flat_utilitarian`; **3/3** under `graduation_first`. Systemwide,
`pct_got_required` goes 0.754 → 1.000. The slider reaches across
department lines exactly as intended, because requirements are a
(major → course code) table, not a same-department test.

## 3.6 Sanity and hand-checks

- Full scale, both engines, flat policy: **0** conflicting pairs
  assigned, **0** courses over capacity.
- The 24-student toy catalog (both engines, two presets): every schedule
  full, conflict-free, within capacity; individual students' assigned
  rank sets eyeball-correct against the toy block structure (e.g. Ava
  Thompson gets ranks {1,2,5,7} — 3 and 4 are block-conflicted with 1
  and 2). ILP and DA agree exactly when there's no contention, as they
  should.
- At 300 students (no contention) every policy and both engines converge
  on identical allocations — differences between policies only exist
  where scarcity exists, which is itself a correct prediction.

## 3.7 Known limitations / future work

- **Conflict detection is still block-equality** (Milestone 2's
  simplification): two sections conflict iff same `days + begin_time`.
  Real overlap detection against `begin_time`/`end_time` is the known
  next step and slots in by swapping `build_conflict_graph`.
- **Full leximin** (fairness beyond the single worst student) is
  approximated by λ + tiebreak; the n-round exact version is future work.
- **Tier rounds freeze assignments** — no Pareto-improving swaps across
  tiers.
- **DA guarantees are heuristic** in this many-to-many setting (§3.4).
- **`prior_avg_rank` and `major_requirements.csv` are invented** —
  disclosed synthetic stand-ins with the right *shape*; a real deployment
  would feed last term's actual outcomes and the registrar's actual
  requirement lists.
