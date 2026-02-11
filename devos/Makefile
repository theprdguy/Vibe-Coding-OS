SHELL := /bin/bash
.DEFAULT_GOAL := help
BASE_REF ?= origin/main
CMD ?= ""
DEVOS := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))

.PHONY: help start status queue questions triage pr-check contract-check \
        copy-claude copy-codex copy-gemini show-claude show-codex show-gemini \
        setup dev lint format test typecheck e2e clean run new-ticket new-question

# ─── Core (daily use) ─────────────────────────────────────

help: ## Show available commands
	@echo ""
	@echo "  Vibe Coding OS v1.5"
	@echo "  ────────────────────────────"
	@echo ""
	@echo "  Daily:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*Daily' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "    \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Prompts:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*Prompt' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "    \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Verify:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*Verify' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "    \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Build (wire once stack chosen):"
	@grep -E '^[a-zA-Z_-]+:.*?## .*Build' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "    \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

start: ## [Daily] Session start: status + queue + questions + next steps
	@echo ""
	@echo "╔══════════════════════════════════════╗"
	@echo "║    Vibe Coding OS — Session Start    ║"
	@echo "╚══════════════════════════════════════╝"
	@echo ""
	@$(MAKE) --no-print-directory status
	@$(MAKE) --no-print-directory queue
	@$(MAKE) --no-print-directory triage
	@echo ""
	@echo "── Next Steps ──────────────────────────"
	@echo "  1. Claude triage:  make copy-claude  (or make show-claude)"
	@echo "  2. Start builders: make copy-codex   / make copy-gemini"
	@echo "  3. Before PR:      make pr-check"
	@echo ""

status: ## [Daily] Git status + SSOT file check
	@echo "── Git ──"
	@git status -sb 2>/dev/null || echo "(not a git repo)"
	@echo ""
	@echo "── SSOT Files ──"
	@for f in AI.md CONTEXT.md PROJECT_STATE.md TASKS.md docs/API_CONTRACT.md docs/UI_CONTRACT.md tasks/QUEUE.yaml questions/QUEUE.md; do \
		if [ -f "$$f" ]; then echo "  ✓ $$f"; else echo "  ✗ $$f (missing)"; fi; \
	done
	@echo ""

queue: ## [Daily] Show ticket queue summary
	@echo "── Ticket Queue ──"
	@if [ -f tasks/QUEUE.yaml ]; then \
		echo "  Sprint: $$(head -1 tasks/QUEUE.yaml | sed 's/sprint_goal: //' | tr -d '\"')"; \
		echo ""; \
		grep -E '^\s+- id:|^\s+status:|^\s+owner:|^\s+goal:' tasks/QUEUE.yaml 2>/dev/null | \
		paste - - - - | \
		awk '{gsub(/\s+- id: /,"  "); gsub(/\s+status: /," ["); gsub(/\s+owner: /,"] "); gsub(/\s+goal: /," — "); print}' || true; \
	else \
		echo "  (missing) tasks/QUEUE.yaml"; \
	fi
	@echo ""

triage: ## [Daily] Show OPEN questions only
	@echo "── Open Questions ──"
	@if [ -f questions/QUEUE.md ]; then \
		awk 'BEGIN{p=0} /^## Q-/{p=0} /^## Q-.*\[open\]/{p=1} {if(p) print "  " $$0}' questions/QUEUE.md; \
		OPEN_COUNT=$$(grep -c '\[open\]' questions/QUEUE.md 2>/dev/null || echo 0); \
		echo ""; \
		echo "  Total open: $$OPEN_COUNT"; \
	else \
		echo "  (missing) questions/QUEUE.md"; \
	fi
	@echo ""

# ─── Prompt Delivery ──────────────────────────────────────

copy-claude: ## [Prompt] Copy Claude triage prompt to clipboard
	@cat prompts/claude/session-start.md | pbcopy 2>/dev/null && \
		echo "✓ Claude prompt copied to clipboard" || \
		$(MAKE) --no-print-directory show-claude

copy-codex: ## [Prompt] Copy Codex builder prompt to clipboard
	@cat prompts/codex/session-start.md | pbcopy 2>/dev/null && \
		echo "✓ Codex prompt copied to clipboard" || \
		$(MAKE) --no-print-directory show-codex

copy-gemini: ## [Prompt] Copy Gemini builder prompt to clipboard
	@cat prompts/gemini/session-start.md | pbcopy 2>/dev/null && \
		echo "✓ Gemini prompt copied to clipboard" || \
		$(MAKE) --no-print-directory show-gemini

show-claude: ## [Prompt] Print Claude triage prompt
	@echo "── Claude Session-Start Prompt ──"
	@cat prompts/claude/session-start.md 2>/dev/null || echo "(missing) prompts/claude/session-start.md"

