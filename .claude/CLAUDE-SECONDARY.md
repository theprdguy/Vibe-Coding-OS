# Claude Secondary — Role TBD

> This instruction file is for the second Claude Code instance.
> Activate in `devos/agents/registry.yaml` when role is determined.

---

## STATUS: INACTIVE

This agent is not yet configured. Choose a role before activating.

---

## ROLE OPTIONS

### Option A: Dedicated Reviewer
- **Focus:** PR review, code quality, architecture compliance
- **Capabilities:** code-review, verification-before-completion
- **Can modify:** `devos/logs/**`, `devos/questions/**`
- **Cannot modify:** Implementation code, SSOT state files
- **Skills:** `requesting-code-review`, `verification-before-completion`

### Option B: QA / TDD Agent
- **Focus:** Test writing, test-driven development, quality assurance
- **Capabilities:** TDD, testing, QA verification
- **Can modify:** `tests/**`, `devos/logs/**`
- **Cannot modify:** Implementation source code (only tests)
- **Skills:** `test-driven-development`, `systematic-debugging`

### Option C: Second Dispatcher
- **Focus:** Manages a separate workstream (different feature area)
- **Capabilities:** planning, triage, ticket-creation
- **Can modify:** `devos/**` (with workstream isolation)
- **Conflict prevention:** Must work on different ticket ID ranges than primary dispatcher

---

## BOOT SEQUENCE (when activated)

Same as primary Claude, plus:
1. Read `devos/agents/registry.yaml` (find your role and scope)
2. Read `devos/logs/` (latest session logs)
3. Follow role-specific instructions above

---

## ACTIVATION CHECKLIST

1. [ ] Choose role (A/B/C above)
2. [ ] Update `devos/agents/registry.yaml`: set role, capabilities, can_modify, status: active
3. [ ] Update this file with role-specific rules
4. [ ] Start Claude Code with this instruction file
