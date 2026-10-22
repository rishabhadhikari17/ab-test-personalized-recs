# Baseline inputs for Option 2

The simulation baseline is fully specified by the supplied category settings:
`0.50 * 0.042 + 0.25 * 0.032 + 0.25 * 0.036 = 0.038`.
This is an expected **3.8%**, not a measurement from historical data.
The expected treatment rate is **4.287%**, a **12.82%** relative lift.

Real v2 data does not exist yet and is not required for this exercise.
`seed_experiment.py` generates all required assignments, orders, and local DuckDB
metadata. `data/seed_config.json` records their synthetic provenance.

The inherited `analysis/baseline.py` and `sql/00_baseline_30d.sql` remain optional
utilities for a future real experiment. That query assumes a `session_events`
schema and a June 15, 2026 cutoff. It is an unverified draft, measures period
conversion rather than mature seven-day cohorts, and is not run against the
synthetic database. Validate schema, dates, and metric comparability before use.