show-codex: ## [Prompt] Print Codex builder prompt
	@echo "── Codex Session-Start Prompt ──"
	@cat prompts/codex/session-start.md 2>/dev/null || echo "(missing) prompts/codex/session-start.md"

show-gemini: ## [Prompt] Print Gemini builder prompt
	@echo "── Gemini Session-Start Prompt ──"
	@cat prompts/gemini/session-start.md 2>/dev/null || echo "(missing) prompts/gemini/session-start.md"

# ─── Verification ─────────────────────────────────────────

contract-check: ## [Verify] Fail if code changed without updating contracts
	@echo "Checking contracts against: $(BASE_REF)"
	@set -e; \
	if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "Not a git repo. Skipping."; exit 0; \
	fi; \
	CHANGED=$$(git diff --name-only $(BASE_REF)...HEAD 2>/dev/null || true); \
	if [ -z "$$CHANGED" ]; then echo "No changes detected."; exit 0; fi; \
	API_CHANGED=$$(echo "$$CHANGED" | grep -E '^apps/api/|^src/api/|^backend/' || true); \
	WEB_CHANGED=$$(echo "$$CHANGED" | grep -E '^apps/web/|^src/|^frontend/|^components/' || true); \
	API_CONTRACT=$$(echo "$$CHANGED" | grep -E 'API_CONTRACT' || true); \
	UI_CONTRACT=$$(echo "$$CHANGED" | grep -E 'UI_CONTRACT' || true); \
	if [ -n "$$API_CHANGED" ] && [ -z "$$API_CONTRACT" ]; then \
		echo "ERROR: API code changed but API_CONTRACT.md not updated"; exit 1; \
	fi; \
	if [ -n "$$WEB_CHANGED" ] && [ -z "$$UI_CONTRACT" ]; then \
		echo "ERROR: UI code changed but UI_CONTRACT.md not updated"; exit 1; \
	fi; \
	echo "✓ contract-check passed"

pr-check: contract-check ## [Verify] Pre-PR checks (expand once stack chosen)
	@echo "✓ pr-check passed (wire lint/test/typecheck/e2e once stack is chosen)"

# ─── Build Commands (placeholder) ─────────────────────────

setup: ## [Build] Project setup (placeholder)
	@echo "TODO: wire setup — e.g., pnpm i | npm i | pip install"

dev: ## [Build] Dev server (placeholder). CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make dev CMD='pnpm dev'"; fi

lint: ## [Build] Linter (placeholder). CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make lint CMD='pnpm lint'"; fi

format: ## [Build] Formatter (placeholder). CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make format CMD='pnpm format'"; fi

test: ## [Build] Tests (placeholder). CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make test CMD='pnpm test'"; fi

typecheck: ## [Build] Typecheck (placeholder). CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make typecheck CMD='pnpm typecheck'"; fi

e2e: ## [Build] E2E tests (placeholder). CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make e2e CMD='pnpm e2e'"; fi

clean: ## [Build] Clean artifacts (placeholder)
	@echo "TODO: clean caches/build outputs"

# ─── Utilities ────────────────────────────────────────────

run: ## Run any command via CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "Usage: make run CMD='echo hello'"; fi

new-ticket: ## Create a new ticket template
	@echo ""
	@echo "Add this to devos/tasks/QUEUE.yaml under tickets:"
	@echo ""
	@echo '  - id: T-XXX'
	@echo '    status: todo'
	@echo '    owner: CODEX|GEMINI'
	@echo '    goal: "What to build (1 sentence)"'
	@echo '    context: |'
	@echo '      Why it is needed, current state (2-3 sentences)'
	@echo '    spec: |'
	@echo '      Detailed requirements'
	@echo '    dod:'
	@echo '      - "Acceptance criteria"'
	@echo '    files:'
	@echo '      - "file path"'
	@echo '    verify:'
	@echo '      - "make pr-check"'
	@echo '    contract_impact: none|api|ui|both'
	@echo '    deps: []'
	@echo ""

new-question: ## Create a new question template
	@echo ""
	@echo "Add this to devos/questions/QUEUE.md:"
	@echo ""
	@echo '## Q-XXX [open] (Blocking|Non-blocking)'
	@echo '**Question:** ...'
	@echo '**Options:** A) ... B) ... C) ...'
	@echo '**Recommendation:** ...'
	@echo '**Default:** A'
	@echo '**Needed-by:** T-XXX'
	@echo '**Impact:** none|API_CONTRACT|UI_CONTRACT'
	@echo ""

# Legacy aliases
kickoff: start ## (alias for start)
questions: triage ## (alias for triage)
session-start: copy-claude ## (alias)
codex-start: copy-codex ## (alias)
gemini-start: copy-gemini ## (alias)
