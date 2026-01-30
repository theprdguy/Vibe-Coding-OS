SHELL := /bin/bash
.DEFAULT_GOAL := help
BASE_REF ?= origin/main
CMD ?= ""

.PHONY: help setup dev lint format test typecheck e2e clean status queue questions contract-check pr-check kickoff triage run

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Project setup (placeholder). Replace with real install commands later.
	@echo "TODO: wire setup once stack is chosen."
	@echo "Examples: pnpm i | npm i | pip install -r requirements.txt | uv sync"

dev: ## Run dev server (placeholder). Use CMD="..." to run actual command
	@if [ -n "$(CMD)" ]; then echo "Running: $(CMD)"; eval "$(CMD)"; else echo "TODO: make dev CMD='pnpm dev'"; fi

lint: ## Run linter (placeholder). Use CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make lint CMD='pnpm lint'"; fi

format: ## Run formatter (placeholder). Use CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make format CMD='pnpm format'"; fi

test: ## Run tests (placeholder). Use CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make test CMD='pnpm test'"; fi

typecheck: ## Run typecheck (placeholder). Use CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make typecheck CMD='pnpm typecheck'"; fi

e2e: ## Run e2e tests (placeholder). Use CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "TODO: make e2e CMD='pnpm e2e'"; fi

clean: ## Clean artifacts (placeholder)
	@echo "TODO: clean caches/build outputs"

status: ## Quick status (git + SSOT pointers)
	@echo "== git =="
	@git status -sb 2>/dev/null || true
	@echo ""
	@echo "== SSOT =="
	@ls -1 AI.md CONTEXT.md PROJECT_STATE.md TASKS.md docs/API_CONTRACT.md docs/UI_CONTRACT.md 2>/dev/null || true
	@echo ""

queue: ## Show current ticket queue
	@echo "== tasks/QUEUE.yaml =="
	@sed -n '1,220p' tasks/QUEUE.yaml 2>/dev/null || echo "(missing) tasks/QUEUE.yaml"
	@echo ""

questions: ## Show question queue
	@echo "== questions/QUEUE.md =="
	@sed -n '1,260p' questions/QUEUE.md 2>/dev/null || echo "(missing) questions/QUEUE.md"
	@echo ""

contract-check: ## Fail if api/ui code changed without updating contract docs (uses BASE_REF)
	@echo "Checking contract updates against: $(BASE_REF)"
	@set -e; \
	if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		echo "Not a git repo. Skipping."; exit 0; \
	fi; \
	CHANGED=$$(git diff --name-only $(BASE_REF)...HEAD 2>/dev/null || true); \
	if [ -z "$$CHANGED" ]; then echo "No changes detected (or BASE_REF not found)."; exit 0; fi; \
	API_CHANGED=$$(echo "$$CHANGED" | grep -E '^apps/api/' || true); \
	WEB_CHANGED=$$(echo "$$CHANGED" | grep -E '^apps/web/' || true); \
	API_CONTRACT_CHANGED=$$(echo "$$CHANGED" | grep -E '^docs/API_CONTRACT.md$$' || true); \
	UI_CONTRACT_CHANGED=$$(echo "$$CHANGED" | grep -E '^docs/UI_CONTRACT.md$$' || true); \
	if [ -n "$$API_CHANGED" ] && [ -z "$$API_CONTRACT_CHANGED" ]; then \
		echo "ERROR: apps/api changed but docs/API_CONTRACT.md not updated"; \
		exit 1; \
	fi; \
	if [ -n "$$WEB_CHANGED" ] && [ -z "$$UI_CONTRACT_CHANGED" ]; then \
		echo "ERROR: apps/web changed but docs/UI_CONTRACT.md not updated"; \
		exit 1; \
	fi; \
	echo "OK: contract-check passed."

pr-check: contract-check ## Standard pre-PR checks (expand later)
	@echo "OK: pr-check done (wire lint/test/typecheck/e2e once stack is chosen)."

kickoff: ## Session start: status + queue + questions
	@echo "== SESSION KICKOFF =="
	@$(MAKE) status
	@$(MAKE) queue
	@$(MAKE) questions
	@echo ""
	@echo "Next: Run Claude (Dispatcher) session-start triage on OPEN questions."

triage: ## Show only OPEN questions
	@echo "== OPEN QUESTIONS =="
	@awk 'BEGIN{p=0} /^## Q-/{p=0} /^## Q-.*\\[open\\]/{p=1} {if(p) print}' questions/QUEUE.md 2>/dev/null || echo "(missing) questions/QUEUE.md"

run: ## Convenience: run any shell command via CMD="..."
	@if [ -n "$(CMD)" ]; then eval "$(CMD)"; else echo "Usage: make run CMD='echo hello'"; fi


session-start: ## Print Claude session-start prompt path
	@echo "Use Claude prompt: prompts/claude/session-start.md"
	@echo "Run: make kickoff && make triage"

pr-review: ## Print Claude PR review prompt path
	@echo "Use Claude prompt: prompts/claude/review-pr.md"


codex-start: ## Print Codex runbook prompt path
	@echo "Use Codex prompt: prompts/codex/session-start.md"

gemini-start: ## Print Gemini runbook prompt path
	@echo "Use Gemini prompt: prompts/gemini/session-start.md"

handoff: ## Print handoff template path
	@echo "Use handoff template: prompts/common/handoff-3lines.md"
