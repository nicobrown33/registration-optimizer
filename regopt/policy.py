"""The Policy layer: every "slider" an IT department can set, in one place.

The whole point of this module is separating *policy* (who should get
priority, how much equality matters) from *mechanism* (the ILP solver in
policy_ilp.py, the deferred-acceptance matcher in deferred_acceptance.py).
Both engines consume the same Policy object, so the same institutional
choices can be run through either mechanism and compared.

The per-student score everything revolves around is the linear "rank
cost": the sum over a student's assigned courses of the rank they gave
each one (1 = first choice), raised to rank_cost_exponent, plus
unassigned_penalty for every course slot left empty. Lower = happier.
"""

import json
from dataclasses import asdict, dataclass, field

from regopt.models import Course, Student

# prior_avg_rank (last term's average received rank, synthetic — see
# preprocessing/add_past_outcomes.py) ranges over [1, 8]. These bounds
# normalize it to a [0, 1] "how badly were you treated" shortfall.
PRIOR_BEST = 1.0
PRIOR_WORST = 8.0

# guarantee_requirement is implemented as a soft constraint with a penalty
# so large the solver treats it as hard, but the model can never become
# infeasible (a true hard constraint could be unsatisfiable when a
# required course's sections are all full or all conflict).
GUARANTEE_PENALTY = 100.0

CLASS_YEARS = ["Senior", "Junior", "Sophomore", "First-Year"]


def _equal_weights() -> dict[str, float]:
    return {year: 1.0 for year in CLASS_YEARS}


@dataclass
class Policy:
    name: str = "custom"

    # --- Who counts more: per-student weight multipliers -------------------
    # Multiplies a student's entire rank cost in the objective. All 1.0 =
    # no seniority preference at all.
    class_year_weights: dict[str, float] = field(default_factory=_equal_weights)
    # 0 = ignore history. At w, a student with the worst possible prior
    # term gets their weight multiplied by (1 + w) — the system "owes" them.
    past_outcome_weight: float = 0.0

    # --- Which (student, course) pairs get cheaper: edge discounts ---------
    # Subtracted from the rank cost when the course's department equals the
    # student's major (in-department affinity).
    major_match_bonus: float = 0.0
    # Subtracted when the course is on the student's major's requirement
    # list (data/major_requirements.csv) — deliberately including
    # cross-department requirements (ECON major needing intro MATH).
    requirement_weight: float = 0.0
    # Near-hard version: huge penalty if a student who ranked at least one
    # required course ends up with none of them.
    guarantee_requirement: bool = False

    # --- Hard vs. soft priority --------------------------------------------
    # "weights": everything above blends into one objective.
    # "tiers": lexicographic — tier_order[0] students are allocated first
    # and their assignments frozen before tier_order[1] is even considered
    # (Middlebury's real seniority gate, Bowdoin's preference orders).
    priority_mode: str = "weights"
    tier_order: list[str] = field(default_factory=lambda: list(CLASS_YEARS))

    # --- The equality dial --------------------------------------------------
    # 0 = utilitarian (minimize total weighted cost, whoever bears it).
    # 1 = Rawlsian (minimize the single worst student's cost).
    # Between: a blend of the two objectives.
    equality: float = 0.0
    # At equality=1 many allocations share the same worst case; this picks
    # the one with the best total cost among them (second solve).
    rawlsian_tiebreak: bool = False

    # --- Course-side seat reservations (Wesleyan's "bins") ------------------
    # course_id -> {group: reserved seats}, where group is a class year
    # ("First-Year") or a major/department code ("ECON"). Reserved seats
    # are only usable by that group; capacity minus all reservations stays
    # open to everyone.
    seat_bins: dict[str, dict[str, int]] = field(default_factory=dict)

    # --- Cost-curve shape and mechanics -------------------------------------
    # 1.0 = linear (5th choice costs 5). 2.0 = convex (5th choice costs
    # 25) — encodes "deep-list courses are disproportionately worse."
    rank_cost_exponent: float = 1.0
    # Charged per empty schedule slot; must exceed the worst possible rank
    # cost of a real course, or the solver would prefer leaving slots
    # empty over granting deep-list choices.
    unassigned_penalty: float = 15.0
    k: int = 4     # courses per student
    seed: int = 0  # lottery tie-breaking (deferred acceptance)

    # --- Serialization so a policy is a shareable config file ---------------
    def to_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def from_json(cls, path: str) -> "Policy":
        with open(path) as f:
            return cls(**json.load(f))


# --- Turning a Policy + a Student into numbers the engines use --------------

def prior_shortfall(student: Student) -> float:
    """How badly last term treated this student, normalized to [0, 1].
    0 = got all first choices (or no history at all); 1 = worst plausible."""
    if student.prior_avg_rank is None:
        return 0.0
    span = PRIOR_WORST - PRIOR_BEST
    return max(0.0, min(1.0, (student.prior_avg_rank - PRIOR_BEST) / span))


