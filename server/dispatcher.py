"""Multi-agent dispatcher for os2-server.

Dispatches Claude 2, Codex, and Gemini for ticket execution.
Runs gate pipelines (tests, review) after completion.
Supports auto-retry on gate failure.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import os
import re
import subprocess
import threading
from pathlib import Path

from .ssot import (
    ValidationError,
    get_recent_logs,
    read_queue,
    update_ticket_fields,
    update_ticket_status,
)

logger = logging.getLogger(__name__)


class Dispatcher:
    """Dispatches builder agents for ticket execution."""

    def __init__(self, config: dict, paths: dict, notify_callback=None):
        """
        notify_callback: async callable(message: str) for completion notifications.
        """
        self.config = config
        self.paths = paths
        self.notify = notify_callback
        self.agent_configs = config.get("agents", {})
        self._running: dict[str, subprocess.Popen] = {}  # ticket_id -> process
        self._threads: dict[str, threading.Thread] = {}  # ticket_id -> thread
        self._state_lock = threading.RLock()

    # ── Public API ──────────────────────────────────────────────────────────

    def dispatch(self, ticket_id: str) -> tuple[bool, str]:
        """
        Dispatch a single ticket to its assigned agent.
        Returns (success, message).
        """
        with self._state_lock:
            try:
                data = read_queue(self.paths["queue"])
            except ValidationError as exc:
                return False, f"ValidationError: {exc}"
            ticket = next((t for t in data.get("tickets", []) if t.get("id") == ticket_id), None)

            if not ticket:
                return False, f"Ticket `{ticket_id}` not found in queue."

            status = ticket.get("status")
            if status not in ("todo",):
                return False, f"Ticket `{ticket_id}` is `{status}`, not `todo`. Cannot dispatch."

            owner = ticket.get("owner")
            target_owner = ticket.get("impl_owner") or owner
            if target_owner not in self.agent_configs:
                return False, f"Unknown owner `{target_owner}` for ticket `{ticket_id}`."

            # Fallback: if agent not available, use fallback agent
            resolved_owner, fallback_reason = self._resolve_agent(target_owner)

            # Check dependencies
            deps = ticket.get("deps", [])
            if deps:
                blocked_by = self._check_deps(data, deps)
                if blocked_by:
                    return False, f"Ticket `{ticket_id}` blocked by: {', '.join(blocked_by)}"

            # Check concurrent limit
            max_concurrent = self.config.get("dispatch", {}).get("max_concurrent", 2)
            if len(self._running) >= max_concurrent:
                return False, f"At capacity ({max_concurrent} agents running). Wait for completion."

            # Check scope overlap (if scope_check enabled)
            if self.config.get("dispatch", {}).get("scope_check", True):
                conflict = self._check_scope_conflict(ticket, data)
                if conflict:
                    return False, f"Ticket `{ticket_id}` file scope conflicts with running ticket `{conflict}`."

            if fallback_reason:
                update_ticket_fields(
                    self.paths["queue"],
                    ticket_id,
                    {
                        "_dispatch_owner": resolved_owner,
                        "_original_impl_owner": ticket.get("_original_impl_owner", target_owner),
                        "_fallback_reason": fallback_reason,
                    },
                )

            # Dispatch
            update_ticket_status(self.paths["queue"], ticket_id, "doing")
            runtime_ticket = self._build_runtime_ticket(ticket, resolved_owner)
            thread = threading.Thread(
                target=self._run_agent,
                args=(runtime_ticket,),
                daemon=False,
            )
            self._threads[ticket_id] = thread
            thread.start()
            return True, f"Dispatched `{ticket_id}` to {resolved_owner}."

    def dispatch_all_todo(self) -> list[tuple[str, str]]:
        """
        Dispatch all tickets that are todo (deps satisfied).
        Blocks until all dispatched agents finish (required for CLI mode).
        Returns list of (ticket_id, message).
        """
        try:
            data = read_queue(self.paths["queue"])
        except ValidationError as exc:
            return [("QUEUE", f"ValidationError: {exc}")]
        results = []
        for ticket in data.get("tickets", []):
            if ticket.get("status") != "todo":
                continue
            ok, msg = self.dispatch(ticket["id"])
            results.append((ticket["id"], msg))
        self.wait_all()
        return results

    def wait_all(self) -> None:
        """Block until all running agent threads have finished."""
        while True:
            with self._state_lock:
                threads = list(self._threads.values())
            if not threads:
                return
            for thread in threads:
                thread.join()

    def get_running(self) -> list[str]:
        """Return list of currently running ticket IDs."""
        with self._state_lock:
            return list(self._running.keys())

    # ── Internal ─────────────────────────────────────────────────────────────

    def _is_agent_available(self, agent_name: str) -> bool:
        """Check if an agent is configured and available to run."""
        agent_cfg = self.agent_configs.get(agent_name, {})
        config_dir = agent_cfg.get("config_dir")
        if config_dir:
            # Agent requires a config directory (e.g. .claude-b) — check credentials exist
            creds = Path(config_dir) / ".claude.json"
            if not creds.exists():
                logger.info(f"{agent_name} not available: {creds} not found")
                return False
        return True

    def _resolve_agent(self, owner: str) -> tuple[str, str | None]:
        """Resolve agent, returning (owner, fallback_reason)."""
        if self._is_agent_available(owner):
            return owner, None
        fallback = self.agent_configs.get(owner, {}).get("fallback")
        if fallback:
            reason = f"{owner} unavailable"
            logger.warning(f"{owner} not available — falling back to {fallback}")
            return fallback, reason
        return owner, None

    def _check_deps(self, data: dict, deps: list[str]) -> list[str]:
        """Return list of unfinished dependency ticket IDs."""
        tickets_by_id = {t["id"]: t for t in data.get("tickets", [])}
        return [d for d in deps if tickets_by_id.get(d, {}).get("status") != "done"]

    def _check_scope_conflict(self, ticket: dict, data: dict) -> str | None:
        """Return conflicting ticket_id if file scope overlaps with a running ticket."""
        my_files = set(ticket.get("files", []))
        for running_id in list(self._running):
            running_ticket = next(
                (t for t in data.get("tickets", []) if t.get("id") == running_id), None
            )
            if not running_ticket:
                continue
            their_files = set(running_ticket.get("files", []))
            if my_files & their_files:
                return running_id
        return None

    def _build_runtime_ticket(self, ticket: dict, owner: str) -> dict:
        """Return an execution-local ticket copy with the resolved owner."""
        runtime_ticket = copy.deepcopy(ticket)
        runtime_ticket["owner"] = owner
        return runtime_ticket

    def _auto_chain_enabled(self) -> bool:
        """Return whether post-completion dispatch chaining is enabled."""
        return bool(self.config.get("dispatch", {}).get("auto_chain", False))

    def _dispatch_auto_chain_todo(self) -> list[tuple[str, str]]:
        """
        Dispatch todo tickets after a completion when auto_chain is enabled.

        This re-scans the queue so downstream tickets unlocked by a `done` status,
        and tickets previously skipped due to capacity, can start without manual re-run.
        """
        if not self._auto_chain_enabled():
            return []

        try:
            data = read_queue(self.paths["queue"])
        except ValidationError as exc:
            return [("QUEUE", f"ValidationError: {exc}")]
        results: list[tuple[str, str]] = []
        for ticket in data.get("tickets", []):
            if ticket.get("status") != "todo":
                continue
            if self._check_deps(data, ticket.get("deps", [])):
                continue

            ok, msg = self.dispatch(ticket["id"])
            results.append((ticket["id"], msg))
            if "At capacity" in msg:
                break

        return results

    def _run_agent(self, ticket: dict) -> None:
        """Run an agent for a ticket in a background thread."""
        ticket_id = ticket["id"]
        owner = ticket["owner"]
        agent_cfg = self.agent_configs.get(owner, {})
        mode = agent_cfg.get("mode", "subprocess")
        completed_done = False
        auto_chain_results: list[tuple[str, str]] = []

        logger.info(f"Starting {owner} for {ticket_id} (mode: {mode})")
        with self._state_lock:
            self._running[ticket_id] = None  # Mark as running

        try:
            if mode in ("subprocess", "pipe"):
                success = self._run_subprocess(ticket, agent_cfg)
            else:
                logger.error(f"Unknown mode {mode} for {owner}")
                success = False

            if not success:
                update_ticket_status(self.paths["queue"], ticket_id, "blocked")
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = f"[FAIL] {ticket_id} failed (marked blocked)\n{log_summary}"
                if self.notify:
                    asyncio.run(self._send_notify(msg))
                return

            # Agent succeeded — run gate pipeline
            gates_passed, gate_msg = self._run_gates(ticket)

            if gates_passed:
                update_ticket_status(self.paths["queue"], ticket_id, "done")
                completed_done = True
                log_summary = self._get_agent_log(owner, ticket_id)
                msg = f"[DONE] {ticket_id} completed by {owner} (gates passed)\n{log_summary}"
            else:
                # Gates failed — attempt retry
                logger.warning(f"Gates failed for {ticket_id}: {gate_msg}")
                retry_success = self._attempt_retry(ticket, gate_msg)

                if retry_success:
                    # Re-run gates after retry
                    gates_passed_2, gate_msg_2 = self._run_gates(ticket)
                    if gates_passed_2:
                        update_ticket_status(self.paths["queue"], ticket_id, "done")
                        completed_done = True
                        msg = f"[DONE] {ticket_id} completed by {owner} (passed after retry)\n{gate_msg_2}"
                    else:
                        update_ticket_status(self.paths["queue"], ticket_id, "blocked")
                        msg = f"[BLOCKED] {ticket_id} gates still failing after retry: {gate_msg_2}"
                else:
                    update_ticket_status(self.paths["queue"], ticket_id, "blocked")
                    msg = f"[BLOCKED] {ticket_id} gates failed: {gate_msg}"

            if self.notify:
                asyncio.run(self._send_notify(msg))

        except Exception as e:
            logger.exception(f"Error running {owner} for {ticket_id}: {e}")
            update_ticket_status(self.paths["queue"], ticket_id, "blocked")
            if self.notify:
                asyncio.run(self._send_notify(f"❌ `{ticket_id}` error: {e}"))
        finally:
            with self._state_lock:
                self._running.pop(ticket_id, None)
                self._threads.pop(ticket_id, None)
            if completed_done:
                auto_chain_results = self._dispatch_auto_chain_todo()
                if auto_chain_results:
                    auto_chain_lines = "\n".join(
                        f"- {downstream_id}: {downstream_msg}"
                        for downstream_id, downstream_msg in auto_chain_results
                    )
                    logger.info(f"Auto-chain results after {ticket_id}:\n{auto_chain_lines}")

    def _build_prompt(self, ticket: dict) -> str:
        """Build the prompt string for an agent.

        Note: Agent instructions (CLAUDE.md) are loaded automatically by
        claude -p via CLAUDE_CONFIG_DIR. We only pass the ticket here.
        """
        return f"""Work on this ticket:

