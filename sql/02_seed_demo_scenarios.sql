-- =============================================================================
-- [Step 2] Seed Golden Demo Scenario Data into `__PROJECT_ID__.__DATASET_ID__`
-- Purpose:
--   1. Ensure relative time queries ("지난 달", "최근 30일", "최근 90일 휴면") always
--      have fresh, deterministic records anchored to `CURRENT_TIMESTAMP()`.
--   2. Inject high-signal patterns for each of the 3 Domain-Scoped BQ CAA Sub-Agents:
--      - Domain 1 (Customer & Marketing): High-LTV VIP customers from `Search`/`Email`
--        and high Cart Abandonment sessions in `Display`.
--      - Domain 2 (Product & Profitability): High-margin (>50%) `Women` `Outerwear & Coats`
--        products with a clear return (`Returned`) spike for executive anomaly detection.
--      - Domain 3 (Supply Chain & Logistics): Delivery lead-time bottleneck (6-7 days)
--        and unsold inventory holding cost at `Chicago IL` (DC #2) & `Memphis TN` (DC #1).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Idempotency Clean-up (Remove previously seeded demo rows with ID >= 9900000)
-- -----------------------------------------------------------------------------
DELETE FROM `__PROJECT_ID__.__DATASET_ID__.users` WHERE id >= 9900000;
DELETE FROM `__PROJECT_ID__.__DATASET_ID__.products` WHERE id >= 9900000;
DELETE FROM `__PROJECT_ID__.__DATASET_ID__.orders` WHERE order_id >= 9900000;
DELETE FROM `__PROJECT_ID__.__DATASET_ID__.order_items` WHERE id >= 9900000;
DELETE FROM `__PROJECT_ID__.__DATASET_ID__.inventory_items` WHERE id >= 9900000;
DELETE FROM `__PROJECT_ID__.__DATASET_ID__.events` WHERE id >= 9900000;

-- -----------------------------------------------------------------------------
-- 2. [Domain 1: Customer & Marketing] Seed Recent VIP Customers & New Signups
-- -----------------------------------------------------------------------------
INSERT INTO `__PROJECT_ID__.__DATASET_ID__.users` (
  id, first_name, last_name, email, age, gender, state, street_address,
  postal_code, city, country, latitude, longitude, traffic_source, created_at
)
SELECT
  9900000 + seq AS id,
  CONCAT('DemoVIP_', CAST(seq AS STRING)) AS first_name,
  'Customer' AS last_name,
  CONCAT('demovip_', CAST(seq AS STRING), '@example.com') AS email,
  30 + MOD(seq, 25) AS age,
  CASE WHEN MOD(seq, 2) = 0 THEN 'F' ELSE 'M' END AS gender,
  'California' AS state,
  '100 Market St' AS street_address,
  '94105' AS postal_code,
  'San Francisco' AS city,
  'United States' AS country,
  37.7897 AS latitude,
  -122.4014 AS longitude,
  CASE
    WHEN MOD(seq, 5) IN (0, 1) THEN 'Search'
    WHEN MOD(seq, 5) = 2 THEN 'Email'
    WHEN MOD(seq, 5) = 3 THEN 'Organic'
    ELSE 'Display'
  END AS traffic_source,
  TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL MOD(seq, 25) DAY) AS created_at
FROM UNNEST(GENERATE_ARRAY(1, 60)) AS seq;

-- -----------------------------------------------------------------------------
-- 3. [Domain 2: Product & Profitability] Seed High-Margin (>52%) Women Outerwear
-- -----------------------------------------------------------------------------
INSERT INTO `__PROJECT_ID__.__DATASET_ID__.products` (
  id, cost, category, name, brand, retail_price, department, sku, distribution_center_id
)
SELECT
  9900000 + seq AS id,
  85.0 AS cost,
  'Outerwear & Coats' AS category,
  CONCAT('Signature Cashmere Trench Coat #', CAST(seq AS STRING)) AS name,
  CASE WHEN MOD(seq, 2) = 0 THEN 'TheLook Atelier' ELSE 'Nordic Luxe' END AS brand,
  195.0 AS retail_price,  -- Margin Rate = (195 - 85) / 195 * 100 = 56.41%
  'Women' AS department,
  CONCAT('SKU-DEMO-COAT-', CAST(seq AS STRING)) AS sku,
  CASE WHEN MOD(seq, 2) = 0 THEN 2 ELSE 1 END AS distribution_center_id
FROM UNNEST(GENERATE_ARRAY(1, 20)) AS seq;

