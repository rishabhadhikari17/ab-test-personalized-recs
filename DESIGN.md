# Simulation design

The project is an independent Option 2 adaptation of the
[reference skeleton](https://github.com/anujhsrsaini/ab-test-pdp-strikethrough).
All assignments, orders, and guardrails are simulated locally. No production
credentials or historical v2 observations are needed.

`seed_experiment.py` controls experiment 202, 50,000 customers, and the category
mix. Each customer's category is sampled before outcomes; SHA-256 assigns the
arm independently of category. Conversion is Bernoulli(category control CR),
multiplied by `1 + category relative lift` for treatment. The expected aggregate
rates are 3.800% and 4.287%, but realized rates and category rankings contain noise.

The seed is fixed at 20260617. It is not searched to obtain significance.
`data/seed_config.json` records the configuration alongside portable CSVs.
DuckDB tables use the same experiment ID/name as the configuration, and all
experiment SQL filters on 202. CSVs and analysis outputs are reproducible.

AOV settings control arithmetic means by subtracting sigma squared / 2 from
log(mean) before drawing lognormal baskets. Refunds are Bernoulli draws among
paid converters. The model generates one paid order per converter and separate
failed-payment attempts. Refunds/repeats are flags for simulated mature outcomes.
Bounce and latency are illustrative customer summaries, not real session telemetry.

SQL and Python use the same half-open seven-day attribution window and all
assigned customers in the denominator. SRM gates outcome analysis at p < 0.001.
Tests validate reproducibility, category conversion distributions, AOV means,
metadata consistency, attribution, SQL/Python agreement, and statistical math.
They do not require a statistically significant simulated result.

See [the test plan](PRE_REGISTRATION.md) for all input assumptions and
[the decision memo](decision_memo.md) for observed results and limitations.
