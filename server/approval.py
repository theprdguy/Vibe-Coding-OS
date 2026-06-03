"""Approval workflow state machine for deos server."""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

import yaml

from .ssot import approve_plan, format_plan_summary, list_pending_plans, read_plan, reject_plan


class ApprovalManager:
    """Manages the plan approval workflow."""

    def __init__(self, plans_path: Path, queue_path: Path):
        self.plans_path = plans_path
        self.queue_path = queue_path
        self.pending_path = plans_path / "pending"
        self.pending_path.mkdir(parents=True, exist_ok=True)

    def save_pending_plan(self, tickets: list[dict], source: str = "PRD") -> str:
        """Save a new plan to pending/ and return plan_id."""
        plan_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + str(uuid.uuid4())[:8]
        plan = {
            "id": plan_id,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "status": "pending",
            "tickets": tickets,
        }
        plan_file = self.pending_path / f"{plan_id}.yaml"
        with open(plan_file, "w") as f:
            yaml.dump(plan, f, allow_unicode=True, sort_keys=False)
        return plan_id

    def get_pending_plans(self) -> list[tuple[str, dict]]:
        """Return list of (plan_id, plan) for all pending plans."""
        result = []
        for plan_file in list_pending_plans(self.plans_path):
            plan = read_plan(plan_file)
            result.append((plan.get("id", plan_file.stem), plan))
        return result

    def get_latest_pending(self) -> tuple[str, dict] | None:
        """Return the most recent pending plan, or None."""
        pending = self.get_pending_plans()
        if not pending:
            return None
        return pending[-1]  # sorted by name = by time

    def approve(self, plan_id: str | None = None) -> tuple[bool, str]:
        """
        Approve a plan. If plan_id is None, approves the latest pending plan.
        Returns (success, message).
        """
        if plan_id is None:
            latest = self.get_latest_pending()
            if not latest:
                return False, "No pending plans to approve."
            plan_id, _ = latest

        success = approve_plan(self.plans_path, plan_id, self.queue_path)
        if success:
            return True, f"Plan `{plan_id}` approved. Tickets added to queue."
        return False, f"Plan `{plan_id}` not found in pending."

    def reject(self, reason: str, plan_id: str | None = None) -> tuple[bool, str]:
        """
        Reject a plan with a reason. If plan_id is None, rejects the latest pending plan.
        Returns (success, message).
        """
        if plan_id is None:
            latest = self.get_latest_pending()
            if not latest:
                return False, "No pending plans to reject."
            plan_id, _ = latest

        success = reject_plan(self.plans_path, plan_id, reason)
        if success:
            return True, f"Plan `{plan_id}` rejected. Claude 1 will revise with feedback: _{reason}_"
        return False, f"Plan `{plan_id}` not found in pending."

    def format_pending_summary(self) -> str:
        """Format all pending plans as a readable summary."""
        pending = self.get_pending_plans()
        if not pending:
            return "No plans pending approval."
        _, plan = pending[-1]  # Show latest
        return format_plan_summary(plan)
