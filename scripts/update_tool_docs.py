"""Generate the packaged tool catalog from live server schemas."""

import asyncio
import json
from pathlib import Path

from myfitnesspal_mcp import __version__
from myfitnesspal_mcp.operations import MODELS
from myfitnesspal_mcp.server import create_server


def main():
    tools = asyncio.run(create_server().list_tools())
    lines = [
        "# MyFitnessPal tool reference", "",
        f"Connector {__version__}. Use get_myfitnesspal_tool_guide for live discovery of all tools and schemas. "
        "These local skills are not automatically delivered to remote ChatGPT clients.", "",
        "## Task routes", "",
        "| Request | Tools |", "| --- | --- |",
        "| Attached or pasted photo | estimate_food_from_attachment |",
        "| Image URL or data | estimate_food_from_image |",
        "| Log food | get_account_profile → search_food → get_food_details → get_myfitnesspal_write_schema → execute_myfitnesspal_write → get_myfitnesspal_data(diary_entries) |",
        "| Edit/delete | get_myfitnesspal_data → get_myfitnesspal_write_schema → execute_myfitnesspal_write → read back |",
        "| Base calorie goal | get_myfitnesspal_data(nutrition_goals) |",
        "| Troubleshoot | get_myfitnesspal_tool_guide → connection_status → get_sdk_capabilities |",
        "", "## Every MCP tool", "",
        "Schemas below are generated from server descriptors, including defaults and nested types. "
        "Prefer live schemas if the server has changed.", "",
    ]
    for tool in tools:
        lines.extend([f"### {tool.name}", "", tool.description or "", "",
                      "```json", json.dumps(tool.inputSchema, indent=2), "```", ""])
        if tool.meta:
            lines.extend(["Tool metadata: `" + json.dumps(tool.meta) + "`", ""])
    lines.extend([
        "## Generic write operations", "",
        "These are operation values, not separate tool names. Fetch the full contract with "
        "get_myfitnesspal_write_schema(operation) before constructing parameters.", "",
        "| Operation | Required fields |", "| --- | --- |",
    ])
    for name, model in MODELS.items():
        required = ", ".join(model.model_json_schema().get("required", []))
        lines.append(f"| {name} | {required} |")
    lines.extend([
        "", "Typed alternatives: create_food → sdk_set_new_food; set_measurement → "
        "sdk_set_measurements; set_nutrition_goals → sdk_set_new_goal. All share the write ledger.",
        "", "## Worked serving example", "",
        "For measured 104 g and a detail response whose chosen serving has gram_weight 100, "
        "submit servings 1.04. For a 1 g serving, submit 104 servings. Use the actual food_id "
        "and serving_index from that response, not a serving ID or assumed list position. "
        "Check mass mappings; database entries may contain inconsistent gram weights.", "",
        "Use the canonical account meal name, e.g. Lunch. Unique case-insensitive matches "
        "also resolve. Read back diary_entries and stored nutrition after acknowledgement.", "",
        "## Outcomes", "",
        "- failed_before_write: no mutation sent. Inspect stage, reason and http_status. "
        "Identical retries can reuse the key; changed parameters require a new key.",
        "- outcome_unknown: inspect the target before retrying; do not force a new-key retry.",
        "- acknowledged: verify actual persisted values by reading back.",
        "- WRITE_SCOPE_REQUIRED: reconnect with myfitnesspal:read and myfitnesspal:write.",
        "- Missing/expired attachment URL: reattach with the app selected. Never invent a URL.",
        "", "Estimation is separate from logging. Model nutrients are estimates; measured TOTAL "
        "edible weight overrides visual mass. Mass ranges are subjective, not calibrated. "
        "Water writes replace the daily total; goal writes replace daily goals and clear meal goals.",
        "", "Attachment file inputs follow [official OpenAI documentation]"
        "(https://developers.openai.com/plugins/reference#file-apis).",
    ])
    path = Path("plugins/myfitnesspal/skills/manage-myfitnesspal/references/tool-guide.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
