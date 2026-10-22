-- ============================================================================
-- 04 — Segmented conversion (category_segment × variant), plus device & country
-- Feeds the heterogeneity analysis. Each segment is another significance test, so
-- analysis.ipynb applies a Bonferroni correction before acting on any single cut.
-- Sanity check: per-segment arm sizes are comparable (a lopsided arm inside a
--               segment hints at assignment leaking into the segmenting variable).
-- Postgres port: category_segment comes from joining the customer's modal product
--   category (order_items -> product_variants -> products -> categories); device
--   from sessions->devices; country from customers (cleaned for the null variants).
-- ============================================================================
with assigned as (
    select variant_name, customer_id, category_segment, device, country, assigned_at
    from experiment_assignments
    where experiment_id = 202
)

, outcomes as (
    select
        a.variant_name
      , a.category_segment
      , a.device
      , a.country
      , a.customer_id
      , max(case when o.payment_status = 'paid' then 1 else 0 end) as converted
    from assigned a
    left join orders o on o.customer_id = a.customer_id
        and o.created_at >= a.assigned_at
        and o.created_at < a.assigned_at + interval '7 days'
    group by 1, 2, 3, 4, 5
)

select
    'category' as cut, category_segment as segment, variant_name
  , count(*) as customers, sum(converted) as converters
  , round(avg(converted), 4) as conversion_rate
from outcomes group by 2, 3
union all
select 'device', device, variant_name, count(*), sum(converted), round(avg(converted), 4)
from outcomes group by 2, 3
union all
select 'country', country, variant_name, count(*), sum(converted), round(avg(converted), 4)
from outcomes group by 2, 3
order by cut, segment, variant_name;
