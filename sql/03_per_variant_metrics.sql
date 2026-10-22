-- ============================================================================
-- 03 — Per-variant metrics (the readout table)
-- Primary metric (customer-level conversion) + guardrails: refund rate, 30-day
-- repeat rate, AOV, payment-failure rate. One row per customer first, then roll up
-- by arm — so the grain is the randomization unit (customer), not the order.
-- Sanity check: conversion_rate in [0,1]; converters <= customers; arms ~equal size.
-- Postgres port: replace `orders` with ecom.orders (payment_status), refund via
--   the ecom.order_refunds view; repeat_30d via a follow-on orders self-join.
-- ============================================================================
with assigned as (
    select
        variant_name
      , customer_id
      , assigned_at
    from experiment_assignments
    where experiment_id = 202
)

, customer_outcomes as (
    select
        a.variant_name
      , a.customer_id
      , max(case when o.payment_status = 'paid' then 1 else 0 end)                       as converted
      , coalesce(sum(case when o.payment_status = 'paid' then o.order_total end), 0)      as revenue
      , max(case when o.payment_status = 'paid' and o.refunded   then 1 else 0 end)       as refunded
      , max(case when o.payment_status = 'paid' and o.repeat_30d then 1 else 0 end)       as repeated
      , max(case when o.payment_status = 'failed' then 1 else 0 end)                      as had_pmt_failure
    from assigned a
    left join orders o on o.customer_id = a.customer_id
        and o.created_at >= a.assigned_at
        and o.created_at < a.assigned_at + interval '7 days'
    group by a.variant_name, a.customer_id
)

select
    variant_name
  , count(*)                                                         as customers
  , sum(converted)                                                   as converters
  , round(avg(converted), 4)                                         as conversion_rate
  , round(sum(revenue), 0)                                           as revenue
  , round(sum(revenue) / nullif(count(*), 0), 2)                     as revenue_per_customer
  , round(sum(revenue) / nullif(sum(converted), 0), 2)               as aov
  , round(sum(refunded)::double / nullif(sum(converted), 0), 4)      as refund_rate
  , round(sum(repeated)::double / nullif(sum(converted), 0), 4)      as repeat_30d_rate
  , round(sum(had_pmt_failure)::double / nullif(count(*), 0), 4)     as pmt_failure_rate
from customer_outcomes
group by variant_name
order by variant_name;
