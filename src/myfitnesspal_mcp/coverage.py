"""Maintained contract inventory for the pinned SDK, without authentication."""

import json
from pathlib import Path


def sdk_coverage():
    evidence_path = (
        Path(__file__).absolute().parents[2] / "work" / "sdk-verification.json"
    )
    try:
        evidence = json.loads(evidence_path.read_text())
    except (OSError, ValueError):
        evidence = {}
    mappings = {
        "get_date": (
            "get_food_diary",
            "SDK read; water/exercise also have dedicated tools",
        ),
        "get_measurements": (
            "get_measurements",
            "SDK read; explicit range cap and unit-loss disclosure",
        ),
        "get_report": (
            "get_report",
            "SDK read; date reconstruction and old-history warnings",
        ),
        "get_food_search_results": ("search_food", "SDK read; bounded result count"),
        "get_food_item_details": (
            "get_food_details",
            "Current API adapter with SDK field projection",
        ),
        "get_recipes": ("get_recipes", "SDK read; paged tool output"),
        "get_recipe": ("get_recipe", "SDK read; complete recipe dictionary"),
        "get_meals": ("get_saved_meals", "SDK read; paged tool output"),
        "get_meal": ("get_saved_meal", "SDK read; title resolved from account list"),
        "set_measurements": (
            "set_measurement",
            "Current web adapter; explicit non-weight units required",
        ),
        "set_new_food": (
            "create_food",
            "Current web adapter; SDK serving label/container mapping requires live verification",
        ),
        "set_new_goal": (
            "set_nutrition_goals",
            "Current web adapter and SDK calculations; rejects mixed/partial macros",
        ),
    }
    return {
        "sdk": "myfitnesspal",
        "pinned_version": "2.1.2",
        "operation_count": 12,
        "operations": [
            {
                "sdk_method": method,
                "tool": tool,
                "status": "implemented",
                "backend_and_differences": detail,
                "live_verification": evidence.get("operations", {}).get(
                    method, {"status": "not_live_verified"}
                ),
            }
            for method, (tool, detail) in mappings.items()
        ],
        "credentials": "Access tokens, cookies and diary passcodes are never exposed as tools.",
        "dates": "Dates default in MFP_TIMEZONE (America/Los_Angeles); explicit YYYY-MM-DD recommended.",
        "extensions": "Existing diary/custom-food mutations, water and fasting are additional connector operations, not SDK capabilities.",
        "verification": "Contract coverage does not establish live endpoint compatibility or mobile operation.",
        "evidence_date": evidence.get("date"),
    }
