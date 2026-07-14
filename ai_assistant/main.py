from __future__ import annotations

import argparse

from . import cli


def main() -> None:
    parser = argparse.ArgumentParser(prog="ai_assistant")
    parser.add_argument("--reindex", action="store_true", help="rebuild the RAG index")
    args = parser.parse_args()
    cli.run(reindex=args.reindex)


if __name__ == "__main__":
    main()
