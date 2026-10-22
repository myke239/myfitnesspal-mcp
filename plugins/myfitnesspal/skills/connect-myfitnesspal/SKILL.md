---
name: connect-myfitnesspal
description: Verify or troubleshoot the local MyFitnessPal MCP connection and browser-session authentication.
---

Use connection_status to verify live account access. Authentication comes from a locally signed-in Chrome session by default; MFP_BROWSER can select edge or firefox. MFP_COOKIE_FILE can instead select a local Netscape cookie file. Never request session secrets in chat or include them in tool arguments.

Start discovery with get_myfitnesspal_tool_guide: it needs no account login and returns the live tool catalog, input schemas and workflow routes. Local stdio tools are supplied by this plugin; remote ChatGPT receives tool descriptions and the guide, not these local SKILL.md files automatically. The packaged plugin selects Firefox, as does the shared remote gateway; Chrome is only the underlying unconfigured service default.

For missing photo tools, refresh/reconnect the connector and verify estimate_food_from_attachment is advertised with openai/fileParams for image. Attach or paste the photo with this app selected. The host must resolve the attachment into download_url and file_id; the server cannot turn a bare ID or sandbox path into a URL. Mobile handoff remains client-dependent; never claim analysis of an inaccessible image. Image inference uses a separate server-side OpenAI API key, not MyFitnessPal browser authentication. Never request that key in chat.

If authentication fails, direct the user to sign in on myfitnesspal.com in their selected browser and run the installed myfitnesspal-mcp verify command locally. Browser cookie encryption may prevent extraction even when login works; a local cookie file is an alternative. Refer to the project's README for setup. Do not automatically weaken browser security or export cookies.

The plugin uses an absolute project virtual-environment interpreter; a moved checkout requires updating .mcp.json. This is an unofficial integration and upstream website changes can break reads. A successful connection check verifies authentication; a successful diary read additionally checks diary compatibility. Implemented writes are enabled by default. Remote writes require myfitnesspal:write as well as myfitnesspal:read; existing read-only registrations need recreation with both scopes. Tool discovery is not evidence of live mutation compatibility.
