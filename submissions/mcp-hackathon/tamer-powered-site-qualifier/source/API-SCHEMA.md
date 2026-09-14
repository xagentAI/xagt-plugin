# API schema

## `POST /v1/qualify`

Request fields are optional so early qualification can explicitly identify missing information. Unknown JSON fields are rejected with HTTP 422 and numeric fields cannot be negative.

Fields include `country_state`, `available_mw`, `power_ready_now`, `energization_rfs_date`, `voltage`, `utility_interconnection_status`, `grid_or_gas_to_power`, `power_price_usd_kwh`, `land_size_acres`, `lease_sale_jv`, `fiber_availability`, `water_availability`, `gas_availability`, `permitting_status`, `expansion_capacity_mw`, and `intended_use`.

Response fields are `bitcoin_mining_readiness`, `ai_data_center_readiness`, `key_positives`, `missing_information`, `major_blockers`, `recommended_next_questions`, `classification`, `intended_use`, and `method`.

Scores are weighted heuristics, not financial, legal, utility, engineering, or investment advice.
