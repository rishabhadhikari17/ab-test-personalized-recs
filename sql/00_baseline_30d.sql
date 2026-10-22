-- DRAFT equivalent, pending the actual Section 7.3 query/schema.
-- Assumes session_events(customer_id, event_type, occurred_at) and
-- orders(customer_id, payment_status, created_at).
-- As-of is 2026-06-15 00:00:00 UTC, exclusive: [May 16, June 15).
-- Counts distinct customers, not sessions or joined event/order rows.
-- This is period conversion, not a fully matured 7-day cohort estimate:
-- recent viewers have less follow-up. Confirm Section 7.3 before using for power.
with pdp_viewers as (
    select customer_id, min(occurred_at) as first_product_view
    from session_events
    where event_type = 'product_view'
      and customer_id is not null
      and occurred_at >= TIMESTAMPTZ '2026-05-16 00:00:00+00'
      and occurred_at < TIMESTAMPTZ '2026-06-15 00:00:00+00'
    group by customer_id
), outcomes as (
    select v.customer_id,
           case when exists (
               select 1 from orders o
               where o.customer_id = v.customer_id
                 and o.payment_status = 'paid'
                 and o.created_at >= v.first_product_view
                 and o.created_at < TIMESTAMPTZ '2026-06-15 00:00:00+00'
           ) then 1 else 0 end as converted
    from pdp_viewers v
)
select count(*) as pdp_customers,
       coalesce(sum(converted), 0) as paid_customers,
       sum(converted)::double / nullif(count(*), 0) as baseline_conversion_rate
from outcomes;
