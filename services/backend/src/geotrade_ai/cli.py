"""`backend api | worker | migrate | seed | evaluate | openapi` - one image, several roles."""

import argparse
import json
import sys

from geotrade_ai.core.config import get_settings
from geotrade_ai.core.logging import setup_logging


def cmd_api(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "geotrade_ai.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_config=None,
    )


def cmd_openapi(args: argparse.Namespace) -> None:
    from geotrade_ai.api.app import create_app

    spec = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        sys.stdout.write(spec)
    else:
        with open(args.out, "w") as f:
            f.write(spec)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="backend")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("api", help="run the HTTP API")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workers", type=int, default=1)
    p.set_defaults(fn=cmd_api)

    p = sub.add_parser("openapi", help="export the OpenAPI document")
    p.add_argument("--out", default="-")
    p.set_defaults(fn=cmd_openapi)

    args = parser.parse_args(argv)
    setup_logging(get_settings().log_level)
    args.fn(args)


if __name__ == "__main__":
    main()
