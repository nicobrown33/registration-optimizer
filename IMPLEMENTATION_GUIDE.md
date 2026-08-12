# Implementation Guide — Middlebury Registration Optimizer (Python)

This is a roadmap, not a solution. Each milestone gives you: a goal, a
"Python you'll need" refresher for anything rusty, suggested
function/class *signatures* (no bodies — you write those), hints on the
parts that are easy to get subtly wrong, and a checkpoint you can verify
by eye. Names are suggestions, not requirements — rename anything that
doesn't fit how you end up structuring things.

Data lives in `data/courses.csv` and `data/preferences.csv` (invented —
see `data/synthetic_students.txt` for the human-readable version and the
disclosure note about what's fake). The original assignment prompt is in
`ORIGINAL_PROMPT.AI-GENERATED.txt`.

**On your own, separately from coding:** do the Part I research (how
Middlebury registration actually works — windows, priority by class year,
waitlists, instructor discretion, etc.). Milestone 3 below needs a real
answer, not a guess, so don't skip it just because it isn't code.

## Setup

```
python3 -m venv venv
source venv/bin/activate
pip install pandas networkx pulp matplotlib
```

What each command does, since it's been a while:
- `python3 -m venv venv` creates an isolated Python environment in a
  folder called `venv/` — its own copy of `pip`, separate from whatever's
  installed system-wide. This stops this project's packages (and their
  exact versions) from colliding with any other Python project on your
  machine.
- `source venv/bin/activate` puts that isolated environment "in front" of
  your shell's `PATH`, so `python` and `pip` inside this terminal now
  refer to the venv's copies. You'll see `(venv)` appear in your prompt.
  You need to re-run this `source` command in every new terminal tab you
  open for this project — it doesn't persist automatically.
- `pip install ...` downloads and installs those four packages *into*
  `venv/`, not system-wide.

What each package is for:
- **pandas** — loading/wrangling the CSVs and building the metrics table.
  Think of it as a spreadsheet library: a `DataFrame` is a table you can
  filter, group, and aggregate without writing manual loops.
- **networkx** — the actual graph theory: bipartite preference graph,
  conflict graph, demand graph. This is the tool doing Parts II and VI of
  the prompt. A `networkx.Graph` is just nodes + edges with a big library
  of algorithms built on top (though for this project you're mostly using
  it to *represent* graphs and draw them, not run exotic algorithms).
- **PuLP** — an ILP (integer linear programming) modeling layer with a
  free bundled solver (CBC) that comes installed alongside it. This is
  what turns the math in Part III (`min Σ x·rank`, subject to
  constraints) into runnable code — you write down the objective and
  constraints roughly as they appear in the prompt, call `.solve()`, and
  it does the actual combinatorial search for you. This is doing Parts
  III and IV.
- **matplotlib** — plotting, for Part IX.

Suggested project layout (you've already scaffolded this — good):

```
registration-optimizer/
  data/
    courses.csv, preferences.csv          (original invented catalog — unused now, kept for reference)
    courses_202690.json                    (raw real Banner export, real Fall 2026 data)
    courses_real.csv, preferences_real.csv  (real data, in the shape io.py actually loads)
  preprocessing/
    export_real_courses.py                  (JSON -> courses_real.csv, re-runnable)
  regopt/
    __init__.py
    models.py               (Course, Student — plus CourseSection, MeetingTime for real data)
    io.py                    (CSV loading — defaults to the *_real.csv files)
    real_data.py              (structured real-data loader — see below)
    graphs.py                (bipartite / conflict / demand graphs)
    baseline.py              (Milestone 3)
    ilp_allocation.py              (Milestones 4-7, the ILP models)
    metrics.py                (Milestone 9)
    viz.py                     (Milestone 10)
  main.py
```

`graphs.py` deliberately holds all three graph-builders (preference,
conflict, demand) — they're small, related, and share imports. If it ever
grows past ~150 lines, that's a reasonable time to reconsider — not now.

**Don't confuse `regopt/models.py` (the `Course`/`Student` dataclasses,
Milestone 0) with "Model 1–4" from Part IV of the prompt** (maximize
total satisfaction / first choices / lexicographic / max-min). Those four
optimization models are unrelated to the `models.py` file — they all live
in `regopt/ilp_allocation.py`.

**Quick reference — which file, which milestone:**

