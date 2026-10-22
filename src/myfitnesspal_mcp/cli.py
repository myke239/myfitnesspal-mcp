"""Command line entrypoint."""

import argparse
import json
import os

from .service import AccessError, Service


def main():
    parser = argparse.ArgumentParser(description="Local MyFitnessPal MCP server")
    parser.add_argument(
        "command", choices=["serve", "verify"], nargs="?", default="serve"
    )
    parser.add_argument(
        "--browser",
        choices=["chrome", "edge", "firefox"],
        help="Select the signed-in browser (overrides MFP_BROWSER).",
    )
    args = parser.parse_args()
    if args.browser:
        os.environ["MFP_BROWSER"] = args.browser
    if args.command == "serve":
        from .server import mcp

        mcp.run(transport="stdio")
    else:
        try:
            print(json.dumps(Service().connection_status(), indent=2))
        except AccessError as error:
            parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
