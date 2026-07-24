"""
Browser Helper — entry point.

Ensures correct import path regardless of how you run it.
Usage: python run.py
       python run.py --port 8000
"""

import sys
import os

# Put src/ first on the import path
# This prevents conflicts with any other installed 'cdp_client' package
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, src_dir)


def main():
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")

    # Parse --port argument
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])
        elif arg.startswith("--port="):
            port = int(arg.split("=")[1])

    print(f"🚀 Browser Helper starting on http://{host}:{port}")
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
