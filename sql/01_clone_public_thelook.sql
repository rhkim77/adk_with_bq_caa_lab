-- =============================================================================
-- [Step 1] Clone 7 Core Tables from `bigquery-public-data.thelook_ecommerce`
-- Target Dataset: `__PROJECT_ID__.__DATASET_ID__` (Default: `thelook_ecommerce_agent`, Region: `US`)
-- Execution Time: ~10-15 seconds via BigQuery in-region CTAS
-- =============================================================================

CREATE OR REPLACE TABLE `__PROJECT_ID__.__DATASET_ID__.distribution_centers` AS
SELECT * FROM `bigquery-public-data.thelook_ecommerce.distribution_centers`;

CREATE OR REPLACE TABLE `__PROJECT_ID__.__DATASET_ID__.products` AS
SELECT * FROM `bigquery-public-data.thelook_ecommerce.products`;

CREATE OR REPLACE TABLE `__PROJECT_ID__.__DATASET_ID__.users` AS
SELECT * FROM `bigquery-public-data.thelook_ecommerce.users`;

CREATE OR REPLACE TABLE `__PROJECT_ID__.__DATASET_ID__.orders` AS
SELECT * FROM `bigquery-public-data.thelook_ecommerce.orders`;

CREATE OR REPLACE TABLE `__PROJECT_ID__.__DATASET_ID__.order_items` AS
SELECT * FROM `bigquery-public-data.thelook_ecommerce.order_items`;

CREATE OR REPLACE TABLE `__PROJECT_ID__.__DATASET_ID__.inventory_items` AS
SELECT * FROM `bigquery-public-data.thelook_ecommerce.inventory_items`;

CREATE OR REPLACE TABLE `__PROJECT_ID__.__DATASET_ID__.events` AS
SELECT * FROM `bigquery-public-data.thelook_ecommerce.events`;
