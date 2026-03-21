"""
Nimbus entry point.
Usage: python -m nimbus [--config path/to/config.yaml]
"""

import argparse
import logging
import os
import sys
import yaml

from .bot import NimbusBot


def load_config(path: str) -> dict:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        print(f"Config not found: {path}")
        print("Copy config.example.yaml to config.yaml and fill in your values.")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="Nimbus — Mobile AI Agent Command Center")
    parser.add_argument(
        "--config", "-c",
        default=os.environ.get("NIMBUS_CONFIG", "config.yaml"),
        help="Path to config file (default: config.yaml or $NIMBUS_CONFIG)"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.DEBUG if args.debug else logging.INFO
    )

    config = load_config(args.config)
    bot = NimbusBot(config)
    bot.run()


if __name__ == "__main__":
    main()