| Milestone | What | File |
|---|---|---|
| 0 | `Course`, `Student` | `regopt/models.py` |
| 0 | `load_courses`, `load_students` | `regopt/io.py` |
| 1 | `build_preference_graph` | `regopt/graphs.py` |
| 2 | `build_conflict_graph` | `regopt/graphs.py` |
| 3 | `run_baseline` | `regopt/baseline.py` |
| 4 | `solve_min_total_rank` (Model 1) | `regopt/ilp_allocation.py` |
| 5 | Model 2 (max first choices) | `regopt/ilp_allocation.py` |
| 6 | `solve_lexicographic` (Model 3) | `regopt/ilp_allocation.py` |
| 7 | Model 4, max-min (Rawlsian) | `regopt/ilp_allocation.py` |
| 8 | `build_demand_graph` | `regopt/graphs.py` |
| 9 | `compute_metrics` | `regopt/metrics.py` |
| 10 | plotting functions | `regopt/viz.py` |
| — | wiring it all together, printing final comparisons | `main.py` |
| — | real data (Part VII, see below) — **this is the default data source now** | `preprocessing/export_real_courses.py`, `regopt/real_data.py`, `regopt/io.py` |

---

## Python refresher: the handful of features every milestone leans on

If you already remember these, skip ahead — but skim the itertools and
PuLP-gotcha bullets either way, those bite everyone.

**f-strings.** `f"course:{course_id}"` builds a string with a variable
spliced in. You'll use this constantly for building graph node names and
debug prints. Example: `name = "Ava"; print(f"hello {name}")` → `hello
Ava`.

**Type hints.** `def load_students(path: str) -> list[Student]:` doesn't
*enforce* anything at runtime — Python won't stop you from returning the
wrong type. It's documentation the editor/linter can check, and it's
worth writing because it makes the stubs in this guide (and your own
functions) self-explanatory months from now. `dict[str, Course]` means "a
dict whose keys are strings and values are `Course` objects." `list[str]
| None` means "either a list of strings, or `None`."

**Dataclasses.** `@dataclass` on a class auto-generates `__init__`,
`__repr__`, and `__eq__` from the fields you list, so you don't hand-write
boilerplate like `self.id = id`. Example:

```python
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int

p = Point(3, 4)
print(p)        # Point(x=3, y=4) — for free, from @dataclass
print(p.x)      # 3
```

That's exactly the pattern `Course` and `Student` use in this project.

**List and dict comprehensions.** A compact way to build a list/dict from
an existing iterable, instead of a `for` loop with `.append`. These two
are equivalent:

```python
squares = []
for n in range(5):
    squares.append(n * n)

squares = [n * n for n in range(5)]     # same result, one line
```

Dict comprehensions look like `{key_expr: value_expr for x in iterable}`:

```python
by_id = {course.id: course for course in course_list}
```

You'll use this shape to go from "a list of Course objects" to "a dict
keyed by course id" — exactly what `load_courses` needs to return.

**`itertools.combinations`.** Gives you every unordered pair from a list,
without writing nested loops yourself:

```python
from itertools import combinations
list(combinations(["A", "B", "C"], 2))
# [('A', 'B'), ('A', 'C'), ('B', 'C')]
```

You'll use this twice: building all pairs of courses within a time block
(Milestone 2) and all pairs of courses in one student's top-10
(Milestone 8).

**Sorting with `key=`.** `sorted(iterable, key=some_function,
reverse=True)` sorts by whatever `some_function` returns for each
element, not the element's natural order. Example: sorting
`(name, count)` tuples by `count` descending:

```python
pairs = [("a", 3), ("b", 9), ("c", 1)]
sorted(pairs, key=lambda p: p[1], reverse=True)
# [('b', 9), ('a', 3), ('c', 1)]
```

You'll want this in Milestone 8 to print the heaviest demand-graph edges.

**Mutable default argument gotcha.** Never write `def f(x, items=[]):` —
that empty list is created *once*, at function-definition time, and
reused across every call, silently accumulating junk. If a stub in this
guide needs a default list/dict argument, use `None` and build the real
default inside the function body:

```python
def f(x, items=None):
    if items is None:
        items = []
```

**PuLP's float gotcha.** After `.solve()`, a binary variable's `.value()`
comes back as a `float` like `0.9999999` or `1.0`, not a clean Python
`bool`/`int` — floating-point solvers are like that. Always check
`var.value() > 0.5` to decide "is this variable on," never `== 1`.

---

## Milestone 0 — Data model and CSV loading

📁 **Code in:** `regopt/models.py` (the two dataclasses) and
`regopt/io.py` (the two loaders) — two files this milestone, split as
shown below.

**Goal:** load `courses.csv` and `preferences.csv` into typed Python
objects.

**Starting point** (`regopt/models.py`):

```python
from dataclasses import dataclass

@dataclass
class Course:
    id: str
    department: str
    title: str
    block: str      # 'A'..'H'
    capacity: int

@dataclass
class Student:
    name: str
    class_year: str
    major: str
    prefs: list[str]   # course IDs in rank order; prefs[0] = 1st choice
```

**Function stubs** (`regopt/io.py`):

```python
def load_courses(path: str) -> dict[str, Course]:
    """Keyed by course id."""

def load_students(path: str) -> list[Student]:
    ...