```yaml
{self._ticket_to_yaml(ticket)}
```

After completing:
1. Run the verify command in the ticket
2. Write a session log to devos/logs/
3. Output the 4-line handoff format
"""

    def _ticket_to_yaml(self, ticket: dict) -> str:
        import yaml
        return yaml.dump(ticket, allow_unicode=True)

    def _run_subprocess(self, ticket: dict, agent_cfg: dict) -> bool:
        """Run agent as subprocess (Claude 2 or Codex)."""
        command = agent_cfg.get("command", ["claude", "-p"])
        timeout = agent_cfg.get("timeout", 600)
        env = {**os.environ, **agent_cfg.get("env", {})}

        # Set config dir for Claude 2
        config_dir = agent_cfg.get("config_dir")
        if config_dir:
            env["CLAUDE_CONFIG_DIR"] = config_dir

        prompt = self._build_prompt(ticket)

        try:
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=str(self.paths["root"]),
            )
            if result.returncode != 0:
                logger.error(f"Agent failed: {result.stderr[:500]}")
                return False
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"Agent timed out after {timeout}s")
            return False

    # ── Gate Pipeline ─────────────────────────────────────────────────────────

    def _resolve_gates(self, ticket: dict) -> list[dict]:
        """Resolve gates for a ticket: ticket-level gates override defaults."""
        ticket_gates = ticket.get("gates")
        if ticket_gates:
            return ticket_gates

        # Use defaults from os2.yaml
        gates_config = self.config.get("gates", {})
        gates = list(gates_config.get("defaults", []))

        # Add tag-based gates
        tags = ticket.get("tags", [])
        by_tag = gates_config.get("by_tag", {})
        for tag in tags:
            if tag in by_tag:
                gates.extend(by_tag[tag])

        return gates

    def _run_command_gate(self, gate: dict) -> tuple[bool, str]:
        """Run a command gate (e.g. make test). Returns (passed, output)."""
        cmd = gate.get("run", "")
        if not cmd:
            return True, "no command"

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=gate.get("timeout", 120),
                cwd=str(self.paths["root"]),
            )
            if result.returncode == 0:
                return True, result.stdout[-500:] if result.stdout else "ok"
            return False, (result.stderr or result.stdout)[-500:]
        except subprocess.TimeoutExpired:
            return False, f"gate timed out after {gate.get('timeout', 120)}s"

    def _run_agent_review(self, ticket: dict) -> tuple[bool, str]:
        """Run agent-review gate: Claude 1 reviews diff against DOD."""
        review_cfg = self.config.get("gates", {}).get("agent_review", {})
        max_diff = review_cfg.get("max_diff_lines", 500)

        # Get git diff for the ticket's files
        files = ticket.get("files", [])
        diff_cmd = ["git", "diff", "HEAD~1", "--"] + files if files else ["git", "diff", "HEAD~1"]
        try:
            diff_result = subprocess.run(
                diff_cmd,
                capture_output=True, text=True, timeout=30,
                cwd=str(self.paths["root"]),
            )
            diff_text = diff_result.stdout
            if len(diff_text.splitlines()) > max_diff:
                diff_text = "\n".join(diff_text.splitlines()[:max_diff]) + "\n... (truncated)"
        except Exception:
            diff_text = "(could not get diff)"

        # Build review prompt
        import yaml
        dod = ticket.get("dod", [])
        review_prompt = f"""You are reviewing a completed ticket. Check if the diff satisfies the DOD.

