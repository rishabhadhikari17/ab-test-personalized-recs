# Test plan: Personalized PDP Recommendations v2

Experiment **202**, Option 2. This records the simulation design; it is not a
claim of prospective registration of a real experiment. All outcomes are synthetic.
The reference repository provides the structure, not real v2 observations.

## Hypothesis
If the PDP displays personalized recommendations, then seven-day customer paid
conversion will rise because relevant alternatives and complementary products
improve discovery. Cross-sell may raise AOV; impulse buying may raise refunds.

## Locked simulation inputs
| Category | Population share | Control CR | Relative lift | Treatment CR |
|---|---:|---:|---:|---:|
| Apparel / beauty | 50% | 4.2% | 15% | 4.830% |
| Electronics | 25% | 3.2% | 8% | 3.456% |
| Home | 25% | 3.6% | 12% | 4.032% |

Weighted expected rates are **3.800% control** and **4.287% treatment**:
**+0.487 percentage points / +12.82% relative**. The aggregate lift weights
category effects by baseline conversions, not just by population shares.
Generate **50,000 customers**, with fixed seed **20260617** retained from the
existing skeleton. Do not select a seed to obtain significance or an expected lift.

Refund probability among paid converters is 1.2% control and 1.5% treatment.
AOV is the arithmetic mean of a lognormal distribution: INR 2,500 and INR 2,620,
with log-scale sigma 0.45. Observed averages and refunds fluctuate.
Additional inherited scenarios: bounce 25% / 26%, repeat purchase 22% / 20%,
failed-payment probability 1.8% in both arms, and treatment latency +80ms.
Refund/repeat flags represent simulated mature outcomes, not actual follow-up.

## Assignment and measurement
- SHA-256 of `experiment_id:customer_id`, modulo 100 below 50 assigns control.
- Customer is the randomization unit; repeat visits retain the assignment.
- Enrollment at the first eligible PDP view, 50/50 allocation, 100% exposure.
- Synthetic timestamps: June 16 to July 14, 2026, exclusive end, UTC.
- Primary metric: at least one paid order in `[assigned_at, assigned_at + 7 days)`.
  ITT denominator: all assigned customers. One paid order per synthetic converter.
- No outcome-based early stopping. A real experiment needs mature seven-day
  follow-up; a real repeat-purchase metric needs 30 days after purchase.

## Power context
With two-sided alpha 0.05 and 80% power, the inherited approximate sample-size
formula requires **25,678 per arm** for a 0.487pp effect at 3.8% baseline.
The requested 50,000 total is slightly below that approximation. Keep the
specified simulation size and report uncertainty; do not force a significant result.
Historical v2 data is not required to run or complete this synthetic exercise.

## Analysis and decision
1. Validate unique customer assignments and both arms. Stop if SRM p < 0.001.
2. Use a two-sided pooled two-proportion Z-test and unpooled absolute 95% CI.
   The relative interval rescales the absolute interval by observed control CR.
3. Report conversion, revenue/customer before refunds, AOV, refunds, repeats,
   failed payments, bounce, and p95 latency.
4. Category/device/country cuts are exploratory: nine tests, Bonferroni alpha
   0.05/9. Separate subgroup significance does not establish an interaction.

Proposed real-test guardrails: refund increase <0.5pp, bounce increase <1.0pp,
and p95 latency increase <100ms. Assess uncertainty, not just point estimates.
A production decision needs positive primary evidence, acceptable guardrails,
and incremental contribution covering recurring costs. This simulation alone
cannot justify production rollout.

Inherited economic scenario: $200k annual cost / $5M annual PDP revenue = a 4%
revenue coverage hurdle, before margin and incremental refund costs. These are
scenario assumptions separate from synthetic INR order values, not a measured forecast.
