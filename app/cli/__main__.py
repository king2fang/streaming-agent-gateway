"""CLI entrypoint."""
import argparse
import sys
from .runner import run_cmd, watch_cmd, cancel_cmd, list_cmd

def main():
    parser = argparse.ArgumentParser(description="Streaming Agent Gateway CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_run = subparsers.add_parser("run", help="Create a run and stream output")
    p_run.add_argument("--model", default="mock", help="Model name (default: mock)")
    p_run.add_argument("--prompt", required=True, help="User prompt")
    p_run.add_argument("--tools", action="store_true", help="Enable mock tools")
    p_run.add_argument("--harness", default="none", choices=["none", "error", "timeout", "drop"], help="Inject fault")
    p_run.set_defaults(func=run_cmd)

    p_watch = subparsers.add_parser("watch", help="Watch an existing run")
    p_watch.add_argument("run_id", help="The Run ID to watch")
    p_watch.add_argument("--last-id", type=int, default=0, help="Last-Event-ID to resume from")
    p_watch.set_defaults(func=watch_cmd)

    p_cancel = subparsers.add_parser("cancel", help="Cancel a running run")
    p_cancel.add_argument("run_id", help="The Run ID to cancel")
    p_cancel.set_defaults(func=cancel_cmd)

    p_list = subparsers.add_parser("list", help="List recent runs")
    p_list.set_defaults(func=list_cmd)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
