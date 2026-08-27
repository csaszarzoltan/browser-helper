"""
Browser Helper — entry point.

Ensures correct import path regardless of how you run it.

Usage:
    python run.py
    python run.py --port 8000
    python run.py --port 8000 --launch-chrome
    python run.py --launch-chrome --profile-dir "C:\\Users\\...\\User Data\\Default"
    python run.py --launch-chrome --debug-port 9222
    python run.py --launch-chrome --headless=new --display :99  # CI (no VNC)
"""

import argparse
import os
import sys

# Put src/ first on the import path
# This prevents conflicts with any other installed 'cdp_client' package
src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
sys.path.insert(0, src_dir)


def main():
    parser = argparse.ArgumentParser(description="Browser Helper API server")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")),
                        help="Server port (default: 8000, or $PORT)")
    parser.add_argument("--host", type=str, default=os.environ.get("HOST", "0.0.0.0"),
                        help="Bind address (default: 0.0.0.0, or $HOST)")
    parser.add_argument("--launch-chrome", action="store_true",
                        help="Launch Chrome with CDP debugging on startup")
    parser.add_argument("--profile-dir", type=str, default=None,
                        help="Chrome profile directory (only with --launch-chrome)")
    parser.add_argument("--debug-port", type=int, default=None,
                        help="Chrome debug port (only with --launch-chrome; default from settings)")
    parser.add_argument("--backend", type=str, default="cdp",
                        choices=["cdp", "playwright"],
                        help="Automation backend: cdp (default) or playwright")
    parser.add_argument("--display", type=str, default=None,
                        help="X11 display for Chrome (e.g. :1); forwarded as CHROME_DISPLAY")
    # P1-1 CI: headless Chrome without VNC — run.py --headless=new --display :99
    parser.add_argument("--headless", type=str, nargs="?", const="new", default=None,
                        help="Launch Chrome headless (--headless=new or --headless; forwarded as CHROME_HEADLESS)")
    args = parser.parse_args()

    # Pass launch parameters to the server via environment variables
    if args.launch_chrome:
        os.environ["CHROME_AUTO_LAUNCH"] = "1"
        if args.profile_dir:
            os.environ["CHROME_AUTO_PROFILE"] = args.profile_dir
        if args.debug_port:
            os.environ["CHROME_AUTO_PORT"] = str(args.debug_port)
    if args.display:
        os.environ["CHROME_DISPLAY"] = args.display
    if args.headless is not None:
        os.environ["CHROME_HEADLESS"] = args.headless

    import uvicorn

    print(f"🚀 Browser Helper starting on http://{args.host}:{args.port}")
    if args.launch_chrome:
        print("   → Auto-launching Chrome with CDP debugging")
        if args.profile_dir:
            print(f"   → Profile: {args.profile_dir}")
        if args.debug_port:
            print(f"   → Debug port: {args.debug_port}")
        if args.headless is not None:
            print(f"   → Headless: {args.headless}")
        if args.display:
            print(f"   → Display: {args.display}")

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
