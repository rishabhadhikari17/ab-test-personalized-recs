#!/usr/bin/env python3
"""Render the three README hero figures from the synthetic experiment data.

Run from the repo root:  python make_figures.py

Reads data/experiment.duckdb (tables: experiment_assignments, orders) if
available, else falls back to data/assignments.csv + data/orders.csv. Every
number on every chart is computed from the data and the CIs come straight out
of analysis/stats.py — nothing is hand-typed, so the figures can never drift
from the stats module or the seed.

Outputs (200 dpi PNGs, white background, tight bbox):
    figures/01_lift_forest.png        — hero forest plot of relative lift + 95% CI
    figures/02_conversion_compare.png — control-vs-treatment dumbbell
    figures/03_guardrails.png         — 1x4 guardrail small-multiples

matplotlib only. No seaborn.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Keep matplotlib's writable cache inside the workspace.
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parent / ".cache" / "matplotlib"))

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")  # headless / reproducible
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

# --------------------------------------------------------------------------
# Paths — resolve everything relative to this file so it runs from anywhere.
# --------------------------------------------------------------------------
REPO = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(REPO, "data")
FIGDIR = os.path.join(REPO, "figures")
sys.path.insert(0, os.path.join(REPO, "analysis"))

import stats as ab  # noqa: E402  (after sys.path tweak; the shared math module)


def fmt_p(p: float) -> str:
    """Display a p-value computed from the current data."""
    return f"p = {p:.3f}"


from seed_experiment import EXPERIMENT_ID
SOURCE_NOTE = "Synthetic PDP recommendation experiment · seed_experiment.py"

# ==========================================================================
# DESIGN SYSTEM  — one shared palette + rcParams for all three figures (kept
# in this file so make_figures.py is self-contained and the notebook reuses it)
# ==========================================================================
CONTROL = "#5B6770"    # slate grey — control / baseline, ALWAYS
TREATMENT = "#1F6FEB"  # confident blue — treatment, ALWAYS
POSITIVE = "#1F6FEB"   # significant favorable
NULL = "#9AA5B1"       # not significant ("we can't tell")
NEGATIVE = "#E8833A"   # significant unfavorable / guardrail breach (amber, NOT red)
INK = "#1A1A1A"        # text + zero / reference lines
GRID = "#E3E6EA"       # hairline gridlines


def apply_theme() -> None:
    """One shared theme for all figures — colorblind-safe, no red/green."""
    plt.rcParams.update({
        "figure.dpi": 150,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlepad": 14,
        "axes.labelsize": 10.5,
        "axes.edgecolor": INK,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.axisbelow": True,
        "xtick.labelsize": 9.5,
        "ytick.labelsize": 9.5,
        "grid.color": GRID,
        "grid.linewidth": 0.8,
        "legend.frameon": False,
        "legend.fontsize": 9.5,
    })


def value_grid(ax, axis: str = "x") -> None:
    """Hairline grid on the value axis only."""
    ax.grid(True, axis=axis, color=GRID, linewidth=0.8, zorder=0)
    ax.grid(False, axis="y" if axis == "x" else "x")


def subtitle(ax, text: str, dy: float = 22) -> None:
    """Grey method caveat under the (already-set) bold title."""
    ax.annotate(text, xy=(0, 1.0), xytext=(0, dy), xycoords="axes fraction",
                textcoords="offset points", ha="left", va="bottom",
                fontsize=9.5, color="#5A6470")


def source_footnote(fig) -> None:
    fig.text(0.005, 0.005, SOURCE_NOTE, ha="left", va="bottom",
             fontsize=8, color="#8A929B")


# ==========================================================================
# DATA LOADING  — duckdb if present, else CSV; identical downstream frame.
# ==========================================================================
def _load_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    duckdb_path = os.path.join(DATA, "experiment.duckdb")
    if os.path.exists(duckdb_path):
        try:
            import duckdb
            con = duckdb.connect(duckdb_path, read_only=True)
            assign = con.execute(
                "select variant_name, customer_id, category_segment, assigned_at, bounced, pdp_latency_ms "
                f"from experiment_assignments where experiment_id = {EXPERIMENT_ID}"
            ).fetchdf()
            orders = con.execute(
                "select customer_id, order_total, payment_status, refunded, repeat_30d, created_at "
                "from orders"
            ).fetchdf()
            con.close()
            return assign, orders
        except ImportError:
            pass  # fall through to CSV
    assign = pd.read_csv(os.path.join(DATA, "assignments.csv"))
    assign = assign[assign["experiment_id"] == EXPERIMENT_ID]
    assign = assign[["variant_name", "customer_id", "category_segment", "assigned_at", "bounced", "pdp_latency_ms"]]
    orders = pd.read_csv(os.path.join(DATA, "orders.csv"))
    orders = orders[["customer_id", "order_total", "payment_status",
                     "refunded", "repeat_30d", "created_at"]]
    return assign, orders


def validate_assignments(assign: pd.DataFrame) -> tuple[float, float]:
    if assign["customer_id"].isna().any() or assign["customer_id"].duplicated().any():
        raise ValueError("Expected exactly one assignment per customer.")
    if not assign["variant_name"].isin(["control", "treatment"]).all():
        raise ValueError("Unknown or missing variant.")
    counts = assign["variant_name"].value_counts()
    return ab.require_valid_srm(int(counts.get("control", 0)), int(counts.get("treatment", 0)))


def _customer_outcomes(assign: pd.DataFrame, orders: pd.DataFrame) -> pd.DataFrame:
    """Roll orders up to one row per assigned customer (the randomization unit).

    Mirrors sql/03 + sql/04: ITT denominator = ALL assigned customers
    (count(*)), so a customer with no order is a non-converter, not dropped.
    """
    validate_assignments(assign)  # gate BEFORE reading outcome metrics
    o = orders.merge(assign[["customer_id", "assigned_at"]], on="customer_id", how="inner", validate="many_to_one")
    created = pd.to_datetime(o["created_at"], utc=True)
    assigned = pd.to_datetime(o["assigned_at"], utc=True)
    o = o[(created >= assigned) & (created < assigned + pd.Timedelta(days=7))].copy()
    paid = o["payment_status"] == "paid"
    o["converted"] = paid.astype(int)
    o["revenue"] = np.where(paid, o["order_total"], 0.0)
    o["refunded_paid"] = (paid & o["refunded"].astype(bool)).astype(int)
    o["repeated_paid"] = (paid & o["repeat_30d"].astype(bool)).astype(int)
    o["pmt_failure"] = (o["payment_status"] == "failed").astype(int)

    agg = o.groupby("customer_id").agg(
        converted=("converted", "max"),
        revenue=("revenue", "sum"),
        refunded=("refunded_paid", "max"),
        repeated=("repeated_paid", "max"),
        had_pmt_failure=("pmt_failure", "max"),
    )
    # LEFT join keeps every assigned customer (ITT); fill non-orderers with 0.
    cust = assign.merge(agg, on="customer_id", how="left")
    for col in ["converted", "revenue", "refunded", "repeated", "had_pmt_failure"]:
        cust[col] = cust[col].fillna(0)
    return cust


# ==========================================================================
# METRICS  — compute the headline, segment, and guardrail numbers from data.
# ==========================================================================
def compute_metrics(cust: pd.DataFrame) -> dict:
    chi2, p_srm = validate_assignments(cust)

    def arm(name: str) -> pd.DataFrame:
        return cust[cust["variant_name"] == name]

    c, t = arm("control"), arm("treatment")
    n_c, n_t = len(c), len(t)
    x_c, x_t = int(c["converted"].sum()), int(t["converted"].sum())

    overall = ab.lift_with_ci(x_c, n_c, x_t, n_t)

    # ---- segment lifts (category) ---------------------------------------
    segs = []
    for seg in cust["category_segment"].dropna().unique():
        sc = c[c["category_segment"] == seg]
        st = t[t["category_segment"] == seg]
        r = ab.lift_with_ci(int(sc["converted"].sum()), len(sc),
                            int(st["converted"].sum()), len(st))
        segs.append({
            "segment": seg,
            "p_c": r.p_control, "p_t": r.p_treatment,
            "rel": r.rel_lift, "rel_lo": r.rel_ci[0], "rel_hi": r.rel_ci[1],
            "p_value": r.p_value,
        })
    seg_df = pd.DataFrame(segs).sort_values("rel", ascending=False).reset_index(drop=True)

    # Bonferroni over the 9 segment tests (3 category + 3 device + 3 country).
    bonf_alpha = ab.bonferroni_alpha(0.05, 9)

    # ---- guardrails -----------------------------------------------------
    conv_c = c[c["converted"] == 1]
    conv_t = t[t["converted"] == 1]
    nc_conv, nt_conv = len(conv_c), len(conv_t)

    refund = ab.lift_with_ci(int(conv_c["refunded"].sum()), nc_conv,
                            int(conv_t["refunded"].sum()), nt_conv)
    repeat = ab.lift_with_ci(int(conv_c["repeated"].sum()), nc_conv,
                            int(conv_t["repeated"].sum()), nt_conv)
    aov_c = conv_c["revenue"].sum() / nc_conv
    aov_t = conv_t["revenue"].sum() / nt_conv
    pmt = ab.lift_with_ci(int(c["had_pmt_failure"].sum()), n_c,
                         int(t["had_pmt_failure"].sum()), n_t)

    return {
        "srm_chi2": chi2, "srm_p": p_srm,
        "bounce_c": c["bounced"].mean(), "bounce_t": t["bounced"].mean(),
        "latency_c": c["pdp_latency_ms"].quantile(.95), "latency_t": t["pdp_latency_ms"].quantile(.95),
        "n_c": n_c, "n_t": n_t, "x_c": x_c, "x_t": x_t,
        "overall": overall, "seg_df": seg_df, "bonf_alpha": bonf_alpha,
        "refund": refund, "repeat": repeat, "pmt": pmt,
        "aov_c": aov_c, "aov_t": aov_t,
    }


# Pretty labels for category segments.
SEG_LABELS = {
    "apparel_beauty": "apparel/beauty",
    "electronics": "electronics",
    "home": "home",
}


def _sig_color(lo: float, hi: float, alpha_sig: bool = False) -> tuple[str, str]:
    """Colour a CI by where it sits vs zero (no glyph — keep it clean)."""
    if lo > 0:
        return (POSITIVE, "")
    if hi < 0:
        return (NEGATIVE, "")
    return (NULL, "")


# ==========================================================================
# FIGURE 1 (HERO) — relative-lift forest plot
# ==========================================================================
def fig1_forest(m: dict) -> str:
    ov = m["overall"]
    seg_df = m["seg_df"]
    bonf = m["bonf_alpha"]

    # Build rows top->bottom: OVERALL, [group label], segments desc by point est.
    fig, ax = plt.subplots(figsize=(7.2, 4.6))

    rows = []  # (y, label, pt, lo, hi, color, glyph, is_overall)
    seg_sorted = seg_df  # already sorted descending by rel
    n_seg = len(seg_sorted)

    # y positions: segments packed at the bottom (one unit apart), a small gap,
    # the group label, then OVERALL as the top anchor — compact, no dead space.
    for i, (_, r) in enumerate(seg_sorted.iterrows()):
        y = (n_seg - 1) - i            # home=2, apparel=1, electronics=0
        sig = r["p_value"] < bonf
        color, glyph = _sig_color(r["rel_lo"], r["rel_hi"], sig)
        rows.append((y, SEG_LABELS.get(r["segment"], r["segment"]),
                     r["rel"] * 100, r["rel_lo"] * 100, r["rel_hi"] * 100,
                     color, glyph, False))

    y_group = n_seg - 0.25            # group label just above the top segment
    y_overall = n_seg + 0.9           # OVERALL anchor above the group label

    # overall row (favorable & CI excludes 0 -> blue, larger anchor marker)
    o_color, _ = _sig_color(ov.rel_ci[0], ov.rel_ci[1], ov.p_value < 0.05)
    rows.insert(0, (y_overall, "OVERALL", ov.rel_lift * 100,
                    ov.rel_ci[0] * 100, ov.rel_ci[1] * 100, o_color, "", True))

    # zero reference line ("no effect")
    ax.axvline(0, color=INK, linewidth=1.2, zorder=1)
    ax.annotate("no effect", xy=(0, y_overall + 0.45), ha="center", va="bottom",
                fontsize=8.5, color="#5A6470")

    for (y, label, pt, lo, hi, color, glyph, is_overall) in rows:
        ms = 10 if is_overall else 7
        elw = 1.8 if is_overall else 1.4
        ax.errorbar(pt, y, xerr=[[pt - lo], [hi - pt]], fmt="o",
                    color=color, ecolor=color, markersize=ms,
                    elinewidth=elw, capsize=3, capthick=elw, zorder=3)

    # thin grey rule beneath OVERALL to set it apart as the anchor
    ax.axhline((y_overall + y_group) / 2, color=GRID, linewidth=1.0, zorder=0)

    # group label "By category" in the left margin, between OVERALL and segments
    ax.text(-0.245, y_group, "By category", transform=ax.get_yaxis_transform(),
            va="center", ha="left", fontsize=9.5, color="#5A6470",
            fontweight="bold")

    # y tick labels
    yticks = [r[0] for r in rows]
    ylabels = []
    for (_, label, *_rest, is_overall) in rows:
        ylabels.append(label)
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels)
    # bold the OVERALL label
    for tl, (_, _l, *_r, is_overall) in zip(ax.get_yticklabels(), rows):
        if is_overall:
            tl.set_fontweight("bold")
            tl.set_color(INK)

    # x axis: relative lift %, ticks -10..+25
    ax.set_xlim(min(r[3] for r in rows) - 5, max(r[4] for r in rows) + 5)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax.set_xlabel("Relative lift vs control")
    value_grid(ax, "x")

    # right-margin value gutter
    for (y, label, pt, lo, hi, color, glyph, is_overall) in rows:
        txt = f"{pt:+.1f}%  [{lo:+.1f}, {hi:+.1f}]{glyph}"
        ax.text(1.012, y, txt, transform=ax.get_yaxis_transform(),
                va="center", ha="left", fontsize=9,
                color=INK if is_overall else color,
                fontweight="bold" if is_overall else "normal")

    ax.set_ylim(-0.7, y_overall + 0.7)
    ax.set_title(
        f"PDP recommendations: {ov.rel_lift:+.1%} observed conversion lift",
        loc="left", fontsize=12.5)
    subtitle(ax,
             "Relative lift vs control, with 95% confidence intervals · two-proportion z-test",
             dy=44)
    # Nominal 95% intervals; adjusted segment tests are in the notebook.
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=POSITIVE,
               markersize=8, label="CI excludes 0 (significant)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor=NULL,
               markersize=8, label="CI crosses 0 (not significant)"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.0, -0.155),
              ncol=2, fontsize=8.5, handletextpad=0.4, columnspacing=1.4)

    source_footnote(fig)
    fig.subplots_adjust(left=0.20, right=0.74, top=0.74, bottom=0.24)
    out = os.path.join(FIGDIR, "01_lift_forest.png")
    fig.savefig(out)
    plt.close(fig)
    return out


# ==========================================================================
# FIGURE 2 — conversion-rate dumbbell (control vs treatment)
# ==========================================================================
def fig2_dumbbell(m: dict) -> str:
    ov = m["overall"]
    p_c, p_t = ov.p_control * 100, ov.p_treatment * 100
    n_c, n_t = m["n_c"], m["n_t"]
    abs_pp = ov.abs_lift * 100
    rel = ov.rel_lift * 100
    pval = ov.p_value
    # per-arm 95% CI on the rate (Wald)
    se_c = np.sqrt(ov.p_control * (1 - ov.p_control) / n_c) * 100
    se_t = np.sqrt(ov.p_treatment * (1 - ov.p_treatment) / n_t) * 100

    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    y = 0.5

    # connector with arrowhead -> treatment (the gap IS the story)
    ax.annotate("", xy=(p_t, y), xytext=(p_c, y),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.6,
                                shrinkA=11, shrinkB=11))
    # dots — per-arm CIs are tiny at n~25k and only clutter a zoomed axis;
    # the overall lift CI is carried by the forest plot (fig 1).
    ax.plot(p_c, y, "o", color=CONTROL, markersize=13, zorder=3)
    ax.plot(p_t, y, "o", color=TREATMENT, markersize=13, zorder=3)

    # labels above
    ax.annotate(f"Control {p_c:.2f}%", xy=(p_c, y), xytext=(0, 16),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=10.5, fontweight="bold", color=CONTROL)
    ax.annotate(f"Treatment {p_t:.2f}%", xy=(p_t, y), xytext=(0, 16),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=10.5, fontweight="bold", color=TREATMENT)
    # n labels below
    ax.annotate(f"n = {n_c:,}", xy=(p_c, y), xytext=(0, -20),
                textcoords="offset points", ha="center", va="top",
                fontsize=9, color="#5A6470")
    ax.annotate(f"n = {n_t:,}", xy=(p_t, y), xytext=(0, -20),
                textcoords="offset points", ha="center", va="top",
                fontsize=9, color="#5A6470")

    # callout bracket between the two points
    mid = (p_c + p_t) / 2
    ax.annotate(f"{abs_pp:+.2f}pp  ({rel:+.1f}%, {fmt_p(pval)})",
                xy=(mid, y), xytext=(mid, y + 0.30), ha="center", va="bottom",
                fontsize=10, fontweight="bold", color=INK)

    axis_start = max(0, min(p_c, p_t) - 0.4)
    ax.set_xlim(axis_start, max(p_c, p_t) + 0.4)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(decimals=1))
    ax.set_xlabel("Customer-level conversion rate")
    ax.set_ylim(0, 1.15)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    value_grid(ax, "x")

    # truncation disclaimer — integrity signal
    ax.annotate(f"axis starts at {axis_start:.2f}%, not 0", xy=(1, 0), xytext=(0, -38),
                xycoords="axes fraction", textcoords="offset points",
                ha="right", va="top", fontsize=8, color="#8A929B", style="italic")

    ax.set_title(
        f"{p_t:.2f}% vs {p_c:.2f}% — {abs_pp:+.2f}pp absolute, {rel:+.1f}% relative lift",
        loc="left")
    subtitle(ax,
             f"Customer-level conversion · SRM p = {m['srm_p']:.3f} · enrollment at PDP view", dy=26)
    source_footnote(fig)
    fig.subplots_adjust(left=0.06, right=0.97, top=0.70, bottom=0.26)
    out = os.path.join(FIGDIR, "02_conversion_compare.png")
    fig.savefig(out)
    plt.close(fig)
    return out


# ==========================================================================
# FIGURE 3 — guardrail small-multiples (1x4 paired horizontal bars)
# ==========================================================================
def fig3_guardrails(m: dict) -> str:
    refund = m["refund"]
    repeat = m["repeat"]
    aov_c, aov_t = m["aov_c"], m["aov_t"]
    pmt = m["pmt"]

    # Each panel carries its own metric + status. CIs (refund/repeat) come from
    # lift_with_ci on the (treatment - control) difference, in percentage points.
    refund_ci = (refund.abs_ci[0] * 100, refund.abs_ci[1] * 100)
    repeat_ci = (repeat.abs_ci[0] * 100, repeat.abs_ci[1] * 100)

    panels = [
        {
            "title": "Refund rate", "c": refund.p_control * 100,
            "t": refund.p_treatment * 100, "fmt": "{:.2f}%",
            "tcolor": TREATMENT, "glyph": "",
            "delta": f"{refund.abs_lift*100:+.2f}pp", "note": "lower is better",
            "ci": refund_ci,
        },
        {
            "title": "30-day repeat rate", "c": repeat.p_control * 100,
            "t": repeat.p_treatment * 100, "fmt": "{:.1f}%",
            "tcolor": TREATMENT, "glyph": "",
            "delta": f"{(repeat.p_treatment - repeat.p_control)*100:+.1f}pp",
            "note": "higher is better",
            "ci": repeat_ci,
        },
        {
            "title": "Average order value", "c": aov_c, "t": aov_t,
            "fmt": "₹{:,.0f}",
            "tcolor": TREATMENT, "glyph": "",
            "delta": f"₹{aov_t - aov_c:+,.0f}",
            "note": "higher is better", "ci": None,
        },
        {
            "title": "Payment failures", "c": pmt.p_control * 100,
            "t": pmt.p_treatment * 100, "fmt": "{:.1f}%",
            "tcolor": TREATMENT, "glyph": "",
            "delta": f"{pmt.abs_lift*100:+.2f}pp", "note": "lower is better",
            "ci": None,
        },
    ]

    fig, axes = plt.subplots(1, 4, figsize=(9.6, 3.8))

    for ax, p in zip(axes, panels):
        vals = [p["c"], p["t"]]
        colors = [CONTROL, p["tcolor"]]
        ypos = [1, 0]  # control on top, treatment below
        ax.barh(ypos, vals, color=colors, height=0.5, zorder=3)

        ax.set_yticks([1, 0])
        ax.set_yticklabels(["Control", "Treatment"], fontsize=9)
        # Right headroom keeps labels inside their own panel.
        reach = max(vals)
        ax.set_xlim(0, reach * 1.5)

        # Difference intervals are printed below, not drawn as arm-rate intervals.
        for yb, v in zip(ypos, vals):
            label = p["fmt"].format(v)
            ax.annotate(label, xy=(v, yb), xytext=(6, 0),
                        textcoords="offset points", va="center", ha="left",
                        fontsize=9.5, fontweight="bold", color=INK, zorder=6)
        if p["ci"] is not None:
            ax.text(0, -0.12, f"Difference 95% CI: [{p['ci'][0]:+.2f}, {p['ci'][1]:+.2f}]pp",
                    transform=ax.transAxes, fontsize=7)
        ax.set_ylim(-0.7, 1.7)
        # panel header: metric name, then a delta+glyph line, then the
        # direction note — stacked so nothing overlaps.
        ax.set_title(p["title"], loc="left", fontsize=10, pad=34)
        ax.annotate(f"{p['delta']}  {p['glyph']}", xy=(0, 1), xytext=(0, 18),
                    xycoords="axes fraction", textcoords="offset points",
                    ha="left", va="bottom", fontsize=10.5, fontweight="bold",
                    color=p["tcolor"])
        ax.annotate(p["note"], xy=(0, 1), xytext=(0, 5),
                    xycoords="axes fraction", textcoords="offset points",
                    ha="left", va="bottom", fontsize=8, color="#8A929B",
                    style="italic")
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)  # no x-axis; labels are on bars
        value_grid(ax, "x")
        ax.set_xticks([])  # values are annotated on the bars; keep panels clean

    fig.suptitle(
        "Recommendation guardrails: compare benefits with possible harms",
        x=0.01, ha="left", fontsize=13, fontweight="bold", y=1.04)
    fig.text(0.01, 0.965,
             "Guardrail metrics — the cost side of the decision. "
             "Intervals show uncertainty; thresholds are evaluated in the memo.",
             ha="left", va="top", fontsize=9.5, color="#5A6470")
    source_footnote(fig)
    fig.subplots_adjust(left=0.05, right=0.985, top=0.72, bottom=0.18, wspace=0.85)
    out = os.path.join(FIGDIR, "03_guardrails.png")
    fig.savefig(out)
    plt.close(fig)
    return out


# ==========================================================================
def main() -> None:
    os.makedirs(FIGDIR, exist_ok=True)
    apply_theme()

    assign, orders = _load_tables()
    chi2, p_srm = validate_assignments(assign)
    print(f"SRM FIRST: chi-square={chi2:.4f}, p={p_srm:.6f}")
    cust = _customer_outcomes(assign, orders)
    m = compute_metrics(cust)

    # Print the computed numbers so a reviewer can eyeball them vs the README.
    ov = m["overall"]
    print(f"Overall: control {ov.p_control*100:.2f}% (n={m['n_c']:,}) "
          f"vs treatment {ov.p_treatment*100:.2f}% (n={m['n_t']:,})")
    print(f"  rel lift {ov.rel_lift*100:+.1f}% "
          f"[{ov.rel_ci[0]*100:+.1f}, {ov.rel_ci[1]*100:+.1f}]  "
          f"z={ov.z:.2f}  p={ov.p_value:.3f}")
    print(f"Bonferroni alpha (9 tests): {m['bonf_alpha']:.4f}")
    print("Segments (desc by rel lift):")
    for _, r in m["seg_df"].iterrows():
        print(f"  {r['segment']:<16} {r['p_c']*100:.2f}->{r['p_t']*100:.2f}  "
              f"rel {r['rel']*100:+.1f}%  p={r['p_value']:.3f}")
    print(f"Refund {m['refund'].p_control*100:.2f}->{m['refund'].p_treatment*100:.2f}%, "
          f"Repeat {m['repeat'].p_control*100:.1f}->{m['repeat'].p_treatment*100:.1f}%, "
          f"AOV ₹{m['aov_c']:,.0f}->₹{m['aov_t']:,.0f}")

    paths = [fig1_forest(m), fig2_dumbbell(m), fig3_guardrails(m)]
    print("\nWrote:")
    for p in paths:
        print(" ", os.path.relpath(p, REPO))


if __name__ == "__main__":
    main()
