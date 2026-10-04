"""Operator CLI for long-term trust checks (run from CI/CD, cron, or before an upgrade).

    python -m loadguard.ops verify-sample --n 500   # re-run recorded decisions with the current engine
    python -m loadguard.ops audit-verify            # check the tamper-evident audit hash chain
    python -m loadguard.ops status                  # worker liveness and queue health
    python -m loadguard.ops alive                   # container healthcheck for a worker (own heartbeat)

Exit code is non-zero when a check fails, so it can gate a deployment pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys

from loadguard.db.session import unit_of_work
from loadguard.services.common import verify_audit_chain
from loadguard.services.governance import local_worker_alive, system_status, verify_sample


def main() -> int:
    p = argparse.ArgumentParser(prog="loadguard.ops")
    sub = p.add_subparsers(dest="cmd", required=True)
    vs = sub.add_parser("verify-sample")
    vs.add_argument("--n", type=int, default=200)
    vs.add_argument("--max-mismatch-rate", type=float, default=0.0)
    sub.add_parser("audit-verify")
    sub.add_parser("status")
    sub.add_parser("alive")
    args = p.parse_args()

    with unit_of_work() as s:
        if args.cmd == "verify-sample":
            out = verify_sample(s, args.n)
            rate = 1 - out["reproduced"] / out["checked"] if out["checked"] else 0.0
            ok = rate <= args.max_mismatch_rate
        elif args.cmd == "alive":
            ok = local_worker_alive(s)
            return 0 if ok else 1
        elif args.cmd == "audit-verify":
            out = verify_audit_chain(s)
            ok = bool(out["ok"])
        else:
            out = system_status(s)
            ok = bool(out["healthy"])
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
