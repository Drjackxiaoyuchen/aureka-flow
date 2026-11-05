"""Run with: python -m aureka_flow [--port 8765] [--no-browser]."""
import argparse
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def open_when_ready(url):
    for _ in range(60):
        try:
            with urllib.request.urlopen(url + "/api/state", timeout=1) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except OSError:
            time.sleep(.5)


def main():
    parser = argparse.ArgumentParser(description="Aureka Flow local cytometry workspace")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port from 1024 to 65535.")
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(f"http://127.0.0.1:{args.port}",), daemon=True).start()
    uvicorn.run("aureka_flow.server:app", host="127.0.0.1", port=args.port, workers=1)


if __name__ == "__main__":
    main()
