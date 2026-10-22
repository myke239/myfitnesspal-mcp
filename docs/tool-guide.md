# Agent tool guide

The [complete tool reference](../plugins/myfitnesspal/skills/manage-myfitnesspal/references/tool-guide.md) covers every MCP tool, exact inputs, write operations, attachment handling, task routes and retry semantics. It ships with the plugin. Regenerate it with `.venv/Scripts/python.exe scripts/update_tool_docs.py` after changing tool contracts.

Remote ChatGPT agents should call `get_myfitnesspal_tool_guide` for live tool discovery and complete input schemas without account authentication or inference usage. The remote endpoint does not automatically deliver local skill files. Refresh or reconnect the app when ChatGPT caches an older tool list.

The plugin bundles five skills: estimate-food, manage-myfitnesspal, analyze-nutrition, analyze-measurements and connect-myfitnesspal. Skill selection is enabled by default. Updating source files updates this project bundle; an installed cached plugin copy may need updating or reloading in its host.
