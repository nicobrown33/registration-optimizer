"""Add a synthetic `prior_avg_rank` column to the preferences CSV.

DISCLOSURE: this column is invented, like the students themselves. It
stands in for "how well did registration go for this student last term" —
the average preference rank of the courses they actually received (1.0 =
got all first choices, 8.0 = got deep-list leftovers). The real Banner
export has no per-student history, so a policy slider that compensates
students who did badly last term needs a made-up-but-plausible signal.

Rules:
- First-Years have no prior term, so their cell is left blank (loaded as
  None) — policy code must treat "no history" as "no compensation."
- Everyone else gets a seeded uniform draw in [1.0, 8.0], rounded to 2
  decimals. Seeded (not truly random) so re-running this script on the
  same input file reproduces the identical column — the experiments stay
  reproducible.

Usage:  python preprocessing/add_past_outcomes.py [path/to/preferences.csv]
Re-running overwrites the column deterministically; it never touches any
other column. No regopt import on purpose, same as export_real_courses.py.
"""

import random
import sys

import pandas as pd

SEED = 42
WORST_PLAUSIBLE_AVG = 8.0  # deep-list outcome; ranks run 1..10 but an
BEST_PLAUSIBLE_AVG = 1.0   # *average* at the extremes is rare


def main(path: str) -> None:
    df = pd.read_csv(path, dtype={f"rank{i}": str for i in range(1, 11)})
    rng = random.Random(SEED)

    values: list[float | None] = []
    for class_year in df["class_year"]:
        if class_year == "First-Year":
            values.append(None)  # pandas writes None as an empty cell
        else:
            values.append(
                round(rng.uniform(BEST_PLAUSIBLE_AVG, WORST_PLAUSIBLE_AVG), 2)
            )

    df["prior_avg_rank"] = values
    df.to_csv(path, index=False)

    n_blank = sum(v is None for v in values)
    print(f"wrote prior_avg_rank to {path}: {len(values)} rows, "
          f"{n_blank} blank (First-Years), seed={SEED}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/preferences_real.csv")