def student_weight(student: Student, policy: Policy) -> float:
    """Multiplier on this student's entire cost. Class year sets the base;
    past-outcome compensation scales it up by how much the system owes
    them. Unknown class years fall back to weight 1.0 rather than crash."""
    base = policy.class_year_weights.get(student.class_year, 1.0)
    return base * (1.0 + policy.past_outcome_weight * prior_shortfall(student))


def student_tier(student: Student, policy: Policy) -> int:
    """Position in tier_order; 0 = allocated first. Class years missing
    from tier_order land in a final catch-all tier."""
    try:
        return policy.tier_order.index(student.class_year)
    except ValueError:
        return len(policy.tier_order)


def edge_cost(
    student: Student,
    course: Course,
    rank: int,
    policy: Policy,
    requirements: dict[str, set[str]],
) -> float:
    """Cost of granting this (student, course) pair, before the student
    weight multiplier. Discounts can push it negative — that reads as "the
    institution actively wants this match" (e.g. a senior into their last
    required course), which is exactly the intended semantics."""
    cost = float(rank) ** policy.rank_cost_exponent
    if course.department == student.major:
        cost -= policy.major_match_bonus
    if course.subject_course in requirements.get(student.major, set()):
        cost -= policy.requirement_weight
    return cost


def required_course_ids(
    student: Student,
    courses: dict[str, Course],
    requirements: dict[str, set[str]],
) -> set[str]:
    """The CRNs in this student's OWN preference list that satisfy a
    requirement of their major. Requirements live at the subject_course
    level; any section counts."""
    required_codes = requirements.get(student.major, set())
    return {
        c_id for c_id in student.prefs
        if c_id in courses and courses[c_id].subject_course in required_codes
    }


def priority_score(
    student: Student,
    course: Course,
    policy: Policy,
    requirements: dict[str, set[str]],
    lottery: float,
) -> tuple[float, float, float]:
    """Course-side priority for deferred acceptance: when a course is over
    capacity, it keeps the students with the LARGEST scores. Tuple compares
    lexicographically: hard tier first (negated so tier 0 sorts highest),
    then the same policy signals the ILP uses as weights/discounts, then a
    per-student lottery number so ties break randomly-but-reproducibly
    instead of alphabetically."""
    tier = -float(student_tier(student, policy)) \
        if policy.priority_mode == "tiers" else 0.0
    score = student_weight(student, policy)
    if course.department == student.major:
        score += policy.major_match_bonus
    if course.subject_course in requirements.get(student.major, set()):
        score += policy.requirement_weight
    return (tier, score, lottery)


# --- Named presets: one Policy per institutional philosophy ------------------

def make_class_year_bins(
    courses: dict[str, Course], fraction: float = 0.2
) -> dict[str, dict[str, int]]:
    """Wesleyan-style bins for every course: reserve `fraction` of seats
    per class year (4 x 20% reserved, 20% open by default). Courses too
    small to give each year a whole seat get no bins."""
    bins = {}
    for c_id, course in courses.items():
        per_year = int(course.capacity * fraction)
        if per_year >= 1:
            bins[c_id] = {year: per_year for year in CLASS_YEARS}
    return bins


def preset_status_quo(courses=None) -> Policy:
    """Middlebury today, idealized: seniority is a hard gate (seniors are
    fully allocated before juniors are considered), no equality correction."""
    return Policy(name="status_quo", priority_mode="tiers")


def preset_flat_utilitarian(courses=None) -> Policy:
    """Everyone equal, minimize total misery — the pure Model-1 philosophy."""
    return Policy(name="flat_utilitarian")


def preset_rawlsian(courses=None) -> Policy:
    """Judge the allocation only by its worst-off student, tie-broken by
    total cost."""
    return Policy(name="rawlsian", equality=1.0, rawlsian_tiebreak=True)


def preset_balanced(courses=None) -> Policy:
    """A middle-of-the-road institution: mild seniority edge, some
    compensation for a bad prior term, requirements matter, and the
    equality dial at half."""
    return Policy(
        name="balanced",
        class_year_weights={"Senior": 1.3, "Junior": 1.15,
                            "Sophomore": 1.0, "First-Year": 1.0},
        past_outcome_weight=0.5,
        requirement_weight=1.0,
        equality=0.5,
    )


def preset_wesleyan_like(courses=None) -> Policy:
    """Course-side reservations instead of student-side weights: every
    class year has seats held in every course, moderate equality."""
    bins = make_class_year_bins(courses) if courses else {}
    return Policy(name="wesleyan_like", seat_bins=bins, equality=0.3)


def preset_graduation_first(courses=None) -> Policy:
    """Progress-toward-degree dominates: getting majors into their
    required courses (including cross-department ones) outranks everything
    except outright shutouts."""
    return Policy(
        name="graduation_first",
        requirement_weight=3.0,
        guarantee_requirement=True,
        equality=0.3,
    )


PRESETS = {
    "status_quo": preset_status_quo,
    "flat_utilitarian": preset_flat_utilitarian,
    "rawlsian": preset_rawlsian,
    "balanced": preset_balanced,
    "wesleyan_like": preset_wesleyan_like,
    "graduation_first": preset_graduation_first,
}
