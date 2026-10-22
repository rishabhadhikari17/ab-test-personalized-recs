"""
Seed a realistic A/B experiment: PDP recommendations vs the current PDP (synthetic demonstration).

WHY SYNTHETIC + LOCAL: in a production deployment you'd seed assignments into a
warehouse `experiment_assignments` table and read outcomes from `orders`. This repo
instead generates a deterministic synthetic dataset into a local DuckDB file so the
whole analysis runs end-to-end on any machine with no warehouse credentials — clone,
run, green. The SQL in sql/ is standard and ports directly to a Postgres e-commerce
schema (equivalents noted at the top of each file).

Determinism: numpy seed is fixed AND variant assignment is a SHA256 hash of
(experiment_id, customer_id) — exactly the production pattern. Re-running produces
identical assignments; only the Bernoulli outcomes carry seeded noise.

Design parameters live in CONFIG below and are mirrored in PRE_REGISTRATION.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("seed")

HERE = Path(__file__).parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)

# ---------------------------------------------------------------- CONFIG
SEED = 20260617
EXPERIMENT_ID = 202
EXPERIMENT_NAME = "Personalized PDP Recommendations v2"
VARIANTS = {0: ("control", True), 1: ("treatment", False)}   # variant_id -> (name, is_control)
N_CUSTOMERS = 50_000
START = pd.Timestamp("2026-06-16", tz="UTC")
END = pd.Timestamp("2026-07-14", tz="UTC")  # 28-day cap (novelty decay guardrail)
ATTRIBUTION_DAYS = 7

# Pre-treatment category: (population share, control CR, treatment relative lift).
# These are simulation inputs; they do not require historical v2 observations.
SEGMENTS = {
    "apparel_beauty": (0.50, 0.042, +0.15),
    "electronics": (0.25, 0.032, +0.08),
    "home": (0.25, 0.036, +0.12),
}
DEVICES = {"mobile": 0.55, "desktop": 0.38, "tablet": 0.07}
COUNTRIES = {"India": 0.78, "United States": 0.14, "Other": 0.08}

# Guardrails — treatment deliberately slightly worse (forces a real tradeoff in the memo)
REFUND_RATE = {"control": 0.012, "treatment": 0.015}      # impulse buying can increase returns
REPEAT_30D = {"control": 0.22, "treatment": 0.20}         # repeat-purchase guardrail
AOV = {"control": 2500.0, "treatment": 2620.0}            # arithmetic mean paid basket (INR)
AOV_LOG_SIGMA = 0.45
PMT_FAILURE_RATE = 0.018                                  # ~flat across arms (sanity guardrail)
EXPOSURE_RATE = 1.00                                      # enroll at the first eligible PDP view


def assign_variant(cid: int) -> int:
    h = int(hashlib.sha256(f"{EXPERIMENT_ID}:{cid}".encode()).hexdigest(), 16)
    return 0 if (h % 100) < 50 else 1


def main(output_dir: Path = DATA, n_customers: int = N_CUSTOMERS) -> None:
    if n_customers < 2:
        raise ValueError("At least two customers are required.")
    shares = [values[0] for values in SEGMENTS.values()]
    if any(share < 0 for share in shares) or not np.isclose(sum(shares), 1):
        raise ValueError("Segment shares must be nonnegative and sum to one.")
    for _, control_cr, relative_lift in SEGMENTS.values():
        if not (0 < control_cr < 1 and 0 < control_cr * (1 + relative_lift) < 1):
            raise ValueError("Segment conversion probabilities must be between zero and one.")
    control_probability = sum(s * p for s, p, _ in SEGMENTS.values())
    treatment_probability = sum(s * p * (1 + lift) for s, p, lift in SEGMENTS.values())
    output_dir.mkdir(parents=True, exist_ok=True)
    log.info("Synthetic run: control p=%.6f, treatment p=%.6f; baseline is an input, not a measured result",
             control_probability, treatment_probability)
    rng = np.random.default_rng(SEED)
    n = n_customers
    cid = np.arange(1_000_000, 1_000_000 + n)

    seg_names = list(SEGMENTS)
    segment = rng.choice(seg_names, size=n, p=shares)
    device = rng.choice(list(DEVICES), size=n, p=list(DEVICES.values()))
    country = rng.choice(list(COUNTRIES), size=n, p=list(COUNTRIES.values()))
    prior_orders = rng.poisson(1.3, size=n)                 # orders in the prior window (context)

    variant = np.array([assign_variant(c) for c in cid])
    variant_name = np.where(variant == 0, "control", "treatment")

    # assignment timestamps spread across the run
    offs = rng.integers(0, int((END - START).total_seconds()), size=n)
    assigned_at = START + pd.to_timedelta(offs, unit="s")
    exposed = rng.random(n) < EXPOSURE_RATE

    # SRM is checked before generating or reporting any outcome metric.
    from analysis.stats import require_valid_srm
    chi2, p_srm = require_valid_srm(int((variant == 0).sum()), int((variant == 1).sum()))
    log.info("SRM FIRST: chi-square=%.4f, p=%.6f", chi2, p_srm)

    # Independent Bernoulli flips per customer, never per session.
    control_cr = np.array([SEGMENTS[s][1] for s in segment])
    relative_lift = np.array([SEGMENTS[s][2] for s in segment])
    p_convert = control_cr * np.where(variant == 1, 1 + relative_lift, 1.0)
    converted = rng.random(n) < p_convert
    # Separate RNG keeps guardrail additions from changing the conversion draw.
    guard_rng = np.random.default_rng(SEED + 1)
    bounced = guard_rng.random(n) < np.where(variant == 1, 0.26, 0.25)
    latency_ms = guard_rng.lognormal(np.log(900), 0.30, n) + np.where(variant == 1, 80, 0)

    assign_df = pd.DataFrame({
        "experiment_id": EXPERIMENT_ID,
        "variant_id": variant,
        "variant_name": variant_name,
        "customer_id": cid,
        "assigned_at": assigned_at,
        "assignment_source": "customer_id",
        "exposed": exposed,
        "category_segment": segment,
        "device": device,
        "country": country,
        "prior_period_orders": prior_orders,
        "bounced": bounced,
        "pdp_latency_ms": latency_ms,
    })

    # ---- orders table (mirrors ecom.orders): one paid order per converter, plus
    #      a small number of failed-payment rows for the payment-failure guardrail ----
    conv_idx = np.where(converted)[0]
    order_rows = []
    oid = 5_000_000
    for i in conv_idx:
        vname = variant_name[i]
        # E[Lognormal(mu, sigma)] = exp(mu + sigma**2 / 2).
        # Correct mu so AOV controls the mean rather than the median.
        total = float(np.round(rng.lognormal(np.log(AOV[vname]) - AOV_LOG_SIGMA**2 / 2,
                                            AOV_LOG_SIGMA), 2))
        refunded = rng.random() < REFUND_RATE[vname]
        repeat = rng.random() < REPEAT_30D[vname]
        ot = assigned_at[i] + pd.Timedelta(hours=int(rng.integers(1, ATTRIBUTION_DAYS * 24)))
        order_rows.append((oid, int(cid[i]), total, "paid", ot, refunded, repeat))
        oid += 1
    # failed-payment attempts (guardrail; ~flat across arms) for a random slice of all customers
    fail_idx = np.where(rng.random(n) < PMT_FAILURE_RATE)[0]
    for i in fail_idx:
        ot = assigned_at[i] + pd.Timedelta(hours=int(rng.integers(1, ATTRIBUTION_DAYS * 24)))
        order_rows.append((oid, int(cid[i]), 0.0, "failed", ot, False, False))
        oid += 1

    orders_df = pd.DataFrame(order_rows, columns=[
        "order_id", "customer_id", "order_total", "payment_status", "created_at", "refunded", "repeat_30d"])

    # ---- write CSVs (committed, browsable) + DuckDB (gitignored, regenerable) ----
    assign_df.to_csv(output_dir / "assignments.csv", index=False)
    orders_df.to_csv(output_dir / "orders.csv", index=False)
    (output_dir / "seed_config.json").write_text(json.dumps({
        "synthetic": True, "seed": SEED, "experiment_id": EXPERIMENT_ID,
        "experiment_name": EXPERIMENT_NAME,
        "control_probability": control_probability,
        "treatment_probability": treatment_probability,
        "expected_relative_lift": treatment_probability / control_probability - 1,
        "baseline_provenance": "Synthetic segment configuration; not measured historical data",
        "segments": {name: {"share": share, "control_cr": p,
                            "treatment_relative_lift": lift}
                     for name, (share, p, lift) in SEGMENTS.items()},
        "refund_rate": REFUND_RATE, "aov_mean_inr": AOV,
        "aov_log_sigma": AOV_LOG_SIGMA,
        "customers": n,
    }, indent=2) + "\n", encoding="utf-8")

    db = output_dir / "experiment.duckdb"
    if db.exists():
        db.unlink()
    con = duckdb.connect(str(db))
    con.execute("create table experiment_assignments as select * from assign_df")
    con.execute("create table orders as select * from orders_df")
    experiments_df = pd.DataFrame([{
        "experiment_id": EXPERIMENT_ID, "name": EXPERIMENT_NAME,
        "owner": "growth-team", "status": "synthetic",
        "primary_metric": "customer_conversion_rate", "start_date": START, "end_date": END,
    }])
    variants_df = pd.DataFrame([
        {"variant_id": vid, "experiment_id": EXPERIMENT_ID, "variant_name": name,
         "allocation_pct": 50.0, "is_control": is_control}
        for vid, (name, is_control) in VARIANTS.items()
    ])
    con.execute("create table experiments as select * from experiments_df")
    con.execute("create table experiment_variants as select * from variants_df")
    con.close()

    n_c = int((variant == 0).sum()); n_t = int((variant == 1).sum())
    x_c = int(converted[variant == 0].sum()); x_t = int(converted[variant == 1].sum())
    log.info("seeded %d customers  | control %d (conv %d, %.3f) | treatment %d (conv %d, %.3f)",
             n, n_c, x_c, x_c / n_c, n_t, x_t, x_t / n_t)
    log.info("observed relative lift: %+.1f%%  | orders rows: %d  | wrote CSVs + experiment.duckdb",
             100 * ((x_t / n_t) / (x_c / n_c) - 1), len(orders_df))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DATA)
    args = parser.parse_args()
    main(output_dir=args.output_dir)
