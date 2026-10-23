import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "gateway":
        sys.argv.pop(1)
        from myfitnesspal_mcp.gateway import main
    elif len(sys.argv) > 1 and sys.argv[1] == "remote":
        sys.argv.pop(1)
        from myfitnesspal_mcp.remote import main
    else:
        from myfitnesspal_mcp.cli import main
    main()
