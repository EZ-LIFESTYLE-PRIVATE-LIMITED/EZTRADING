"""Manage premium coupons from the command line (no admin UI yet).

  python -m scripts.coupons list
  python -m scripts.coupons add DIWALI50 --percent 50 --until 2026-11-30 --max 100
  python -m scripts.coupons add FLAT100 --flat 100
  python -m scripts.coupons add TRIAL14 --free-days 14
  python -m scripts.coupons disable DIWALI50

In Docker:  docker compose exec web python -m scripts.coupons list
"""

from __future__ import annotations

import argparse
from datetime import datetime

from app.config import Settings
from app.db.base import make_engine, make_session_factory
from app.repositories.billing import CouponRepository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    add = sub.add_parser("add", help="create or update a coupon")
    add.add_argument("code")
    kind = add.add_mutually_exclusive_group(required=True)
    kind.add_argument("--percent", type=int, help="percent off the price (1-100)")
    kind.add_argument("--flat", type=int, help="rupees off the price")
    kind.add_argument("--free-days", type=int, help="days of premium, no payment")
    add.add_argument("--until", help="last valid day, YYYY-MM-DD (UTC)")
    add.add_argument("--max", type=int, help="total redemptions allowed (default unlimited)")
    off = sub.add_parser("disable")
    off.add_argument("code")
    args = parser.parse_args()

    settings = Settings()
    with make_session_factory(make_engine(settings.database_url))() as db:
        repo = CouponRepository(db)
        if args.cmd == "list":
            for c in repo.all():
                until = c.valid_until.date().isoformat() if c.valid_until else "no expiry"
                print(f"{c.code:<16} {c.kind:<9} {c.value:>5}  {until:<10}  used {repo.redemptions(c.code)}"
                      f"/{c.max_redemptions or '∞'}  {'active' if c.active else 'disabled'}")
        elif args.cmd == "add":
            if args.percent is not None and not 1 <= args.percent <= 100:
                parser.error("--percent must be 1-100")
            kind, value = (("percent", args.percent) if args.percent is not None
                           else ("flat", args.flat) if args.flat is not None else ("free_days", args.free_days))
            until = datetime.fromisoformat(args.until).replace(hour=23, minute=59, second=59) if args.until else None
            repo.upsert(args.code, kind=kind, value=value, max_redemptions=args.max, valid_until=until, active=True)
            print(f"Saved {args.code.upper()}: {kind} {value}")
        elif args.cmd == "disable":
            if repo.get(args.code) is None:
                parser.error(f"No coupon {args.code.upper()}")
            repo.upsert(args.code, active=False)
            print(f"Disabled {args.code.upper()}")


if __name__ == "__main__":
    main()
