"""Run with: python -m aureka_flow [--port 8765] [--no-browser]."""
import argparse
import os
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def open_when_ready(url, path="/"):
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url + path)
                    return
        except OSError:
            time.sleep(.5)


def main():
    parser = argparse.ArgumentParser(description="Aureka Flow browser cytometry workspace")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8765")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--practice", action="store_true", help="Open a synthetic FCS practice workspace in the browser.")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535.")
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        os.environ.setdefault("AUREKA_SERVER_MODE", "1")
        os.environ.setdefault("AUREKA_ALLOWED_HOSTS", "*")
    if not args.no_browser and args.host in {"127.0.0.1", "localhost", "::1"}:
        threading.Thread(target=open_when_ready, args=(f"http://127.0.0.1:{args.port}", "/?practice=1" if args.practice else "/"), daemon=True).start()
    uvicorn.run("aureka_flow.server:app", host=args.host, port=args.port, workers=1,
                proxy_headers=True, forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))


if __name__ == "__main__":
    main()
