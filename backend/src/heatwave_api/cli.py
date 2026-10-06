"""``heatwave-api``: operator commands for the backend.

    uv run heatwave-api migrate                    # apply pending database migrations
    uv run heatwave-api create-user USERNAME --display-name "Name"   # prompts for a password
    uv run heatwave-api set-password USERNAME      # prompts for the new password
    uv run heatwave-api check                      # run the full startup, then exit
    uv run heatwave-api openapi [--out PATH]       # write the OpenAPI contract

Passwords are read from a prompt, or from the environment variable named by
--password-env (for scripted setups); never from the command line, where they would
land in shell history.
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from heatwave_api.config import REPO_ROOT, get_settings
from heatwave_api.db import Database, MigrationError
from heatwave_api.db.repository import Repository
from heatwave_api.inference import StartupError
from heatwave_api.security import hash_password

MIN_PASSWORD_LENGTH = 12
OPENAPI_PATH = REPO_ROOT / "docs" / "api" / "openapi.json"


def _password(env_name: str | None) -> str:
    if env_name:
        password = os.environ.get(env_name, "")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            raise ValueError("the passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"use at least {MIN_PASSWORD_LENGTH} characters")
    return password


def openapi_schema() -> dict:
    from heatwave_api.main import create_app

    return create_app(configure_logs=False).openapi()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="heatwave-api", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate", help="apply pending database migrations")
    for name in ("create-user", "set-password"):
        p = sub.add_parser(name)
        p.add_argument("username")
        p.add_argument("--password-env", help="read the password from this env variable")
        if name == "create-user":
            p.add_argument("--display-name", required=True)
    sub.add_parser("check", help="load everything the service loads at startup, then exit")
    out = sub.add_parser("openapi", help="write the OpenAPI schema")
    out.add_argument("--out", type=Path, default=OPENAPI_PATH)
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        if args.command == "openapi":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(openapi_schema(), indent=2, ensure_ascii=False) + "\n"
            args.out.write_text(text, encoding="utf-8")
            print(f"wrote {args.out}")
            return 0
        if args.command == "check":
            from heatwave_api.services import build_services

            services = build_services(settings)
            print(
                f"ok   model {services.model.model_version}, explainer "
                f"{services.model.explainer_id}, database {services.db.path}, "
                f"{len(services.reference.regions)} regions, notifications "
                f"{services.notifier.mode}"
            )
            return 0
        db = Database(settings.sqlite_path)
        applied = db.migrate()
        if args.command == "migrate":
            print(f"applied {applied}" if applied else "up to date", f"({db.path})")
            return 0
        with db.connect() as conn:
            repo = Repository(conn)
            if args.command == "create-user":
                if repo.user_by_username(args.username):
                    raise ValueError(f"user {args.username!r} already exists")
                repo.create_user(
                    args.username, hash_password(_password(args.password_env)), args.display_name
                )
                print(f"created user {args.username}")
            else:
                if not repo.set_password(
                    args.username, hash_password(_password(args.password_env))
                ):
                    raise ValueError(f"no user {args.username!r}")
                print(f"password changed for {args.username}")
        return 0
    except (StartupError, MigrationError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