```

**Python you'll need:** `pandas.read_csv(path)` returns a `DataFrame` —
picture it as the whole CSV loaded into a table you can slice. Two ways
to walk its rows and turn each into a plain object:

```python
import pandas as pd
df = pd.read_csv("data/courses.csv")

for row in df.itertuples():
    # row.id, row.department, row.block, row.capacity — attribute access
    ...

for row in df.to_dict("records"):
    # row["id"], row["department"], ... — dict access
    ...
```
Either is fine; pick whichever reads more naturally to you. The point is:
**don't leave the data as a DataFrame past this milestone** — the rest of
the project wants plain `Course`/`Student` objects and, later, `networkx`
graphs, not spreadsheet rows.

**Step-by-step:**
1. Read the CSV with `pd.read_csv`.
2. Loop over rows, construct one `Course` (or `Student`) per row.
3. For courses: collect them into a `dict[str, Course]` keyed by `id` —
   a dict comprehension (see refresher above) is the natural fit, or a
   plain loop with `result[row.id] = Course(...)` if that's clearer to
   you right now.
4. For students: the tricky part is the 10 `rank1..rank10` columns need
   to collapse into one `prefs` list per student. A list comprehension
   over `range(1, 11)` pulling `row[f"rank{i}"]` (or `getattr(row,
   f"rank{i}")` if using `itertuples`) is the shape you want — see the
   f-string and comprehension refreshers above, this is where they
   combine.
5. Collect students into a plain `list[Student]` (order doesn't matter
   yet, but you'll want a stable order later for Milestone 3's baseline).

**Checkpoint:** print `len(courses)`, `len(students)`, and one specific
student's `prefs` list (try `"Ava Thompson"`) — compare by eye against
`preferences.csv`. If the count is off by one, you probably forgot to
skip/account for the header row — `read_csv` handles that automatically
by default, so an off-by-one here usually means something else (like
accidentally re-reading a blank trailing line); print `df.shape` to see
what pandas actually parsed.

*(Already done, against `data/courses.csv`/`data/preferences.csv` — no
need to redo it. Since then, `load_courses`/`load_students` gained
default arguments pointing at the real-data CSVs instead — see "Real data
ingestion" right below. Same functions, same shape, just a different
default file.)*

---

## Real data ingestion (Part VII) — parallel to Milestone 0, not "Milestone 1"

📁 **Code in:** `preprocessing/export_real_courses.py` (standalone script)
and `regopt/real_data.py` (structured loader) — both already written, and
**`Milestones 1–10 now run on this real data by default`** (see below).

This section exists outside the 0–10 numbering because it's plumbing, not
graph-theory/optimization content — but unlike when this section was
first written, it's no longer just a parallel side-track: `regopt/io.py`
now actually routes here.

**What this is:** `data/courses_202690.json` is a real export of
Middlebury's Fall 2026 course schedule (Banner course-search format) —
1,834 real sections across 56 real departments, with real capacities,
enrollment, meeting days/times, and instructors. Genuine Part VII
"historical data," not synthetic.

**The pipeline, in order:**
1. `data/courses_202690.json` — raw Banner export. Never edited by hand;
   redownload a fresh one if you need a different term.
2. `preprocessing/export_real_courses.py` — standalone script (no
   `regopt` import, so it can't break if the package changes), converts
   the JSON into `data/courses_real.csv`, one row per real *section*
   (keyed by CRN, since a real course can have several sections at
   different times/instructors — see "Section granularity" decision
   below). Re-run it any time you redownload a new export:
   `python preprocessing/export_real_courses.py data/courses_202710.json data/courses_real.csv`.
   Columns: `id` (CRN), `subject_course`, `department`, `title`,
   `section`, `credit_hours`, `capacity`, `enrolled`, `seats_available`,
   `instructors`, `block`, `days`, `begin_time`, `end_time`, `meeting_time`.
3. `data/preferences_real.csv` — your 23 synthetic students, hand-mapped
   to rank real Fall 2026 CRNs from a curated 27-section subset of
   `courses_real.csv` (chosen to mirror the old invented catalog's
   breadth across ~18 departments). Not derived by a script — authored
   once, the same way the original `preferences.csv` was, since it's
   invented content, not something to re-derive from a redownload.
4. `regopt/io.py`'s `load_courses`/`load_students` now **default** to
   `data/courses_real.csv` / `data/preferences_real.csv`. The original
   `data/courses.csv` / `data/preferences.csv` still exist, untouched,
   but nothing calls them anymore — pass an explicit `path=` argument if
   you ever want them back for a quick comparison.

**Two `block`-like fields, and why both exist:**
- `block` = `days + begin_time` (e.g. `"TuTh0945"`). This is what
  Milestone 2's equality-based `build_conflict_graph` groups on — it
  works, but it's an approximation: two sections only get flagged as
  conflicting if they start at the *exact* same time. A 9:00–12:00 class
  and a 10:00–12:00 class genuinely overlap but get different `block`
  values (`"Mo0900"` vs `"Mo1000"`), so equality-grouping misses that
  conflict. No amount of extra info stuffed into the `block` string fixes
  this — string equality can never detect a partial overlap, only an
  exact match.
- `days`, `begin_time`, `end_time` — the same information, kept as
  separate structured columns instead of one glued string, specifically
  so **real overlap detection** can be written directly against them
  later: two sections conflict iff they share a day AND
  `max(begin1, begin2) < min(end1, end2)`. `begin_time`/`end_time` are
  `"HHMM"` 24-hour strings (`"1330"`) — `int(...)` works fine for
  comparison since they're zero-padded. This is a strictly harder,
  more realistic version of the same graph-theory idea as Milestone 2 —
  it's real learning content, not done for you, and worth attempting
  only after Milestone 2 itself (on the current `block` approximation)
  is solid.

**Section granularity decision (already made, in case you revisit it):**
`courses_real.csv` is one row per section, not one per course — 272 real
courses this term have more than one section at a different
time/instructor. Treating each section as its own "course" for
allocation purposes matches how registration actually works (you pick a
specific section, not just a course name); it's also why `preferences_real.csv`
ranks CRNs (numeric section IDs like `90079`) rather than readable codes
like `"CSCI0201"` — less readable, but it's what real registration units
actually are.

**Still not done, and not planned to be done for you** (same spirit as
every other milestone): real overlap-based conflict detection (above);
no prerequisite data exists in the Banner export at all, so the Part V
prerequisite stretch still needs an invented "completed courses" field;
and data-quality calls — a few sections have no scheduled meeting time
(independent studies) or `capacity == 0` (reserved sections) — are left
as-is in `courses_real.csv`, filter them in your own code if a given
milestone needs to.

---

## Milestone 1 — The student-course bipartite graph

📁 **Code in:** `regopt/graphs.py` (first function in this file — Milestones
2 and 8 add more functions here later, don't split them out).

**Goal:** represent Part II.A as an actual `networkx` graph, not just the
`prefs` lists sitting in `Student` objects.

```python
import networkx as nx

