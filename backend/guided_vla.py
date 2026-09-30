"""Operator-only preparation/check or one explicitly requested Guided API call. No other models."""
import argparse
import json
from uuid import UUID

from backend.model_clients.guided_vla import GuidedVLAClient, GuidedVLAError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "check", "run"))
    parser.add_argument("--attempt-id", type=UUID)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "run" and (not args.live or args.attempt_id is None):
        parser.error("run requires --live and --attempt-id; never retries")
    if args.action != "run" and args.live:
        parser.error("--live is accepted only for run")
    try:
        client = GuidedVLAClient()
        if args.action == "prepare":
            if args.attempt_id:
                parser.error("prepare creates a fresh UUID")
            attempt = client.prepare()
        else:
            if args.attempt_id is None:
                parser.error("check/run requires --attempt-id")
            attempt = client.settings.attempts / str(args.attempt_id)
        if args.action == "run":
            client.execute(attempt, live=True)
        report = client.summary(attempt)
        report.update(status="GUIDED_VLA_RESPONSE_PASS" if args.action == "run" else "GUIDED_VLA_ADAPTER_OFFLINE_READY",
                      live_called=args.action == "run", attempt_directory=str(attempt))
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 0
    except GuidedVLAError as exc:
        print(json.dumps({"status": "GUIDED_VLA_ADAPTER_BLOCKED", "code": exc.code}, ensure_ascii=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