## Ticket
```yaml
{yaml.dump(ticket, allow_unicode=True)}
```

## DOD Checklist
{chr(10).join(f'- [ ] {item}' for item in dod)}

## Diff
```diff
{diff_text}
```

Respond with EXACTLY one of:
- PASS: <one-line summary>
- FAIL: <what's missing or wrong>
"""

        try:
            result = subprocess.run(
                ["claude", "-p"],
                input=review_prompt,
                capture_output=True, text=True,
                timeout=review_cfg.get("timeout", 120),
                cwd=str(self.paths["root"]),
            )
            if result.returncode != 0:
                error_output = (result.stderr or result.stdout or "agent review command failed").strip()
                return False, error_output[-500:]

            response = result.stdout.strip()
            ansi_pattern = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
            verdict_pattern = re.compile(r"(?im)^[^\S\r\n]*(PASS|FAIL):[^\n\r]*")

            cleaned_response = ansi_pattern.sub("", response)
            verdict_match = verdict_pattern.search(cleaned_response)
            if verdict_match:
                verdict_line = verdict_match.group(0).strip()
                return verdict_line.upper().startswith("PASS:"), verdict_line

            preview = cleaned_response.replace("\r", " ").replace("\n", " ").strip()
            preview = preview[:200] if preview else "(empty response)"
            return False, f"no verdict in response: {preview}"
        except subprocess.TimeoutExpired:
            return False, "agent review timed out"
        except FileNotFoundError:
            logger.warning("claude CLI not found for agent-review gate, skipping")
            return True, "skipped (claude not found)"

    def _run_ticket_verify(self, ticket: dict) -> tuple[bool, str]:
        """Run ticket-level verify command(s). Returns (passed, message)."""
        verify = ticket.get("verify")
        if not verify:
            return True, "skipped (no verify)"

        commands = verify if isinstance(verify, list) else [verify]
        timeout = self.config.get("gates", {}).get("verify_timeout", 120)

        for raw_cmd in commands:
            cmd = str(raw_cmd).strip()
            if not cmd:
                continue

            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(self.paths["root"]),
                )
            except subprocess.TimeoutExpired as exc:
                output = ((exc.stderr or "") + (exc.stdout or "")).strip() or "(no output)"
                return False, f"verify failed: {cmd}\n{output}\n(timed out after {timeout}s)"

            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            output = (stderr or stdout) or "(no output)"
            if result.returncode != 0:
                return False, f"verify failed: {cmd}\n{output}"
            if "wc -l" in cmd and stdout.isdigit() and int(stdout) != 0:
                return False, f"verify failed: {cmd}\n{stdout}"

        return True, "verify passed"

    def _run_gates(self, ticket: dict) -> tuple[bool, str]:
        """Run the full gate pipeline. Returns (all_passed, failure_message)."""
        gates = self._resolve_gates(ticket)
        for gate in gates:
            gate_name = gate.get("name", "unnamed")
            logger.info(f"Running gate '{gate_name}' for {ticket['id']}")

            if gate.get("type") == "agent-review":
                passed, msg = self._run_agent_review(ticket)
            else:
                passed, msg = self._run_command_gate(gate)

            if not passed:
                logger.warning(f"Gate '{gate_name}' failed for {ticket['id']}: {msg}")
                return False, f"{gate_name}: {msg}"

            logger.info(f"Gate '{gate_name}' passed for {ticket['id']}")

        logger.info(f"Running gate 'verify' for {ticket['id']}")
        verify_passed, verify_msg = self._run_ticket_verify(ticket)
        if not verify_passed:
            logger.warning(f"Gate 'verify' failed for {ticket['id']}: {verify_msg}")
            return False, f"verify: {verify_msg}"
        logger.info(f"Gate 'verify' passed for {ticket['id']}: {verify_msg}")

        if not gates and not ticket.get("verify"):
            return True, "no gates configured"

        return True, "all gates passed"

    def _rollback_retry_files(self, ticket_id: str, files: list[str]) -> bool:
        """Restore retry scope files to HEAD and confirm they are clean."""
        if not files:
            return True

        root = str(self.paths["root"])
        failed_files: list[str] = []

        for file_path in files:
            tracked_cmd = ["git", "ls-files", "--error-unmatch", "--", file_path]
            try:
                tracked_result = subprocess.run(
                    tracked_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=root,
                )
            except (subprocess.TimeoutExpired, Exception) as exc:
                logger.error(f"Rollback failed for {ticket_id} on {file_path}: {exc}")
                failed_files.append(file_path)
                continue

            target_path = Path(root) / file_path
            if tracked_result.returncode == 0:
                rollback_cmd = ["git", "restore", "--worktree", "--source=HEAD", "--", file_path]
            elif target_path.exists():
                rollback_cmd = ["git", "clean", "-f", "--", file_path]
            else:
                continue

            try:
                rollback_result = subprocess.run(
                    rollback_cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=root,
                )
            except (subprocess.TimeoutExpired, Exception) as exc:
                logger.error(f"Rollback failed for {ticket_id} on {file_path}: {exc}")
                failed_files.append(file_path)
                continue

            if rollback_result.returncode != 0:
                error_output = (
                    rollback_result.stderr
                    or rollback_result.stdout
                    or f"{rollback_cmd[1]} failed"
                ).strip()
                logger.error(f"Rollback failed for {ticket_id} on {file_path}: {error_output}")
                failed_files.append(file_path)

        status_cmd = ["git", "status", "--short", "--", *files]
        try:
            status_result = subprocess.run(
                status_cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=root,
            )
        except (subprocess.TimeoutExpired, Exception) as exc:
            logger.error(f"Rollback status check failed for {ticket_id}: {exc}")
            return False

        if status_result.returncode != 0:
            error_output = (status_result.stderr or status_result.stdout or "git status failed").strip()
            logger.error(f"Rollback status check failed for {ticket_id}: {error_output}")
            return False

        remaining = status_result.stdout.strip()
        if remaining:
            logger.error(f"Rollback left scope dirty for {ticket_id}: {remaining}")
            for line in remaining.splitlines():
                dirty_path = line[3:].strip()
                if dirty_path and dirty_path not in failed_files:
                    failed_files.append(dirty_path)

        if failed_files:
            logger.error(
                "Rollback incomplete for %s; failed files: %s",
                ticket_id,
                ", ".join(failed_files),
            )
            return False

        return True

    def _get_max_retries_for_ticket(self, ticket: dict) -> int:
        """Resolve retry limit using retry_policy with max_retries fallback."""
        retry_cfg = self.config.get("gates", {}).get("auto_retry", {})
        default_max_retries = retry_cfg.get("max_retries", 1)
        priority = ticket.get("priority")
        if not priority:
            return default_max_retries

        retry_policy = retry_cfg.get("retry_policy", {})
        priority_limit = retry_policy.get(priority)
        if priority_limit is None:
            return default_max_retries

        try:
            return int(priority_limit)
        except (TypeError, ValueError):
            logger.warning(
                "Invalid retry_policy for priority '%s': %r; using default max_retries=%s",
                priority,
                priority_limit,
                default_max_retries,
            )
            return default_max_retries

    def _attempt_retry(self, ticket: dict, gate_output: str) -> bool:
        """Re-dispatch builder with gate failure context. Returns success."""
        retry_cfg = self.config.get("gates", {}).get("auto_retry", {})
        if not retry_cfg.get("enabled", False):
            return False

        ticket_id = ticket["id"]
        max_retries = self._get_max_retries_for_ticket(ticket)

        # Track retries via ticket metadata
        retries = ticket.get("_retries", 0)
        if retries >= max_retries:
            logger.info(f"Max retries ({max_retries}) reached for {ticket_id}")
            return False

        # Get diff for context
        files = ticket.get("files", [])
        diff_cmd = ["git", "diff", "HEAD~1", "--"] + files if files else ["git", "diff", "HEAD~1"]
        try:
            diff_result = subprocess.run(
                diff_cmd, capture_output=True, text=True, timeout=30,
                cwd=str(self.paths["root"]),
            )
            diff_text = diff_result.stdout[-3000:]
        except Exception:
            diff_text = "(could not get diff)"

        retry_ticket = copy.deepcopy(ticket)
        retry_ticket["_retries"] = retries + 1

        owner = retry_ticket["owner"]
        agent_cfg = self.agent_configs.get(owner, {})

        logger.info(f"Retrying {ticket_id} (attempt {retries + 1}/{max_retries})")

        if not self._rollback_retry_files(ticket_id, files):
            logger.error(f"Retry aborted for {ticket_id}: rollback failed")
            return False

        # Build retry prompt with gate context
        import yaml
        retry_prompt = f"""Your previous attempt on this ticket failed gate checks. Fix the issues.