def build_preference_graph(students: list[Student], courses: dict[str, Course]) -> nx.Graph:
    """Bipartite graph. Student nodes and course nodes, distinguished by a
    'bipartite' node attribute (0/1) per networkx convention. Each edge
    carries a 'rank' attribute (1..10)."""
```

**Python/networkx you'll need:**

```python
G = nx.Graph()
G.add_node("student:Ava Thompson", bipartite=0)
G.add_node("course:CSCI0101", bipartite=1)
G.add_edge("student:Ava Thompson", "course:CSCI0101", rank=3)

G.number_of_nodes()          # total node count
G["student:Ava Thompson"]    # dict-like view of that node's neighbors
                              # -> {"course:CSCI0101": {"rank": 3}, ...}
```

`add_node`/`add_edge` are idempotent — calling `add_node` again on an
existing node just updates its attributes, it won't create a duplicate.
That means you don't need to check "have I already added this course
node" before adding it again from a different student's loop iteration.

**Step-by-step:**
1. Create an empty `nx.Graph()`.
2. Add one node per course, tagged `bipartite=1` — loop over
   `courses.values()`.
3. Add one node per student, tagged `bipartite=0` — loop over `students`.
4. For each student, for each `(rank_position, course_id)` in their
   `prefs` (an `enumerate(student.prefs, start=1)` gives you exactly that
   pairing — look up `enumerate` if that's rusty too, it's `for i, x in
   enumerate(seq, start=1)`), add an edge with `rank=rank_position`.

**Hints:**
- Look up `networkx`'s bipartite graph conventions
  (`nx.algorithms.bipartite`) — you don't have to use its matching
  algorithms, but the node-attribute convention is worth following so the
  graph is legible to anyone who knows networkx.
- Student names aren't guaranteed unique in general (yours happen to be,
  but don't rely on that) — prefix node ids as shown above
  (`f"student:{s.name}"` vs `f"course:{c.id}"`), so a student and a
  course can never collide into the same node even if a name and a course
  id ever matched by coincidence.

**Checkpoint:** `G.number_of_nodes()` should equal `len(students) +
len(courses)`. Pick one student node and print `G[node]` — the `rank`
values should match that student's `prefs` order (rank 1 = their `prefs[0]`).

---

## Milestone 2 — Course conflict graph (Part II.C)

📁 **Code in:** `regopt/graphs.py` — same file as Milestone 1, as a second
function alongside `build_preference_graph`.

```python
def build_conflict_graph(courses: dict[str, Course]) -> nx.Graph:
    """Nodes = course ids. Edge between two courses iff they share a
    meeting block."""
