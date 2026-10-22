# SDK coverage: MyFitnessPal 2.1.2

Connector version: 0.5.0. Last read-only account checks: October 15, 2026.
The original SDK validation passed 63 tests, lint and packaging. Current tool contracts and estimator extensions are documented in the agent guide.
The installed SDK source is the contract. Tests detect public-method or
set_new_food/set_new_goal signature drift. Twelve operation contracts are
implemented; SDK properties and serialization helpers are projected into outputs.

| SDK operation | Tool | Backend | Live evidence |
| --- | --- | --- | --- |
| get_date | get_food_diary | SDK | Returned four meals, no entries, notes available; empty intake is not established |
| get_measurements | get_measurements | SDK | Returned one dated observation |
| get_report | get_report | SDK | Returned seven dated observations |
| get_food_search_results | search_food | SDK | Returned a public food match |
| get_food_item_details | get_food_details | Current API equivalent | Individual-food endpoint returned nine servings, confirmation count and version |
| get_recipes | get_recipes | SDK | List request succeeded empty; completeness cannot be verified |
| get_recipe | get_recipe | SDK | Not live verified: no recipe ID returned by account list |
| get_meals | get_saved_meals | SDK | List request succeeded empty; completeness cannot be verified |
| get_meal | get_saved_meal | SDK | Not live verified: no saved-meal ID returned by account list |
| set_measurements | set_measurement | Current web adapter | Contract tested; no live mutation performed |
| set_new_food | create_food | Current web adapter | All SDK inputs tested; live serving/container persistence unverified |
| set_new_goal | set_nutrition_goals | Current web adapter and SDK calculations | Six energy/macro combinations compared with real SDK against fake HTTP; no live mutation performed |

## Parameters and behavioral differences

- **Dates:** SDK year/month/day arguments map to YYYY-MM-DD. Omitted dates use
  MFP_TIMEZONE (default America/Los_Angeles), rather than the host's implicit date.
  Explicit date fields are recommended. Report/measurement reversed bounds swap;
  ranges cap at 366 inclusive days. These bounds intentionally limit requests.
- **Reports:** Category and name remain selectable, with URL metacharacters
  rejected. The SDK reconstructs dates from the host date. Responses warn about
  host/user date discrepancies and reports older than 80 days. Units are not guessed.
- **Diaries:** Meals include totals, full nutrient dictionaries and parsed quantity,
  unit and short_name. Notes retain the SDK dictionary. Water and exercise have
  dedicated tools. Alternate diaries obey upstream privacy; owner notes are not
  attached to another user's diary. Parsed portions may be unavailable.
- **Foods:** Details preserve all nutrient fields, energy, brand, verification,
  confirmation count, serving IDs/indexes/value/unit/multiplier. The collection
  endpoint omits details; the adapter uses the same individual endpoint as the SDK.
- **Recipes/meals:** List tools return a cursor and up to 100 records. Detail tools
  retain the entire SDK recipe dictionary. Saved meal titles are resolved from the
  account. Underlying SDK pagination is bounded by a per-operation time budget.
- **Measurements:** Value is required, even though the SDK signature defaults it
  to None and rejects it later. Weight defaults from the account's unit setting.
  Other measurement types require an explicit unit because no reliable unit
  inference is implemented. Numeric SDK history does not retain units; structured
  account records remain accessible with get_myfitnesspal_data(measurements).
- **Food creation:** All SDK parameters are accepted, including vitamin A/C,
  calcium, iron, optional zero-valued nutrients, serving_size, servingspercontainer,
  and sharepublic. The adapter retains serving_size as a label and represents a
  container with its serving multiplier. This mapping still requires live UI
  comparison. US total-carbohydrate semantics are used. Private is the default.
- **Goals:** Energy-only mode scales previous macros. Absolute grams raise energy
  if their calculated energy is higher. Percentage mode uses SDK conversion and
  rounding. Calories, kilojoules and account units are supported. All daily goals
  are replaced and meal goals cleared, matching the SDK's implementation.
  Mixed/incomplete macro sets and percentages not summing to 100 are rejected;
  the SDK otherwise silently prioritizes or ignores some of these inputs.
  Premium/account rules may further round submitted values; read back actual goals.
- **Identity:** get_account_profile returns ID, username, units, meal names and
  tracked nutrients. Access tokens, cookies, diary passcodes and raw session
  objects are not exposed. Authentication remains local browser-session based.

## Authorization and release checks

All tools are discoverable by default. Both OAuth scopes are offered for new
registrations, but read-only grants cannot invoke any of the four write entry
points. All write entry points share validation, serialization and the encrypted
durable idempotency ledger. Unknown outcomes are not retried automatically.
Existing tools and their dispatcher contracts remain supported.

The coverage inventory distinguishes implementation from live evidence. Completing
live validation requires real intended changes with exact values, dates and units,
followed by read-back/UI comparison. Missing recipe/meal IDs and mobile interaction
remain verification gaps. No fake account data was inserted to fill those gaps.

Connector extensions (diary CRUD, water, custom-food update/delete, fasting, and
additional raw reads) remain separate from the twelve SDK operation contracts.

Image estimation and tool discovery are connector extensions, not SDK operations. See [agent tool guide](tool-guide.md).
