"""Local numeric-only budget administration; no automatic resets or public writes."""

import argparse
import json

from sqlalchemy.exc import SQLAlchemyError

from app.application.budget import BudgetError, TokenBudgetService


def main():
    parser = argparse.ArgumentParser(
        description="Inspect and reconcile the durable project Token budget"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("pending")
    commands.add_parser("acknowledge-overrun")
    history = commands.add_parser("reconcile-history")
    history.add_argument("--confirmed-total", type=int, required=True)
    initialize = commands.add_parser("initialize")
    initialize.add_argument("--limit", type=int, default=1_000_000)
    initialize.add_argument("--prior-confirmed", type=int, default=0)
    initialize.add_argument("--prior-uncertain", type=int, default=0)
    reconcile = commands.add_parser("reconcile")
    reconcile.add_argument("request_id")
    reconcile.add_argument("--input-tokens", type=int, required=True)
    reconcile.add_argument("--output-tokens", type=int, required=True)
    args = parser.parse_args()
    from app.main import app

    if app.state.session_factory is None:
        parser.exit(1, "budget_storage_unavailable\n")
    service = TokenBudgetService(app.state.session_factory)
    try:
        if args.command == "initialize":
            service.initialize(args.limit, args.prior_confirmed, args.prior_uncertain)
        elif args.command == "reconcile":
            service.settle(args.request_id, args.input_tokens, args.output_tokens, reconcile=True)
        elif args.command == "reconcile-history":
            service.reconcile_history(args.confirmed_total)
        elif args.command == "acknowledge-overrun":
            service.acknowledge_overrun()
        result = service.pending() if args.command == "pending" else service.status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except BudgetError as error:
        parser.exit(1, f"{error.code}\n")
    except SQLAlchemyError:
        parser.exit(1, "budget_storage_unavailable\n")
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
