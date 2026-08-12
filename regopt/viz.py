"""One chart: where each policy puts students on their preference lists.

A horizontal 100%-stacked bar per run — segments are ordered outcome
buckets (1st choice ... no course). Rank buckets are *ordinal*, so color
is a single-hue sequential ramp (dark = best outcome), not categorical
hues; "no course" is a neutral gray, deliberately outside the ramp — it
means absence, not a fifth rank. Ramp validated with the dataviz
palette validator (ordinal mode, light surface): monotone lightness,
single hue, light end 2.06:1 vs surface.
"""

import matplotlib
matplotlib.use("Agg")  # render to file; never needs a display
import matplotlib.pyplot as plt

from regopt.metrics import K
from regopt.models import Student

# Buckets, best -> worst, then absence. 4th-10th is one bucket: past the
# top three the reader's question is "how deep in the list?" not "which
# exact rank?"
BUCKETS = ["1st choice", "2nd", "3rd", "4th–10th", "no course"]
RAMP = ["#184f95", "#2a78d6", "#5598e7", "#86b6ef"]  # blue 600/450/350/250
NO_COURSE = "#898781"   # neutral muted gray — absence, not a rank
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"


def bucket_shares(
    assignment: dict[str, list[str]], students: list[Student]
) -> list[float]:
    """Fractions of all n*K schedule slots landing in each bucket."""
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


def plot_rank_distribution(
    runs: dict[str, dict[str, list[str]]],
    students: list[Student],
    out_path: str,
    subtitle: str = "",
) -> None:
    """One row per run (insertion order, top first), segments = BUCKETS.
    `runs` maps a display label to an assignment dict."""
    labels = list(runs)
    shares = {label: bucket_shares(runs[label], students) for label in labels}

    plt.rcParams["font.family"] = ["Helvetica Neue", "Arial", "sans-serif"]
    fig_h = 1.1 + 0.52 * len(labels)
    fig, ax = plt.subplots(figsize=(9.6, fig_h), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)

    colors = RAMP + [NO_COURSE]
    ys = range(len(labels) - 1, -1, -1)  # first run on top
    for y, label in zip(ys, labels):
        left = 0.0
        for share, color in zip(shares[label], colors):
            # bar height 0.55 = thin marks; the surface-colored edge is
            # the 2px spacer between stacked segments.
            ax.barh(y, share, left=left, height=0.55, color=color,
                    edgecolor=SURFACE, linewidth=1.4)
            left += share
        # Selective direct labels: the headline number of each row (the
        # 1st-choice share, inside the dark segment where white ink
        # clears it) and the failure signal (the no-course share, outside
        # the right end) — not a number on every segment.
        first = shares[label][0]
        ax.text(first / 2, y, f"{first:.0%}", va="center", ha="center",
                color="#ffffff", fontsize=8.5)
        none_share = shares[label][4]
        if none_share >= 0.002:
            ax.text(1.005, y, f"{none_share:.1%} none", va="center",
                    ha="left", color=INK_SECONDARY, fontsize=8)

    ax.set_yticks(list(ys))
    ax.set_yticklabels(labels, fontsize=9.5, color=INK)
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"],
                       fontsize=8.5, color=INK_MUTED)
    ax.set_xlabel("share of all schedule slots", fontsize=9,
                  color=INK_SECONDARY)

    # Recessive chrome: hairline vertical grid behind the bars, a single
    # baseline, no box.
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(length=0)

    # Stacked header, bottom-up in axes coordinates: legend row sits at
    # 1.005 (its top lands near 1.09), subtitle above it, title on top.
    ax.set_title("Where each policy puts students on their preference lists",
                 loc="left", fontsize=12, color=INK, y=1.17)
    if subtitle:
        ax.text(0, 1.105, subtitle, transform=ax.transAxes,
                fontsize=9, color=INK_SECONDARY)

    # Legend: five buckets -> always present, one row above the plot,
    # frameless, text in ink (the swatch carries the color).
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors]
    ax.legend(handles, BUCKETS, ncol=len(BUCKETS), loc="lower left",
              bbox_to_anchor=(0, 1.005), frameon=False, fontsize=8,
              handlelength=1.1, handleheight=1.1, labelcolor=INK_SECONDARY)

    fig.tight_layout()
    fig.savefig(out_path, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")
