# Shared ngrok endpoint: Garmin + MyFitnessPal

Use one ngrok HTTPS hostname and one tunnel for both connectors. They are routed by distinct URL paths:

| Connector | MCP endpoint |
| --- | --- |
| Garmin Connect | `https://YOUR-NGROK-HOST/mcp/garmin-connect/` |
| MyFitnessPal | `https://YOUR-NGROK-HOST/myfitnesspal/mcp` |

Replace only `YOUR-NGROK-HOST` with the current hostname shown by ngrok. Keep each path ending exactly as shown. Both URLs share the same scheme, hostname, and tunnel. MyFitnessPal has its own OAuth endpoints and scopes (`myfitnesspal:read`, `myfitnesspal:write`); neither connector uses the other's OAuth grants or account state.

## Start the combined gateway (Windows)

This gateway currently runs on Windows. Install MyFitnessPal with the [release installer](getting-started.md), and make sure Garmin Connect MCP is already installed and its existing shared-ngrok configuration works. Stop Garmin's standalone public tunnel first; its local stdio server may remain available.

Open PowerShell and set the executable and data paths for your existing Garmin installation. The example below uses the MyFitnessPal release install location:

```powershell
$MfpPython = "$env:LOCALAPPDATA\MyFitnessPalMCP\venv\Scripts\python.exe"
$GarminPython = 'D:\path\to\garmin\.venv\Scripts\python.exe'
$GarminData = 'D:\developer\.garmin-connect-mcp'
```

Install the gateway's optional packages into the isolated MyFitnessPal environment:

```powershell
& $MfpPython -m pip install 'ngrok==1.7.0' 'pywin32>=310'
```

Start the combined gateway:

```powershell
& $MfpPython -m myfitnesspal_mcp.gateway --garmin-python $GarminPython --garmin-data $GarminData
```

The gateway runs Garmin's private HTTP backend on loopback port 8787, the shared listener on loopback port 8788, and opens a single ngrok endpoint. It reads the existing ngrok credential locally without changing it. If either port is already occupied, startup fails rather than silently choosing another port. MyFitnessPal OAuth state is encrypted in the installed environment's ignored `work/remote` directory.

Startup prints two full MCP URLs. Use the Garmin URL ending `/mcp/garmin-connect/` for Garmin and the MyFitnessPal URL ending `/myfitnesspal/mcp` for MyFitnessPal. Preserve the same current ngrok hostname in both URLs.

## Configure ChatGPT

1. Open ChatGPT settings and add a custom MCP server.
2. Enter the **MyFitnessPal** URL printed by startup, including `/myfitnesspal/mcp`.
3. Select OAuth and Dynamic Client Registration. Leave static client ID/secret blank.
4. Request scopes `myfitnesspal:read myfitnesspal:write`, then complete the local PowerShell consent command shown by the flow. Review the details and type `APPROVE` to grant.
5. Return to ChatGPT and continue. Verify `connection_status`, then request a dated diary read.

For read-only access, request only `myfitnesspal:read`. To expand a prior read-only grant, delete/recreate the ChatGPT registration so it can request the write scope; refreshing tools cannot expand an approved grant.

## Operational notes

- One hostname, one tunnel, unique connector paths. Do not start the old Garmin standalone public tunnel alongside the combined gateway.
- Your Windows computer must stay awake and Firefox must remain signed in.
- If your ngrok hostname changes, update both ChatGPT connector URLs and reconnect each one to its matching path.
- Ctrl+C stops the foreground gateway and its Garmin child service. To return to Garmin-only operation, stop the combined gateway and restart Garmin's original tunnel launcher.
- `remote-reset` revokes MyFitnessPal clients/grants after local confirmation and preserves Garmin grants and ngrok credentials.
- Never share OAuth tokens, cookie exports, ngrok credentials, or encrypted state directories.

This is a local owner gateway, not a hosted multi-user service. Linux and macOS are supported for local stdio; the shared remote gateway is currently Windows-only.
