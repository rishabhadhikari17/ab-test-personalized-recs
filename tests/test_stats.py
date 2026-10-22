"""Pin the statistics so the notebook's numbers are trustworthy, and pin the
assignment hash so 'deterministic' is enforced, not just claimed."""
import hashlib
import sys
from pathlib import Path

import pytest
import duckdb
import pandas as pd
from scipy.stats import norm
from statsmodels.stats.proportion import proportions_ztest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stats as ab  # noqa: E402
import seed_experiment as seed
import make_figures as figures


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    path = tmp_path_factory.mktemp("recommendations")
    seed.main(output_dir=path)
    return path


def test_ztest_matches_statsmodels():
    # cross-check our hand-rolled pooled z-test against statsmodels
    x_c, n_c, x_t, n_t = 1010, 26031, 1118, 25969
    z, p = ab.two_proportion_ztest(x_c, n_c, x_t, n_t)
    z_sm, p_sm = proportions_ztest([x_t, x_c], [n_t, n_c], alternative="two-sided")
    assert abs(z - z_sm) < 1e-6
    assert abs(p - p_sm) < 1e-6


def test_seeded_sql_test_matches_statsmodels(seeded):
    # Verify the full seeded readout without requiring a significant outcome.
    root = Path(__file__).resolve().parents[1]
    with duckdb.connect(str(seeded / "experiment.duckdb"), read_only=True) as con:
        counts = con.execute((root / "sql/01_srm_check.sql").read_text(encoding="utf-8")).df().set_index("variant_name")
        ab.require_valid_srm(int(counts.loc["control", "n"]), int(counts.loc["treatment", "n"]))
        m = con.execute((root / "sql/03_per_variant_metrics.sql").read_text(encoding="utf-8")).df().set_index("variant_name")
    z, p = ab.two_proportion_ztest(int(m.loc["control", "converters"]), int(m.loc["control", "customers"]),
                                 int(m.loc["treatment", "converters"]), int(m.loc["treatment", "customers"]))
    expected_z, expected_p = proportions_ztest(
        m.loc[['treatment', 'control'], 'converters'].to_numpy(dtype=float),
        m.loc[['treatment', 'control'], 'customers'].to_numpy(dtype=float))
    assert z == pytest.approx(expected_z)
    assert p == pytest.approx(expected_p)


def test_lift_ci_excludes_zero_when_significant():
    r = ab.lift_with_ci(1010, 26031, 1118, 25969)
    assert r.abs_lift > 0
    assert r.abs_ci[0] > 0          # CI excludes zero => significant
    assert 0.05 < r.rel_lift < 0.20  # current recommendation fixture


def test_srm_passes_on_balanced_split():
    chi2, p = ab.chisq_srm(26031, 25969)
    assert p >= 0.001               # not a mismatch


def test_srm_flags_broken_split():
    chi2, p = ab.chisq_srm(26500, 23500)   # 53/47 on 50k => clearly broken
    assert p < 0.001


def test_assignment_is_deterministic_and_balanced():
    assign = seed.assign_variant
    assigned = [assign(c) for c in range(1_000_000, 1_010_000)]
    # deterministic: same input, same bucket
    assert assign(1_234_567) == assign(1_234_567)
    # roughly balanced
    share = sum(assigned) / len(assigned)
    assert 0.47 < share < 0.53
    for cid in [1_234_567, 1_000_001]:
        expected = int(hashlib.sha256(f"{seed.EXPERIMENT_ID}:{cid}".encode()).hexdigest(), 16) % 100 >= 50
        assert assign(cid) == int(expected)


def test_srm_blocks_outcomes_before_metric_access():
    # Deliberately omit outcome columns: SRM must fail before trying to read them.
    broken = pd.DataFrame({"customer_id": range(10000),
                           "variant_name": ["control"] * 6000 + ["treatment"] * 4000})
    with pytest.raises(ValueError, match="SRM failed"):
        figures.compute_metrics(broken)
    with pytest.raises(ValueError, match="both control and treatment"):
        ab.require_valid_srm(100, 0)


def test_sql_and_python_match_and_exclude_late_orders(seeded):
    root = Path(__file__).resolve().parents[1]
    a = pd.read_csv(seeded / "assignments.csv")
    o = pd.read_csv(seeded / "orders.csv")
    # Append a paid order exactly at day 7: the half-open window must exclude it.
    late = o.iloc[[0]].copy()
    cid = int(late.customer_id.iloc[0])
    late["created_at"] = str(pd.Timestamp(a.loc[a.customer_id == cid, "assigned_at"].iloc[0]) + pd.Timedelta(days=7))
    late["order_total"] = 1e9
    o = pd.concat([o, late], ignore_index=True)
    m = figures.compute_metrics(figures._customer_outcomes(a, o))
    with duckdb.connect() as con:
        con.execute("create table experiment_assignments as select * replace (assigned_at::timestamptz as assigned_at) from a")
        con.execute("create table orders as select * replace (created_at::timestamptz as created_at) from o")
        sql = con.execute((root / "sql/03_per_variant_metrics.sql").read_text(encoding="utf-8")).df().set_index("variant_name")
    assert m["x_c"] == sql.loc["control", "converters"]
    assert m["x_t"] == sql.loc["treatment", "converters"]
    assert m["aov_c"] == pytest.approx(sql.loc["control", "aov"], abs=.01)
    assert m["aov_t"] == pytest.approx(sql.loc["treatment", "aov"], abs=.01)


def test_sample_size_roundtrips():
    # required_sample_per_arm and detectable_mde_abs should be inverses
    n = ab.required_sample_per_arm(baseline=0.038, mde_abs=0.005)
    mde = ab.detectable_mde_abs(baseline=0.038, n_per_arm=n)
    assert abs(mde - 0.005) < 0.0003


def test_draft_baseline_deduplicates_and_respects_as_of():
    """Tiny fixture validates query mechanics; it is not a historical baseline."""
    root = Path(__file__).resolve().parents[1]
    with duckdb.connect() as con:
        con.execute("""create table session_events (
            customer_id integer, event_type varchar, occurred_at timestamptz);
            insert into session_events values
            (1, 'product_view', '2026-05-16 00:00:00+00'),
            (1, 'product_view', '2026-05-20 00:00:00+00'),
            (2, 'product_view', '2026-06-01 00:00:00+00'),
            (3, 'product_view', '2026-06-10 00:00:00+00'),
            (4, 'product_view', '2026-06-15 00:00:00+00'),
            (5, 'product_view', '2026-05-15 23:59:59+00'),
            (6, 'page_view', '2026-06-01 00:00:00+00');
            create table orders (
                customer_id integer, payment_status varchar, created_at timestamptz);
            insert into orders values
            (1, 'paid', '2026-05-17 00:00:00+00'),
            (1, 'paid', '2026-05-21 00:00:00+00'),
            (2, 'failed', '2026-06-02 00:00:00+00'),
            (2, 'paid', '2026-06-15 00:00:00+00'),
            (3, 'paid', '2026-06-09 00:00:00+00');""")
        n, x, rate = con.execute((root / "sql/00_baseline_30d.sql").read_text(encoding="utf-8")).fetchone()
    assert (n, x) == (3, 1)
    assert rate == pytest.approx(1 / 3)
