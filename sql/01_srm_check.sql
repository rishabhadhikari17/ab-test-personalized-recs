-- ============================================================================
-- 01 — Sample Ratio Mismatch (SRM) check
-- Run this BEFORE any conversion analysis. If the 50/50 split didn't hold,
-- randomization is broken and every downstream number is suspect — stop and fix.
-- Sanity check: observed_share for each arm ≈ 0.50 (chi-square p >= 0.001 in analysis.ipynb)
-- Postgres port: identical against a warehouse experiment_assignments table;
--                keep the WHERE experiment_id filter.
-- ============================================================================
with counts as (
    select
        variant_name
      , count(*) as n
    from experiment_assignments
    where experiment_id = 202
    group by variant_name
)

select
    variant_name
  , n
  , sum(n) over ()                              as total
  , round(n::double / sum(n) over (), 4)        as observed_share
  , 0.50                                        as expected_share
from counts
order by variant_name;
