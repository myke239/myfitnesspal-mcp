---
name: manage-myfitnesspal
description: Log, edit or delete MyFitnessPal food diary entries and manage custom foods, water, measurements, nutrition goals or fasting using the connector's validated write tools.
---

Call `get_myfitnesspal_tool_guide` when tools or routes are unclear. It returns every current tool's description and exact input schema, supported write operations and task routes without account access. For parameter details and examples, read the relevant section of the [tool reference](references/tool-guide.md). Discover names from the connected server; a host may prefix them with its connector namespace.

## Food logging

For an attached photo, use `estimate_food_from_attachment` as described in [estimate-food](../estimate-food/SKILL.md). Resolve dates in the user's timezone and use explicit YYYY-MM-DD. Inspect `get_account_profile` for meal names and units. Case-insensitive unique meal matches are supported, but submit the account's canonical name when known; do not guess a custom meal category.

Use `search_food`, then `get_food_details(food_id)`. Match the actual food, raw/cooked preparation and serving. Use the returned `serving_index`, not the serving's ID or list position. Where the serving has a credible `gram_weight`, servings = edible grams / gram_weight. For example, a returned 100 g serving with gram_weight 100 requires 1.04 servings for 104 g; a returned 1 g serving requires 104 servings. Check consistency of value/unit/gram_weight; some database entries contain invalid mass mappings. If no trustworthy mass conversion exists, resolve another entry or ask for the intended serving rather than fabricate it.

Read `get_myfitnesspal_write_schema(operation="add_food_to_diary")`. Submit `execute_myfitnesspal_write` with calendar_date, food_id, canonical meal_name, servings and serving_index. Read back `get_myfitnesspal_data(resource="diary_entries", calendar_date=...)` and/or `get_food_diary` before claiming saved quantities. Report the actual stored nutrition, distinguishing it from prior estimates.

## Other changes

Read structured records using `get_myfitnesspal_data` to obtain exact IDs before updates/deletes. Get the relevant write schema, perform only the user-requested change and read back. `create_food`, `set_measurement` and `set_nutrition_goals` offer typed SDK contracts; the generic executor also exposes extension contracts. Use the current schemas rather than reconstructing fields from memory.

- Base calorie intake: read `get_myfitnesspal_data(resource="nutrition_goals")`; diary goals may include exercise adjustments. Goal writes replace daily goals and clear per-meal goals; explain this effect when relevant to the requested change.
- `set_water` replaces the day's TOTAL milliliters; it is not an increment. Read existing water before adding a reported drink to the daily total.
- Measurements require actual observations and known units. Never create test measurements. Fasting requires explicitly zoned timestamps and an exact record ID as specified in the schema.
- Saved recipes/meals are readable; exercise/recipe creation and fasting history are not implemented. Do not advertise them as supported writes.

## Outcomes and retries

Use an 8–100 character idempotency key of letters, digits, `_` or `-` per intended change. Reuse the same key and identical parameters for the same retry. A key cannot be reused for a different change.

`failed_before_write` means no mutation request was sent: inspect `stage`, `reason` and `http_status`, correct the cause and retry. Identical requests can retry under the same key; changed parameters need a new key. `unknown_meal_name` requires account meal lookup; `serving_index_not_found` requires fresh food details. `outcome_unknown` means a mutation may have reached MyFitnessPal: inspect the diary/target before any new attempt; do not use a new key to force a retry. `acknowledged` still requires read-back verification. Stop on unresolved errors and describe what is known rather than claim success.

Remote changes require `myfitnesspal:read` and `myfitnesspal:write`. `WRITE_SCOPE_REQUIRED` calls for reconnecting with both scopes. Estimation alone never authorizes logging. User requests such as “log it” authorize the specified entry; avoid redundant confirmation when values and target are already clear.
