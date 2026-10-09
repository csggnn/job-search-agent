"""
CLI entrypoint: serve the read-only database UI for one evaluations database.

    podman-compose exec ui python3 -m ui.browse_db --db data/evaluations.db

The server listens on all interfaces inside the container. The compose file publishes the
port on the host's 127.0.0.1 only.
"""

import argparse

from ui.browser import create_app

DEFAULT_PORT = 8000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, help="path of the evaluations database to show")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"port to listen on (default {DEFAULT_PORT})")
    args = parser.parse_args()

    create_app(args.db).run(host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
