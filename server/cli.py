"""server/cli.py — argparse unified CLI router for deos."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from server.cli_gates import _invocation_cwd, handle_pr_check
from server.cli_gemini import (
    handle_gemini_dispatch,
    handle_gemini_ingest,
    handle_gemini_next,
    handle_gemini_pending,
    handle_gemini_smoke,
    handle_gemini_status,
)
from server.cli_reports import handle_cost_report, handle_pilot_status

logger = logging.getLogger("deos.cli")

from server.ssot import _QUEUE_HEADER_STATUSES as QUEUE_HEADER_STATUSES, format_queue_with_header  # noqa: F401

_PROJECT: str | None = None  # set by main() from --project; consumed by _load()
_INVOCATION_CWD: Path | None = None  # captured once in main() via _invocation_cwd()

def _load() -> tuple:
    from server.config import ProjectResolutionError, resolve_paths
    cwd = _INVOCATION_CWD if _INVOCATION_CWD is not None else Path.cwd()
    try:
        return resolve_paths(_PROJECT, cwd=cwd)
    except ProjectResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("error: no project resolved — pass --project <name>, "
              "run inside a project dir (.deos.yaml), or run from the host root", file=sys.stderr)
        sys.exit(1)


def _validate_ticket_id_arg(ticket_id: str) -> str:
    from server._ticket_id import TicketIdError, validate_ticket_id
    try:
        validate_ticket_id(ticket_id)
    except TicketIdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    return ticket_id

def _handle_queue(args):
    _c, paths = _load()
    print(format_queue_with_header(paths["queue"])); return 0
def _handle_status(args):
    from server.ssot import format_status_summary, read_archive
    _c, paths = _load()
    archived = len(read_archive(paths["queue"]).get("tickets", []))
    print(f"archived: {archived}")
    print(format_status_summary(paths["devos"])); return 0
def _handle_pending(args):
    from server.approval import ApprovalManager
    _c, paths = _load()
    print(ApprovalManager(paths["plans"], paths["queue"]).format_pending_summary()); return 0
def _handle_logs(args):
    from server.ssot import format_logs_summary
    _c, paths = _load()
    print(format_logs_summary(paths["logs"])); return 0

def _handle_dashboard(args):
    from server.config import host_root
    from server.dashboard import serve
    return serve(host_root(), port=args.port, open_browser=not args.no_open)

def _handle_archive(args):
    from server.ssot import ArchiveLockError, archive_done_tickets
    _c, paths = _load()
    try:
        moved, _ = archive_done_tickets(paths["queue"])
    except ArchiveLockError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("no done tickets to archive" if moved == 0 else f"archived {moved} done tickets")
    return 0

def _handle_dispatch(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    config, paths = _load()
    from server.dispatcher import (
        Dispatcher, DispatcherSingletonError, acquire_dispatcher_singleton, route_by_owner,
    )
    from server.ssot import read_queue_with_archive
    try:
        queue = read_queue_with_archive(paths["queue"])
        ticket = next((t for t in queue.get("tickets", []) if t.get("id") == ticket_id), None)
    except Exception:
        ticket = None
    if ticket:
        routing = route_by_owner(ticket.get("owner", ""))
        if routing["action"] in ("in_session_message", "interactive_only"):
            print(routing["message"])
            return routing["exit_code"]
        if routing["action"] == "unknown":
            print(routing["message"], file=sys.stderr)
            return routing["exit_code"]
        if routing["action"] == "deprecated_reject":
            sys.stderr.write(routing["message"] + "\n")
            return routing["exit_code"]
    try:
        with acquire_dispatcher_singleton(config, paths):
            d = Dispatcher(config=config, paths=paths)
            _, msg = d.dispatch(ticket_id)
            print(msg)
            d.wait_all()
    except DispatcherSingletonError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    return 0

def _handle_dispatch_all(args):
    config, paths = _load()
    from server.dispatcher import Dispatcher, DispatcherSingletonError, acquire_dispatcher_singleton
    try:
        with acquire_dispatcher_singleton(config, paths):
            d = Dispatcher(config=config, paths=paths)
            results = d.dispatch_all_todo()
    except DispatcherSingletonError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    if not results:
        print("No todo tickets to dispatch.")
    for tid, msg in results:
        print(f"  {tid}: {msg}")
    return 0

def _handle_dispatch_codex(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    config, paths = _load()
    from server.dispatcher import (
        Dispatcher, DispatcherSingletonError, acquire_dispatcher_singleton, route_by_owner,
    )
    from server.ssot import read_queue_with_archive
    try:
        queue = read_queue_with_archive(paths["queue"])
        ticket = next((t for t in queue.get("tickets", []) if t.get("id") == ticket_id), None)
    except Exception:
        ticket = None
    if ticket:
        owner = ticket.get("owner", "")
        if owner.upper() != "CODEX":
            print(
                f"error: dispatch-codex requires owner=CODEX; ticket {ticket_id} has owner={owner!r}. "
                "Use 'deos dispatch' for non-CODEX tickets.",
                file=sys.stderr,
            )
            return 1
    try:
        with acquire_dispatcher_singleton(config, paths):
            d = Dispatcher(config=config, paths=paths)
            _, msg = d.dispatch(ticket_id)
            print(msg)
            d.wait_all()
    except DispatcherSingletonError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    return 0

def _handle_owner(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    if ticket_id.startswith("T="):
        ticket_id = ticket_id[2:]
    _c, paths = _load()
    from server.ssot import read_queue_with_archive
    try:
        queue = read_queue_with_archive(paths["queue"])
    except Exception as exc:
        print(f"queue read error: {exc}", file=sys.stderr)
        return 1
    ticket = next((t for t in queue.get("tickets", []) if t.get("id") == ticket_id), None)
    if not ticket:
        print(f"not_found: {ticket_id}", file=sys.stderr)
        return 1
    print(ticket.get("owner", ""))
    return 0

def _handle_cross_model_codex(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    reason = getattr(args, "reason", None) or "uncertainty flag from reviewer/security sub-agent"
    from server.dispatcher import cross_model_codex
    import yaml as _yaml
    result = cross_model_codex(ticket_id, reason)
    print(_yaml.safe_dump(result, allow_unicode=True, sort_keys=False), end=""); return 0 if not result.get("fallback") else 2

def _handle_next(args):
    from server.ssot import read_queue_with_archive
    _c, paths = _load()
    todos = [t for t in read_queue_with_archive(paths["queue"]).get("tickets", []) if t.get("status") == "todo"]
    if not todos: print("no todo tickets"); return 0
    print(f"{todos[0].get('id')} — {todos[0].get('goal', '')[:80]}"); return 0

def _handle_dispatch_next(args):
    from server.ssot import read_queue_with_archive
    _c, paths = _load()
    todos = [t for t in read_queue_with_archive(paths["queue"]).get("tickets", []) if t.get("status") == "todo"]
    if not todos: print("no todo tickets"); return 0
    return _handle_dispatch(argparse.Namespace(ticket_id=todos[0]["id"]))

def _handle_verify(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    config, paths = _load()
    from server.dispatcher import Dispatcher
    from server.ssot import read_queue_with_archive
    ticket = next((t for t in read_queue_with_archive(paths["queue"]).get("tickets", []) if t.get("id") == ticket_id), None)
    if ticket is None: print(f"ticket not found: {ticket_id}", file=sys.stderr); return 1
    ok, msg = Dispatcher(config=config, paths=paths)._run_ticket_verify(ticket)
    print(msg); return 0 if ok else 1


def _handle_resume(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    config, paths = _load()
    from server.dispatcher import Dispatcher, DispatcherSingletonError, acquire_dispatcher_singleton
    try:
        with acquire_dispatcher_singleton(config, paths):
            d = Dispatcher(config=config, paths=paths)
            ok, msg = d.resume(ticket_id)
            if not ok: print(msg, file=sys.stderr); return 1
            print(msg); d.wait_all()
    except DispatcherSingletonError as exc:
        print(exc, file=sys.stderr); return exc.exit_code
    return 0


def _handle_lookup(args):
    tid = _validate_ticket_id_arg(args.ticket_id)
    _c, paths = _load()
    import yaml
    from server.ssot import archive_path_for_queue, find_archived_ticket, read_queue_with_archive
    if getattr(args, "archive", False):
        t = find_archived_ticket(archive_path_for_queue(paths["queue"]), tid)
        if t is None:
            print(f"ticket not_found: {tid}", file=sys.stderr); return 1
    else:
        t = next((x for x in read_queue_with_archive(paths["queue"]).get("tickets", [])
                  if x.get("id") == tid), None)
        if t is None:
            print(f"ticket not found: {tid}", file=sys.stderr); return 1
    print(yaml.safe_dump(t, allow_unicode=True, sort_keys=False), end=""); return 0


def _handle_user_review(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    config, paths = _load()
    from server.dispatcher import Dispatcher
    ok, msg = Dispatcher(config=config, paths=paths).user_review(ticket_id)
    print(msg); return 0 if ok else 1


def _handle_set_status(args):
    ticket_id = _validate_ticket_id_arg(args.ticket_id)
    _c, paths = _load()
    from server.ssot import update_ticket_status
    override = getattr(args, "override", False)
    reason_flag = getattr(args, "reason_flag", None)
    actor_flag = getattr(args, "actor_flag", None)
    if override:
        miss = [f for f, v in (("--reason", reason_flag), ("--actor", actor_flag)) if not v or not v.strip()]
        if miss: print(f"error: --override requires {' and '.join(miss)}", file=sys.stderr); return 2
    reason = reason_flag or getattr(args, "reason_pos", None) or ""  # flag > positional
    actor = actor_flag or getattr(args, "actor_pos", None) or "user"
    try:
        updated = update_ticket_status(paths["queue"], ticket_id, args.status, reason=reason, actor=actor, override=override)
    except Exception as exc:
        print(f"ValidationError: {exc}", file=sys.stderr); return 1
    if not updated: print(f"Ticket `{ticket_id}` not found in queue.", file=sys.stderr); return 1
    print(f"updated {ticket_id} -> {args.status}"); return 0


def _handle_close(args):
    """Record verdict + advance ticket to done (doing→code_ready→done) atomically."""
    tid = _validate_ticket_id_arg(args.ticket_id)
    _c, paths = _load()
    from server.ssot import ValidationError, close_ticket_atomic, read_queue
    data = read_queue(paths["queue"])
    t = next((t for t in data.get("tickets", []) if t.get("id") == tid), None)
    if t is None: print(f"error: ticket {tid!r} not found.", file=sys.stderr); return 1
    if t.get("status") == "done": print(f"error: {tid!r} already done.", file=sys.stderr); return 1
    try:
        close_ticket_atomic(paths["queue"], tid, args.verdict, by=args.by,
            confidence=float(args.confidence), note=args.note or "",
            reason=args.reason or "", actor=args.by)
    except ValidationError as exc: print(f"error: {exc}", file=sys.stderr); return 1
    print(f"closed {tid} -> done (verdict={args.verdict} by={args.by})"); return 0


def _handle_approve(args):
    config, paths = _load()
    from server.approval import ApprovalManager
    from server.ssot import AmbiguousPlanMatchError, validate_queue_file
    from server.dispatcher import Dispatcher, DispatcherSingletonError, acquire_dispatcher_singleton
    approval = ApprovalManager(paths["plans"], paths["queue"])
    try:
        ok, msg = approval.approve(getattr(args, "plan_id", None))
    except AmbiguousPlanMatchError as exc:
        print(exc, file=sys.stderr)
        return 1
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print(msg)
    try:
        validate_queue_file(paths["queue"])
    except Exception as exc:
        print(f"Queue validation failed after approval: {exc}", file=sys.stderr)
        return 1
    try:
        with acquire_dispatcher_singleton(config, paths):
            d = Dispatcher(config=config, paths=paths)
            for tid, m in d.dispatch_all_todo():
                print(f"  {tid}: {m}")
    except DispatcherSingletonError as exc:
        print(exc, file=sys.stderr)
        return exc.exit_code
    return 0


def _handle_reject(args):
    _c, paths = _load()
    from server.approval import ApprovalManager
    from server.ssot import AmbiguousPlanMatchError
    approval = ApprovalManager(paths["plans"], paths["queue"])
    try:
        ok, msg = approval.reject(args.reason, getattr(args, "plan_id", None))
    except (AmbiguousPlanMatchError, FileNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print(msg)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deos", description="deos - single entry point")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", metavar="<name>", default=None,
                        help="Target project under host projects/ (default: cwd/host)")
    sub = parser.add_subparsers(dest="cmd", metavar="<command>")
    sub.required = True

    def _cmd(name, help_, handler, *add_args_fn):
        p = sub.add_parser(name, help=help_, parents=[common])
        p.set_defaults(handler=handler)
        for fn in add_args_fn:
            fn(p)
        return p

    def _add_strict(p):
        p.add_argument("--strict", action="store_true", default=False,
                       help="Exit nonzero when pilot readiness requirements are missing")

    _cmd("queue",        "List active tickets",               _handle_queue)
    _cmd("status",       "Show overall project status",       _handle_status)
    _cmd("pilot-status", "Show deos E2E pilot readiness", handle_pilot_status, _add_strict)
    _cmd("pending",      "Show pending plan approvals",       _handle_pending)
    _cmd("logs",         "Show session log summary",          _handle_logs)
    _cmd("archive",      "Archive done tickets",              _handle_archive)
    _cmd("next",         "Show next dispatchable ticket",     _handle_next)
    _cmd("dispatch-all", "Dispatch all todo tickets",         _handle_dispatch_all)
    _cmd("dispatch-next","Auto-select and dispatch next",     _handle_dispatch_next)

    def _add_ticket(p): p.add_argument("ticket_id", metavar="<ticket-id>")
    def _add_plan(p):   p.add_argument("plan_id", metavar="[plan-id]", nargs="?", default=None)
    def _add_reason(p): p.add_argument("reason", metavar="<reason>")

    def _add_ticket_with_reason(p):
        p.add_argument("ticket_id", metavar="<ticket-id>")
        p.add_argument("--reason", metavar="<reason>", default=None,
                       help="Uncertainty reason for cross-model review")

    _cmd("dispatch",           "Dispatch a ticket",                      _handle_dispatch,           _add_ticket)
    _cmd("dispatch-codex",     "Dispatch via Codex subprocess (CODEX owner only)",
         _handle_dispatch_codex, _add_ticket)
    _cmd("verify",             "Run verify commands for ticket",         _handle_verify,             _add_ticket)
    _cmd("resume",             "Resume a paused ticket",                 _handle_resume,             _add_ticket)
    _cmd("user-review",        "Trigger user outcome review",            _handle_user_review,        _add_ticket)
    _cmd("owner",              "Print ticket owner string",              _handle_owner,              _add_ticket)

    p_lookup = sub.add_parser("lookup", help="Print full ticket YAML (QUEUE then ARCHIVE)", parents=[common])
    p_lookup.add_argument("ticket_id", metavar="<ticket-id>"); p_lookup.set_defaults(handler=_handle_lookup)
    p_lookup.add_argument("--archive", action="store_true", default=False, help="ARCHIVE-INDEX lookup only")
    _cmd("cross-model-codex",  "b' adaptive CODEX second-opinion review",
         _handle_cross_model_codex, _add_ticket_with_reason)

    def _add_days(p):
        p.add_argument("--days", type=int, default=30,
                       help="Window in days (default 30)")

    def _add_dashboard_args(p):
        p.add_argument("--port", type=int, default=8787,
                       help="Localhost port to bind (default 8787)")
        p.add_argument("--no-open", action="store_true", default=False,
                       help="Do not open the dashboard in the default browser")

    _cmd("cost-report",        "Aggregate channel usage (C1/C2/C0) + cost estimate",
         handle_cost_report, _add_days)
    _cmd("dashboard",          "Serve the local read-only ticket dashboard",
         _handle_dashboard, _add_dashboard_args)
    _cmd("approve",            "Approve pending plan",                   _handle_approve,            _add_plan)
    _cmd("reject",             "Reject pending plan with reason",        _handle_reject,             _add_reason, _add_plan)
    _cmd("pr-check",           "Run all baseline PR gates (replaces make pr-check)", handle_pr_check)

    p = sub.add_parser("set-status", help="Update ticket status with reason", parents=[common])
    p.add_argument("ticket_id", metavar="<ticket-id>")
    p.add_argument("status",    metavar="<status>")
    p.add_argument("reason_pos", metavar="<reason>", nargs="?", default=None)
    p.add_argument("actor_pos",  metavar="[actor]",  nargs="?", default=None)
    p.add_argument("--override", action="store_true", default=False, help="Force transition (escape hatch)")
    p.add_argument("--reason",   dest="reason_flag", metavar="<reason>", default=None)
    p.add_argument("--actor",    dest="actor_flag",  metavar="<actor>",  default=None)
    p.set_defaults(handler=_handle_set_status)

    p_close = sub.add_parser("close", help="Record verdict + advance to done", parents=[common])
    p_close.add_argument("ticket_id", metavar="<ticket-id>")
    p_close.add_argument("--verdict",    metavar="OK|WARNING", required=True)
    p_close.add_argument("--by",         metavar="<reviewer>", required=True)
    p_close.add_argument("--confidence", metavar="<0-1>",      default="1.0")
    p_close.add_argument("--reason",     metavar="<text>",     default="")
    p_close.add_argument("--note",       metavar="<text>",     default="")
    p_close.set_defaults(handler=_handle_close)

    # host-level commands (no --project; operate on the host OS) — wiring in cli_host.py
    from server.cli_host import add_host_commands
    add_host_commands(sub)

    # gemini nested — parents=[common] propagates --project (DOD-2 fix)
    p_gem = sub.add_parser("gemini", help="Gemini integration subcommands", parents=[common])
    gsub = p_gem.add_subparsers(dest="gemini_cmd", metavar="<gemini-command>")
    gsub.required = True

    def _gcmd(name, help_, handler, *add_args_fn):
        g = gsub.add_parser(name, help=help_, parents=[common])
        g.set_defaults(handler=handler)
        for fn in add_args_fn:
            fn(g)

    _gcmd("pending",  "List pending Gemini handoff tickets",    handle_gemini_pending)
    _gcmd("next",     "Pick oldest pending, print guidance",    handle_gemini_next)
    _gcmd("ingest",   "Read stdin response, store log",         handle_gemini_ingest)
    _gcmd("status",   "Show Gemini quota + failure stats",      handle_gemini_status)
    _gcmd("smoke",    "Force re-run Gemini smoke test",         handle_gemini_smoke)
    _gcmd("dispatch", "Dispatch ticket to Gemini CLI",          handle_gemini_dispatch, _add_ticket)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch to handler. Returns integer exit code."""
    global _PROJECT, _INVOCATION_CWD
    _INVOCATION_CWD = _invocation_cwd()

    parser = _build_parser()
    args = parser.parse_args(argv)
    _PROJECT = getattr(args, "project", None)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    try:
        return handler(args) or 0
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 0
