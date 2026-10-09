"""
CLI entrypoint: serve the read-only database UI for one evaluations database.

    podman-compose exec ui python3 -m ui.browse_db --db data/evaluations.db

The server listens on --host, 127.0.0.1 by default. The ui compose service sets
UI_HOST=0.0.0.0, the default of --host inside the container, so the published port reaches
it. The compose file publishes that port on the host's 127.0.0.1 only.
"""

import argparse
import os

from ui.browser import create_app

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="path of the evaluations database to show")
    parser.add_argument("--host", default=os.environ.get("UI_HOST", DEFAULT_HOST),
                        help=f"address to listen on (default $UI_HOST, else {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"port to listen on (default {DEFAULT_PORT})")
    args = parser.parse_args()

    create_app(args.db).run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