-- -----------------------------------------------------------------------------
-- 4. [Domain 1, 2, 3] Seed Recent Orders & Order Items (Last 30 Days)
--    - Creates VIP spend (> $500) for seeded users
--    - Creates Return/Cancel spike on 'TheLook Atelier' high-margin coats
--    - Creates 6-day delivery lead-time bottleneck on DC #2 (Chicago IL)
-- -----------------------------------------------------------------------------
INSERT INTO `__PROJECT_ID__.__DATASET_ID__.orders` (
  order_id, user_id, status, gender, created_at, returned_at, shipped_at, delivered_at, num_of_item
)
SELECT
  9900000 + seq AS order_id,
  9900000 + MOD(seq, 60) + 1 AS user_id,
  CASE
    WHEN MOD(seq, 4) = 0 THEN 'Returned'
    WHEN MOD(seq, 10) = 1 THEN 'Cancelled'
    ELSE 'Complete'
  END AS status,
  CASE WHEN MOD(seq, 2) = 0 THEN 'F' ELSE 'M' END AS gender,
  TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) + 5) DAY) AS created_at,
  CASE
    WHEN MOD(seq, 4) = 0 THEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
    ELSE NULL
  END AS returned_at,
  CASE
    WHEN MOD(seq, 10) = 1 THEN NULL
    ELSE TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) + 4) DAY)
  END AS shipped_at,
  CASE
    WHEN MOD(seq, 10) = 1 THEN NULL
    -- Inject 6-day delivery lead time for even seq (linked to DC #2) vs 2-day for odd
    WHEN MOD(seq, 2) = 0 THEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) - 2) DAY)
    ELSE TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) + 2) DAY)
  END AS delivered_at,
  3 AS num_of_item
FROM UNNEST(GENERATE_ARRAY(1, 180)) AS seq;

INSERT INTO `__PROJECT_ID__.__DATASET_ID__.order_items` (
  id, order_id, user_id, product_id, inventory_item_id, status,
  created_at, shipped_at, delivered_at, returned_at, sale_price
)
SELECT
  9900000 + seq AS id,
  9900000 + seq AS order_id,
  9900000 + MOD(seq, 60) + 1 AS user_id,
  9900000 + MOD(seq, 20) + 1 AS product_id,
  9900000 + seq AS inventory_item_id,
  CASE
    WHEN MOD(seq, 4) = 0 THEN 'Returned'
    WHEN MOD(seq, 10) = 1 THEN 'Cancelled'
    ELSE 'Complete'
  END AS status,
  TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) + 5) DAY) AS created_at,
  CASE
    WHEN MOD(seq, 10) = 1 THEN NULL
    ELSE TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) + 4) DAY)
  END AS shipped_at,
  CASE
    WHEN MOD(seq, 10) = 1 THEN NULL
    WHEN MOD(seq, 2) = 0 THEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) - 2) DAY)
    ELSE TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (MOD(seq, 24) + 2) DAY)
  END AS delivered_at,
  CASE
    WHEN MOD(seq, 4) = 0 THEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
    ELSE NULL
  END AS returned_at,
  245.0 AS sale_price  -- 3 orders * $245 = $735 (> $500 VIP threshold)
FROM UNNEST(GENERATE_ARRAY(1, 180)) AS seq;

-- -----------------------------------------------------------------------------
-- 5. [Domain 3: Supply Chain & Logistics] Seed Unsold Inventory (`sold_at IS NULL`)
-- -----------------------------------------------------------------------------
INSERT INTO `__PROJECT_ID__.__DATASET_ID__.inventory_items` (
  id, product_id, created_at, sold_at, cost, product_category, product_name,
  product_brand, product_retail_price, product_department, product_sku,
  product_distribution_center_id
)
SELECT
  9900000 + seq AS id,
  9900000 + MOD(seq, 20) + 1 AS product_id,
  TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL (30 + MOD(seq, 60)) DAY) AS created_at,
  CASE
    WHEN seq <= 180 THEN TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL MOD(seq, 20) DAY)
    ELSE NULL  -- seq 181..400 remain unsold (`sold_at IS NULL`)
  END AS sold_at,
  85.0 AS cost,
  'Outerwear & Coats' AS product_category,
  CONCAT('Signature Cashmere Trench Coat #', CAST(MOD(seq, 20) + 1 AS STRING)) AS product_name,
  CASE WHEN MOD(seq, 2) = 0 THEN 'TheLook Atelier' ELSE 'Nordic Luxe' END AS product_brand,
  195.0 AS product_retail_price,
  'Women' AS product_department,
  CONCAT('SKU-DEMO-COAT-', CAST(MOD(seq, 20) + 1 AS STRING)) AS product_sku,
  CASE WHEN MOD(seq, 2) = 0 THEN 2 ELSE 1 END AS product_distribution_center_id
FROM UNNEST(GENERATE_ARRAY(1, 400)) AS seq;

-- -----------------------------------------------------------------------------
-- 6. [Domain 1: Marketing Funnel] Seed Cart Abandonment Sessions in `events`
-- -----------------------------------------------------------------------------
INSERT INTO `__PROJECT_ID__.__DATASET_ID__.events` (
  id, user_id, sequence_number, session_id, created_at, ip_address,
  city, state, postal_code, browser, traffic_source, uri, event_type
)
SELECT
  9900000 + seq AS id,
  9900000 + MOD(seq, 60) + 1 AS user_id,
  1 AS sequence_number,
  CONCAT('demo-cart-session-', CAST(seq AS STRING)) AS session_id,
  TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL MOD(seq, 14) DAY) AS created_at,
  '192.0.2.10' AS ip_address,
  'San Francisco' AS city,
  'California' AS state,
  '94105' AS postal_code,
  'Chrome' AS browser,
  CASE
    WHEN MOD(seq, 3) = 0 THEN 'Display'
    WHEN MOD(seq, 3) = 1 THEN 'Social'
    ELSE 'Search'
  END AS traffic_source,
  '/cart' AS uri,
  'cart' AS event_type
FROM UNNEST(GENERATE_ARRAY(1, 120)) AS seq;