```

**Python you'll need:** grouping courses by block, then all pairs within
each group.

```python
from itertools import combinations
from collections import defaultdict

by_block = defaultdict(list)
for course in courses.values():
    by_block[course.block].append(course.id)
# by_block now looks like {"TuTh0945": ["90079", "90362", ...], "Mo0900": [...], ...}
# (real data: block is a days+start-time code like "TuTh0945", not a
# single letter — same grouping idea either way)
```

`defaultdict(list)` is a dict that auto-creates an empty list the first
time you access a missing key, so `by_block[course.block].append(...)`
works even for a block you haven't seen before — no `if key not in dict:
dict[key] = []` boilerplate. If that's unfamiliar, `dict.setdefault(key,
[]).append(...)` does the same thing with a plain `dict`.

Once you have `by_block`, courses sharing a block form a clique — for
each block's list of course ids, `combinations(ids, 2)` gives every pair
that needs an edge (see the itertools refresher above), and
`G.add_edges_from(...)` takes an iterable of `(u, v)` pairs directly.

**Checkpoint:** for each distinct `block` value, print the course ids in
it — cross-check against `data/courses_real.csv`. Then confirm
`conflict_graph.has_edge("90079", "90362")` is `True` — CRN `90079` is
`CSCI0201` and `90362` is `PSCI0103`, both meeting `TuTh0945`. (Remember
this only catches *exact* `block` matches — see "Real data ingestion"
above for why that's an intentional simplification, not a bug, at this
stage.)

---

## Milestone 3 — Baseline: simulate the *current* system

📁 **Code in:** `regopt/baseline.py` (new file).

This is where your own Part I research feeds in. Before writing this,
decide (from what you actually found, not a guess): is Middlebury's
registration closer to strict first-come-first-served, priority by class
year/credits, or something else? That becomes `priority_order`.

**Concept to look up:** serial dictatorship — process students in
priority order; each one greedily takes the best still-available,
non-conflicting course from their own ranked list.

```python
def run_baseline(
    students: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    priority_order: list[Student],
    k: int = 4,   # courses each student needs this term
) -> dict[str, list[str]]:
    """Returns {student_name: [assigned course ids]}."""
```

**Python you'll need:** nothing new here syntactically — this is plain
loops and dict/list bookkeeping. The one thing worth calling out:

```python
remaining_seats = {cid: c.capacity for cid, c in courses.items()}
```

builds a **copy** of the capacity numbers as a plain dict. This matters
because dicts and the `Course` objects inside them are mutable — if you
instead wrote `remaining_seats = courses` and then decremented values
inside it, you'd be corrupting the actual `Course.capacity` fields that
every later milestone reads. Always make an explicit fresh dict when you
need "capacity minus what's been used so far" bookkeeping.

**Step-by-step:**
1. Build `remaining_seats` as shown above.
2. Prepare an empty `assignment: dict[str, list[str]]`, one empty list
   per student (`{s.name: [] for s in students}`).
3. Loop over `priority_order`. For each student, loop over their
   `prefs` top to bottom. For each candidate course:
   - skip it if `remaining_seats[course_id] <= 0`,
   - skip it if it conflicts (via `conflict_graph.has_edge`) with any
     course this student has *already* accepted in this same inner loop,
   - otherwise, accept it: append to `assignment[student.name]`,
     decrement `remaining_seats[course_id]`, stop once the student has
     `k` courses.

**Checkpoint:** run with `priority_order = students` (input order, a
rough FCFS proxy) and print: % getting 1st choice, % getting top-3,
average rank. This is your comparison baseline for everything after it.

---

## Milestone 4 — Model 1: minimize total rank cost (ILP)

📁 **Code in:** `regopt/ilp_allocation.py` (new file — this is "Model 1," not to
be confused with `regopt/models.py`'s `Course`/`Student` classes;
Milestones 5–7 add more functions to this same file).

This is Part III's literal formula. Set it up close to how it's written
in the prompt:

```
minimize   Σ_s Σ_c  x[s,c] · rank(s,c)
subject to Σ_s x[s,c] ≤ capacity(c)                        for every course c
           x[s,c1] + x[s,c2] ≤ 1                             for every conflicting pair (c1,c2) student s ranked
           Σ_c x[s,c] ≤ k                                    for every student s
           x[s,c] ∈ {0,1}, only defined where s ranked c
```

```python
import pulp

def solve_min_total_rank(
    students: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    k: int = 4,
) -> dict[str, list[str]]:
    ...
```

**PuLP crash course**, since this is the least familiar library here even
if you know Python well:

```python
prob = pulp.LpProblem("name_it_anything", pulp.LpMinimize)

# One binary decision variable per (student, course) pair you care about.
x = {}
for s in students:
    for c in s.prefs:
        x[(s.name, c)] = pulp.LpVariable(f"x_{s.name}_{c}", cat="Binary")

