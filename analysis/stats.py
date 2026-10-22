"""Reusable A/B statistics — shared by analysis.ipynb and the tests.

Kept deliberately small and dependency-light (numpy + scipy) so each function is
auditable. The point of factoring these out: the notebook reads like a narrative,
and the tests pin the math so a reviewer can trust the narrative's numbers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


@dataclass
class LiftResult:
    p_control: float
    p_treatment: float
    abs_lift: float
    rel_lift: float
    abs_ci: tuple[float, float]
    rel_ci: tuple[float, float]
    z: float
    p_value: float


def two_proportion_ztest(x_c: int, n_c: int, x_t: int, n_t: int) -> tuple[float, float]:
    """Pooled two-proportion z-test (the pooled SE is the correct one under H0)."""
    p_pool = (x_c + x_t) / (n_c + n_t)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n_c + 1 / n_t))
    z = (x_t / n_t - x_c / n_c) / se
    p = 2 * stats.norm.sf(abs(z))   # two-tailed; stable even for extreme Z
    return z, p


def lift_with_ci(x_c: int, n_c: int, x_t: int, n_t: int, z_crit: float = 1.96) -> LiftResult:
    """Absolute + relative lift with 95% CIs (unpooled SE — correct for the CI)."""
    p_c, p_t = x_c / n_c, x_t / n_t
    abs_lift = p_t - p_c
    rel_lift = abs_lift / p_c
    se = math.sqrt(p_c * (1 - p_c) / n_c + p_t * (1 - p_t) / n_t)
    abs_ci = (abs_lift - z_crit * se, abs_lift + z_crit * se)
    rel_ci = (abs_ci[0] / p_c, abs_ci[1] / p_c)
    z, pval = two_proportion_ztest(x_c, n_c, x_t, n_t)
    return LiftResult(p_c, p_t, abs_lift, rel_lift, abs_ci, rel_ci, z, pval)


def chisq_srm(n_control: int, n_treatment: int, expected_split: float = 0.5) -> tuple[float, float]:
    """Chi-square SRM test. p < 0.001 => sample-ratio mismatch, stop the analysis."""
    total = n_control + n_treatment
    expected = [total * expected_split, total * (1 - expected_split)]
    chi2, p = stats.chisquare([n_control, n_treatment], expected)
    return chi2, p


def require_valid_srm(n_control: int, n_treatment: int,
                      threshold: float = 0.001) -> tuple[float, float]:
    """Fail closed before computing outcomes if either arm is missing or SRM fails."""
    if n_control <= 0 or n_treatment <= 0:
        raise ValueError("SRM requires both control and treatment customers.")
    chi2, p = chisq_srm(n_control, n_treatment)
    if p < threshold:
        raise ValueError(f"SRM failed: chi-square={chi2:.4f}, p={p:.6g}; stop analysis.")
    return chi2, p


def bonferroni_alpha(alpha: float, n_tests: int) -> float:
    return alpha / n_tests


def required_sample_per_arm(baseline: float, mde_abs: float, alpha: float = 0.05,
                            power: float = 0.80) -> int:
    """Two-proportion sample size per arm (standard closed form)."""
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    p1, p2 = baseline, baseline + mde_abs
    n = (z_a + z_b) ** 2 * (p1 * (1 - p1) + p2 * (1 - p2)) / (p2 - p1) ** 2
    return math.ceil(n)


def detectable_mde_abs(baseline: float, n_per_arm: int, alpha: float = 0.05,
                       power: float = 0.80) -> float:
    """Inverse of the above: smallest absolute effect detectable at given n/arm."""
    z_a = stats.norm.ppf(1 - alpha / 2)
    z_b = stats.norm.ppf(power)
    p = baseline
    return (z_a + z_b) * math.sqrt(2 * p * (1 - p) / n_per_arm)
