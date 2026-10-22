-- ============================================================================
-- 02 — Exposure: ITT vs ATT
-- How many ASSIGNED customers actually saw the PDP (were exposed)? We gate the
-- decision on ITT (intent-to-treat: all assigned). An exposed-only comparison
-- does not identify a causal ATT without additional assumptions.
-- Sanity check: exposure_rate = 1.0: enrollment is at the eligible PDP view (differential
--               exposure would itself be a red flag).
-- Postgres port: `exposed` here stands in for "has a product_view in the window";
--   real query LEFT JOINs ecom.session_events (event_type='product_view') on
--   customer_id AND occurred_at BETWEEN assigned_at AND end_date.
-- ============================================================================
select
    variant_name
  , count(*)                                                    as assigned
  , count(*) filter (where exposed)                             as actually_exposed
  , round(count(*) filter (where exposed)::double
          / nullif(count(*), 0), 4)                             as exposure_rate
from experiment_assignments
where experiment_id = 202
group by variant_name
order by variant_name;