## Gate Failure
{gate_output}

## Your Previous Diff
```diff
{diff_text}
```

## Original Ticket
```yaml
{yaml.dump(retry_ticket, allow_unicode=True)}
```

이전 시도의 변경은 롤백됨, 원본 코드 기준으로 작업.

Fix the issues identified in the gate failure, then:
1. Run the verify command in the ticket
2. Write a session log to devos/logs/
3. Output the 4-line handoff format
"""

        # Run the agent with retry prompt
        mode = agent_cfg.get("mode", "subprocess")
        if mode in ("subprocess", "pipe"):
            command = agent_cfg.get("command", ["claude", "-p"])
            timeout = agent_cfg.get("timeout", 600)
            env = {**os.environ, **agent_cfg.get("env", {})}
            config_dir = agent_cfg.get("config_dir")
            if config_dir:
                env["CLAUDE_CONFIG_DIR"] = config_dir

            try:
                result = subprocess.run(
                    command, input=retry_prompt,
                    capture_output=True, text=True,
                    timeout=timeout, env=env,
                    cwd=str(self.paths["root"]),
                )
                return result.returncode == 0
            except (subprocess.TimeoutExpired, Exception) as e:
                logger.error(f"Retry failed for {ticket_id}: {e}")
                return False
        else:
            logger.warning(f"Retry not supported for mode '{mode}'")
            return False

    def _get_agent_log(self, owner: str, ticket_id: str) -> str:
        """Get summary from the agent's session log."""
        import re
        logs_path = self.paths["logs"]
        agent_name = owner.lower().replace("1", "1").replace("2", "2")
        # Find most recent log for this agent/ticket
        recent = get_recent_logs(logs_path, limit=10)
        for log_file in recent:
            if agent_name in log_file.name.lower() and ticket_id in log_file.name:
                content = log_file.read_text()
                match = re.search(r"## Summary\n(.*?)(?=\n##|\Z)", content, re.DOTALL)
                if match:
                    return match.group(1).strip()[:200]
        return ""

    async def _send_notify(self, message: str) -> None:
        """Send notification via callback."""
        if self.notify:
            try:
                await self.notify(message)
            except Exception as e:
                logger.error(f"Failed to send notification: {e}")
