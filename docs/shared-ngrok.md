# Shared ngrok endpoint: Garmin + MyFitnessPal

Use the same authenticated ngrok HTTPS hostname and tunnel for both connectors. The gateway routes by URL path:

| Connector | MCP endpoint |
| --- | --- |
| Garmin Connect (existing) | `https://YOUR-NGROK-HOST/mcp` |
| MyFitnessPal | `https://YOUR-NGROK-HOST/myfitnesspal/mcp` |

Replace only `YOUR-NGROK-HOST` with the current hostname shown by ngrok. Keep the distinct path endings exactly as shown. MyFitnessPal also uses its own OAuth endpoints and scopes (`myfitnesspal:read`, `myfitnesspal:write`); Garmin's existing endpoint, OAuth grants, and local installation remain in place.

## Start the combined gateway (Windows)

Install the remote dependencies with the project's Python environment:

```powershell
python -m pip install -e ".[remote]"
```

Stop Garmin's standalone public tunnel first. Keep its local stdio configuration if you use it. Start the gateway, supplying your existing Garmin Python interpreter and data directory:

```powershell
.\scripts\myfitnesspal.ps1 gateway -GarminPython 'D:\path\to\garmin\.venv\Scripts\python.exe' -GarminData 'D:\developer\.garmin-connect-mcp'
```

The gateway runs the Garmin backend on loopback port 8787, the shared listener on loopback port 8788, and opens one ngrok endpoint. It reads the existing local ngrok credential without changing it. Port conflicts fail clearly rather than silently picking another port. MyFitnessPal remote state is encrypted under the project's ignored `work/remote` directory.

The MyFitnessPal MCP endpoint printed by startup ends in `/myfitnesspal/mcp`; give that full URL to ChatGPT's custom MCP server setup. Keep your existing Garmin connection at `/mcp`.

## Configure ChatGPT

1. Open ChatGPT settings and add a custom MCP server.
2. Enter `https://YOUR-NGROK-HOST/myfitnesspal/mcp` (including `/myfitnesspal/mcp`).
3. Select OAuth and Dynamic Client Registration. Leave static client ID/secret blank.
4. Request scopes `myfitnesspal:read myfitnesspal:write`, then complete the local PowerShell consent command shown by the flow. Review the details and type `APPROVE` to grant.
5. Return to ChatGPT and continue. Verify `connection_status`, then request a dated diary read.

For read-only use, request only `myfitnesspal:read`. To expand a prior read-only grant, delete/recreate the ChatGPT registration so it can request the write scope; refreshing tools cannot expand an approved grant.

## Operational notes

- One hostname, one tunnel, unique paths: do not start the old Garmin standalone tunnel alongside the combined gateway.
- Your computer must stay awake; Firefox must remain signed in.
- A current ngrok hostname must be used in both connector registrations after a tunnel hostname changes. Reconnect only the connector whose resource URL changed.
- Ctrl+C stops the foreground gateway and its Garmin child service. Return to Garmin-only operation by stopping the gateway and restarting its original tunnel launcher.
- `remote-reset` revokes MyFitnessPal clients/grants after local confirmation and preserves Garmin grants and ngrok credentials.
- Never share OAuth tokens, cookie exports, ngrok credentials, or encrypted state directories.

Security details and limitations are documented in the root README. This setup is a local owner gateway, not a hosted multi-user service.
