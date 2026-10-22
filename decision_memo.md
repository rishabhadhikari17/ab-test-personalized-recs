# Decision memo: Personalized PDP Recommendations v2

**Experiment 202 | Synthetic Option 2 demonstration**

**Recommendation:** the simulation workflow is ready for review; do not use this
synthetic result to authorize production rollout. The primary conversion result
is inconclusive and guardrail uncertainty includes meaningful harm.

## Validity and conversion
SRM chi-square **0.0387**, p **0.844004** passes for
**25,022 control / 24,978 treatment** assignments. All assigned customers
are included; only paid orders in their half-open seven-day window count.

Observed conversion lift: **+6.30% relative / +0.239pp**;
Z = **1.378**, two-sided p = **0.1683**.
95% absolute CI: **[-0.101, +0.579]pp**;
approximate relative CI: **[-2.66%, +15.26%]**.
The primary result is not statistically significant at alpha 0.05.

The configuration implies 12.82% expected relative lift, but this fixed random
sample realizes 6.30%. The seed was retained, not selected to produce
significance. A non-significant result does not prove no benefit.

| Metric | Control | Treatment |
|---|---:|---:|
| Assigned customers | 25,022 | 24,978 |
| Paid converters (7 days) | 949 | 1,007 |
| Conversion | 3.793% | 4.032% |
| Mean order value (INR) | 2,465.18 | 2,595.93 |
| Revenue/customer before refunds (INR) | 93.50 | 104.66 |
| Refund rate among converters | 1.159% | 2.383% |
| Repeat rate among converters | 22.76% | 19.17% |
| Bounce | 25.150% | 26.523% |
| PDP p95 latency (ms) | 1477.5 | 1558.0 |

## Guardrails and economics
Refunds increase **+1.224pp**; 95% difference CI
**[+0.062, +2.387]pp**. The point estimate
exceeds the proposed +0.5pp limit, even though the configured expected increase
is only +0.3pp. Sparse refund events produce substantial uncertainty.

Bounce difference is **+1.373pp**, with 95% CI
**[+0.606, +2.141]pp** versus a proposed +1.0pp limit.
P95 latency changes by **+80.4ms** versus +100ms;
no latency uncertainty interval is estimated here. Repeat purchase difference is
**-3.595pp**, 95% CI
**[-7.204, +0.014]pp**.
These metrics are simulated mature flags/customer summaries, not real telemetry.

Revenue/customer before refunds rises **+11.94%** in this realization.
AOV is higher by design, so conversion lift alone does not represent revenue lift.
No uncertainty interval for revenue lift or claim of increased profit is made.
The inherited $200k cost / $5M revenue scenario implies a 4% revenue coverage
hurdle before margins and refund costs; those dollar assumptions cannot be
subtracted directly from synthetic INR orders.

## Next steps
The synthetic task is complete without real v2 data. For a future production
experiment, lock a prospective plan, instrument customer-level exposure and mature
outcomes, verify power using a suitable baseline, and assess net contribution.
Keep category/device/country cuts exploratory (nine comparisons, Bonferroni
alpha 0.05/9). Although category effects are imposed in the generator, noisy
subgroup estimates do not establish real-world heterogeneity or justify a
category-specific rollout.