# The objective: build it as a sum of (variable * coefficient) terms,
# then assign it to the problem with +=.
prob += pulp.lpSum(
    x[(s.name, c)] * rank_of(s, c)
    for s in students for c in s.prefs
)

# Constraints are also added with += — each one is a linear
# inequality/equality built out of the same variables.
prob += x[("Ava Thompson", "CSCI0101")] + x[("Ava Thompson", "ECON0155")] <= 1

prob.solve()
pulp.LpStatus[prob.status]     # "Optimal", "Infeasible", etc. — check this!
x[("Ava Thompson", "CSCI0101")].value()   # 1.0 or 0.0 (float — see the gotcha above)
```

The pattern to internalize: `prob += <expression>` means "add this to the
model" — PuLP figures out from context whether `<expression>` is *the*
objective (only the first bare `pulp.lpSum(...)` you add without a
comparison operator) or *a* constraint (anything with `<=`, `>=`, `==`).
`pulp.lpSum(generator_expression)` is just a fast, PuLP-friendly version
of Python's built-in `sum(...)` — use it instead of `sum()` for anything
involving PuLP variables.

**Hints:**
- Only create a variable `x[(s.name, c)]` for `c in s.prefs` — don't
  create variables for (student, course) pairs the student never ranked,
  you'd be solving a much bigger problem than you need to, for no
  benefit (those variables would just always end up fixed at 0).
- You'll want a helper to look up a student's rank for a course they
  ranked — e.g. `student.prefs.index(course_id) + 1` (`list.index` finds
  the position; `+1` converts from 0-indexed position to 1st/2nd/3rd...).
- The conflict constraint only matters between courses that are *both* in
  a given student's `prefs` — for each student, use
  `combinations(student.prefs, 2)` and check `conflict_graph.has_edge(c1,
  c2)` for each pair, only adding the `<= 1` constraint when it's `True`.
- After `prob.solve()`, check `pulp.LpStatus[prob.status] == "Optimal"`
  before trusting the result — an infeasible model (e.g. `k` set higher
  than any student's `prefs` can satisfy given conflicts) will solve
  "successfully" in the sense that `.solve()` returns, but the status
  tells you the result is garbage.
- Read off assignments with `var.value() > 0.5`, not `== 1` (see the
  PuLP float gotcha in the refresher above).

**Checkpoint:** run on the synthetic data; compare total cost and the
satisfaction summary against Milestone 3. Write these numbers down — you
need them for Part VIII.

---

## Milestone 5 — Model 2: maximize first-choice count

📁 **Code in:** `regopt/ilp_allocation.py` — same file as Milestone 4.

Same constraint structure as Milestone 4, different objective:

```
maximize   Σ_s x[s, s's 1st choice course]
```

In PuLP terms: same variables and constraints as Milestone 4, but the
objective sums only the terms where `c == s.prefs[0]`, and you use
`pulp.LpMaximize` when constructing the `LpProblem` instead of
`LpMinimize`.

**Hint:** you can literally copy Milestone 4's constraint-building code
and swap only the objective line — that repetition is a signal you'll
want to factor constraint-building into its own helper function shared
across Milestones 4–7 (something like `add_capacity_and_conflict_constraints(prob, x,
students, courses, conflict_graph, k)`, called before each milestone adds
its own objective). Do that refactor once you actually see the
duplication with your own eyes, not before — premature refactoring before
you've written the second copy tends to guess the wrong shared shape.

**Checkpoint:** how many students get their 1st choice, vs. under Model
1? You should see the tension Part IV describes — this number can "win"
here while the tail (worst-off students) gets worse. Check a few
individual students' full assignment to see who lost out.

---

## Milestone 6 — Model 3: lexicographic fairness

📁 **Code in:** `regopt/ilp_allocation.py` — same file as Milestones 4–5.

**Idea:** solve in rounds. Round 1 = Milestone 5 (maximize # getting rank
1). Freeze those results — remove those students from the pool, subtract
their seats from `remaining_seats`. Round 2: among what's left, maximize
# getting rank ≤ 2. Continue through rank 10 or until everyone's placed.

```python
def solve_lexicographic(
    students: list[Student],
    courses: dict[str, Course],
    conflict_graph: nx.Graph,
    k: int = 4,
) -> dict[str, list[str]]:
    ...
```

**Hint on structure:** this is a `for` loop over rank thresholds
1..10, and *inside* that loop you're building and solving a fresh, small
PuLP problem each time (a new `pulp.LpProblem` per round — don't try to
reuse/mutate one problem object across rounds, it gets confusing fast).
Each round's problem only includes the students not yet satisfied, and
uses a `remaining_seats`-style capacity dict that carries over between
rounds (same mutable-copy caution as Milestone 3).

**Hint — the one real design decision here:** once a student is satisfied
at round *r*, do they leave the pool permanently, or could a later round
improve them without hurting anyone already settled? The simple, correct
version removes them permanently — note in your write-up that a stronger
version allowing later Pareto-improving swaps is possible but harder.
That's a legitimate "future work" line for your paper, not something you
need to build now.

**Checkpoint:** a table of (round, # newly satisfied at that rank).
Compare its shape to Models 1 and 2.

---

## Milestone 7 — Model 4: max-min (Rawlsian) fairness

📁 **Code in:** `regopt/ilp_allocation.py` — last function in this file (4 of 4
allocation models done after this).

Unlike a from-scratch flow-network approach, in ILP form this is just one
more variable and constraint — no binary search needed.

```
minimize   z
subject to (all of Milestone 4's constraints, plus:)
           z ≥ Σ_c x[s,c] · rank(s,c)     for every student s
```

`z` becomes an upper bound on every student's assigned rank; minimizing
it pushes down the worst outcome. In PuLP, `z` is just one more
`pulp.LpVariable` (this time continuous, not binary — `cat="Continuous"`
or `cat="Integer"`), and the new constraint is one `prob += z >=
pulp.lpSum(...)` per student, added in a loop.

**Hint:** once you have the optimal `z*` (read it with `z.value()` after
solving), consider a second solve: build a *new* problem with the same
constraints plus `z <= z*` (using the value you just found, hardcoded as
a constant now, not a variable), and minimize total rank cost
(Milestone 4's objective) as a tiebreak among all assignments that
achieve the best worst-case. Two small solves chained together, reusing
your Milestone 4 constraint-building helper for the second one.

**Checkpoint:** report `z*` — the smallest worst-case rank achievable.
This single interpretable number ("no student is forced below their Nth
choice") is good material for your fairness discussion.

---

## Milestone 8 — Course demand / co-ranking graph (Part VI)

📁 **Code in:** `regopt/graphs.py` — third and last function in this file,
alongside `build_preference_graph` and `build_conflict_graph`.

A different graph from everything above: nodes = courses, edge weight =
number of students who ranked *both* endpoints anywhere in their top 10.

```python
def build_demand_graph(students: list[Student], courses: dict[str, Course]) -> nx.Graph:
    """Weighted graph; edge weight = # students who ranked both courses."""
```

**Python you'll need:** counting co-occurring pairs is a natural fit for
`collections.Counter`:

```python
from collections import Counter
from itertools import combinations

counts = Counter()
for student in students:
    for pair in combinations(sorted(student.prefs), 2):
        counts[pair] += 1
# counts is now e.g. {("CSCI0101", "ECON0155"): 7, ("CSCI0101", "PSYC0105"): 3, ...}
```

`sorted(student.prefs)` before pairing matters: without it, the same
course pair could show up sometimes as `("A", "B")` and sometimes as
`("B", "A")` depending on rank order, and `Counter` would treat those as
two different keys instead of accumulating one count. Sorting each pair's
two elements first guarantees a consistent key.

Once you have `counts`, load it into a graph: `G.add_edge(u, v,
weight=count)` for each `(u, v), count in counts.items()`.

**Checkpoint:** print the 5 heaviest edges — `sorted(counts.items(),
key=lambda item: item[1], reverse=True)[:5]` (this is the sorting-with-
`key` pattern from the refresher, applied to `dict.items()` tuples). Do
any land on courses that are *also* in the same time block (high demand
overlap **and** a scheduling conflict)? That cross-reference — a pair
Middlebury should probably never schedule opposite each other — is a real
Part VI finding.

---

## Milestone 9 — Metrics harness (Part VIII)

📁 **Code in:** `regopt/metrics.py` (new file).

One function, reused across baseline + all four models.

```python
import pandas as pd

def compute_metrics(
    assignment: dict[str, list[str]],
    students: list[Student],
    courses: dict[str, Course],
) -> dict:
    """Returns pct_first_choice, pct_top3, avg_rank, median_rank,
    worst_rank, num_unassigned_slots, num_empty_seats, etc."""
```

**Python/pandas you'll need:** build a "long" DataFrame — one row per
(student, assigned course), with the rank of that course included — then
let pandas do the aggregation instead of hand-rolling it.

```python
rows = []
for student in students:
    for course_id in assignment[student.name]:
        rows.append({
            "student": student.name,
            "course": course_id,
            "rank": student.prefs.index(course_id) + 1,
        })
df = pd.DataFrame(rows)

df["rank"].mean()                    # average rank
df["rank"].median()                  # median rank
df["rank"].max()                     # worst rank
(df["rank"] == 1).mean()             # fraction getting 1st choice (bool mean = proportion True)
(df["rank"] <= 3).mean()             # fraction getting top-3
```

That last trick — `(condition).mean()` on a pandas Series — works because
`True`/`False` behave as `1`/`0` for arithmetic purposes, so "the mean of
a column of booleans" is exactly "the fraction that are `True`." It's a
very common pandas idiom worth having in your toolkit beyond this
project.

**Checkpoint:** build one table (a DataFrame with one row per model:
baseline, Model 1–4, columns = the metrics above) and print it. This
table is most of your Part VIII deliverable.

---

## Milestone 10 — Visualization (Part IX)

📁 **Code in:** `regopt/viz.py` (new file).

```python
import matplotlib.pyplot as plt
```

- **Bipartite graph:** `nx.draw` with `pos` from
  `nx.bipartite_layout(G, student_nodes)` (you need to pass it the set of
  nodes on one side — e.g. `{n for n, d in G.nodes(data=True) if
  d["bipartite"] == 0}`, using the attribute you set in Milestone 1).
  With 24 students × 27 courses this will already look busy — consider
  drawing only the *assigned* edges highlighted (thicker/colored) over
  the full preference graph drawn faint, per the prompt's Part IX.1
  suggestion. `nx.draw(G, pos, edge_color=[...], width=[...])` accepts a
  per-edge list of colors/widths in the same order as `G.edges()`, which
  is how you'd distinguish "assigned" from "just ranked."
- **Demand network:** node size or color by course popularity (total
  ranked count — you can compute this straight from the `rank` matrix or
  by summing degree-weighted counts), edge width by `weight` from
  Milestone 8. `nx.draw(G, node_size=[...], width=[...])` again takes
  per-node/per-edge lists.
- **Rank distribution comparison:** a grouped bar chart — x-axis = choice
  rank (1st, 2nd, 3rd, 4th+), bars grouped by model (baseline vs. Model
  1–4), height = count or %. `matplotlib`'s bar-chart grouping usually
  means manually offsetting x-positions per group
  (`plt.bar(x + i*width, ...)` for each model `i`) — look up a "grouped
  bar chart matplotlib" example if the offset math is fiddly, it's a
  well-worn pattern. This is the most important chart for your results
  section — it's the direct visual answer to the research question.
- **Demand heat map:** courses × (requested / capacity / excess demand) —
  a simple horizontal bar or `seaborn.heatmap`-style table works fine,
  you don't need anything fancy. (If you don't already have `seaborn`
  installed and don't want to add it, a plain sorted `plt.barh` of
  "requested − capacity" per course communicates the same thing.)

**Checkpoint:** four saved PNGs (`plt.savefig(...)`) or inline in a
notebook — bipartite graph, demand graph, rank-distribution comparison,
demand heat map.

---

## Stretch goals (Part V) — only after Milestones 0–9 work

📁 **Code in:** mainly `regopt/ilp_allocation.py` (filtering which `(student,
course)` variables get created, and adjusting `k`/costs); the
completed-courses field itself belongs in `regopt/models.py` /
`regopt/io.py` next to where `Student` is defined and loaded.

- **Prerequisites:** add a `prereq: dict[str, str | None]` (course id →
  required course id). Before building the ILP variables in Milestone 4,
  filter out `(student, course)` pairs where the student's synthetic
  "completed courses" don't include the prereq. You'll need to invent
  that completed-courses field — extend `preferences.csv` or add a new
  file, your call.
- **Priority for seniors/graduation requirements:** fold this in without
  redesigning everything by making `k` or specific edge costs depend on
  class year / requirement flags (e.g. required-for-graduation edges get
  a cost discount in the objective, or those students get processed in
  an earlier lexicographic round). Try it both ways and compare — that
  tension *is* the ethical question Part V asks you to answer.

---

## Before you write the final paper (Part X)

Once you have real numbers out of Milestones 3–9, answer these yourself,
grounded in what you actually observed (not in the abstract):
- Strategic ranking — could a student have done better by lying about
  their preferences under Model 1? Under the lexicographic model? (These
  differ — figure out why.)
- Popularity spirals — look at your Milestone 8 demand graph; did that
  happen with this synthetic data?
- Whose outcomes got worse under the fairness models vs. Model 1, and by
  how much?
- Would a student who didn't get a course understand *why*, from the
  numbers your program produces?

---

## Open questions for me, whenever you hit them

- If you want a second pair of eyes on a PuLP model once it's written
  (getting the conflict constraint's scope right is the one part of this
  that's easy to get subtly wrong), ask and I'll review it — but try to
  get it running and hand-check a small example first.
- If something in this guide's Python assumes knowledge you don't have
  yet (a stdlib module, a pandas/networkx call I used without
  explaining), just ask — the refresher sections above cover what I
  expect to come up, but they won't cover everything.
- If you want to scale past the 24-student/27-course toy dataset later
  (bigger synthetic set, or real registrar data), say so — CBC (PuLP's
  bundled solver) is fine at this scale but you'd want to know before you
  build something that assumes 24 students forever.
