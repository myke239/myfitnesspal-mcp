import asyncio
import json

from myfitnesspal_mcp.server import mcp


def test_guide_exposes_live_schemas_and_resolvable_workflow_routes():
    from myfitnesspal_mcp.operations import MODELS

    result = asyncio.run(mcp.call_tool("get_myfitnesspal_tool_guide", {}))
    guide = json.loads(result[0].text)
    # FastMCP structured output should be a complete discovery snapshot.
    names = {tool["name"] for tool in guide["tools"]}
    assert names == {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert set(guide["write_operations"]) == set(MODELS)
    assert all(name in names for route in guide["workflows"].values() for name in route)
    attachment = next(t for t in guide["tools"] if t["name"] == "estimate_food_from_attachment")
    assert attachment["_meta"]["openai/fileParams"] == ["image", "additional_images"]
    assert "inputSchema" in attachment


def test_tool_discovery_needs_no_authentication():
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == {
        "get_myfitnesspal_tool_guide",
        "estimate_food_from_image",
        "estimate_food_from_attachment",
        "connection_status",
        "get_report",
        "get_recipes",
        "get_recipe",
        "get_saved_meals",
        "get_saved_meal",
        "get_account_profile",
        "get_sdk_capabilities",
        "create_food",
        "set_measurement",
        "set_nutrition_goals",
        "get_food_diary",
        "get_nutrition_summary",
        "get_water",
        "get_exercise_diary",
        "get_measurements",
        "search_food",
        "get_food_details",
        "get_myfitnesspal_data",
        "get_myfitnesspal_write_schema",
        "execute_myfitnesspal_write",
    }
    assert {tool.name for tool in tools if not tool.annotations.readOnlyHint} == {
        "execute_myfitnesspal_write",
        "create_food",
        "set_measurement",
        "set_nutrition_goals",
    }
