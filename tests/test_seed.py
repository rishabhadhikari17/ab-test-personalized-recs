"""Validate the simulation contract, distributions, and reproducibility."""
import hashlib
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import seed_experiment as seed


def test_option2_generation_and_reproducibility(tmp_path):
    seed.main(output_dir=tmp_path)
    a = pd.read_csv(tmp_path / "assignments.csv")
    o = pd.read_csv(tmp_path / "orders.csv")
    config = json.loads((tmp_path / "seed_config.json").read_text())
    assert len(a) == 50_000
    assert a.customer_id.is_unique
    assert set(a.experiment_id) == {202}
    assert config["experiment_name"] == "Personalized PDP Recommendations v2"
    assert config["control_probability"] == pytest.approx(.038)
    assert config["treatment_probability"] == pytest.approx(.04287)
    assert config["refund_rate"] == {"control": .012, "treatment": .015}
    assert config["aov_mean_inr"] == {"control": 2500., "treatment": 2620.}
    assert o.order_id.is_unique
    assert set(o.customer_id) <= set(a.customer_id)
    joined = o.merge(a, on="customer_id", validate="many_to_one")
    delta = pd.to_datetime(joined.created_at) - pd.to_datetime(joined.assigned_at)
    assert (delta >= pd.Timedelta(0)).all()
    assert (delta < pd.Timedelta(days=7)).all()
    paid = joined[joined.payment_status == "paid"]
    assert paid.customer_id.is_unique
    assert (paid.order_total > 0).all()
    for name, (share, p, lift) in seed.SEGMENTS.items():
        assert (a.category_segment == name).mean() == pytest.approx(share, abs=.01)
        for variant in ["control", "treatment"]:
            n = len(a[(a.category_segment == name) & (a.variant_name == variant)])
            x = len(paid[(paid.category_segment == name) & (paid.variant_name == variant)])
            expected = p * (1 + lift if variant == "treatment" else 1)
            assert abs(x / n - expected) < 5 * np.sqrt(expected * (1 - expected) / n)
    for variant in ["control", "treatment"]:
        baskets = paid.loc[paid.variant_name == variant, "order_total"]
        assert abs(baskets.mean() - seed.AOV[variant]) < 5 * baskets.std() / np.sqrt(len(baskets))
    with duckdb.connect(str(tmp_path / "experiment.duckdb"), read_only=True) as con:
        assert con.execute("select experiment_id, name from experiments").fetchone() == (
            202, seed.EXPERIMENT_NAME)
        assert con.execute("select distinct experiment_id from experiment_variants").fetchall() == [(202,)]
        assert con.execute("select count(*) from experiment_assignments").fetchone()[0] == len(a)
        assert con.execute("select count(*) from orders").fetchone()[0] == len(o)
    # Compare portable artifacts; DuckDB's physical page bytes need not be identical.
    files = ["assignments.csv", "orders.csv", "seed_config.json"]
    before = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files}
    seed.main(output_dir=tmp_path)
    assert before == {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files}
