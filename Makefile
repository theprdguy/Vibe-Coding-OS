# os2 Makefile
# Usage: make <target>

.PHONY: start stop restart ps handoff pickup server status queue logs pending dispatch dispatch-all approve reject test test-queue-schema scan-secrets security-check check-tdd-first-commit pr-check install setup help

PID_FILE := .os2-server.pid
LOG_FILE := $(shell .venv/bin/python3 -c 'from pathlib import Path; import yaml; default = ".os2-server.log"; path = Path("os2.yaml"); config = yaml.safe_load(path.read_text()) if path.exists() else {}; print((((config or {}).get("server") or {}).get("log_file")) or default)')

# ── Server 시작/종료 ──────────────────────────────────────────────────────────

## 서버 시작 (백그라운드)
start:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "이미 실행 중 (PID: $$(cat $(PID_FILE)))"; \
	else \
		echo "Log file: $(LOG_FILE)"; \
		.venv/bin/python3 -m server >> $(LOG_FILE) 2>&1 & echo $$! > $(PID_FILE); \
		echo "os2-server 시작 (PID: $$(cat $(PID_FILE)), 로그: $(LOG_FILE))"; \
	fi

## 서버 종료
stop:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		kill $$(cat $(PID_FILE)) && rm -f $(PID_FILE); \
		echo "os2-server 종료 완료"; \
	else \
		echo "실행 중인 서버 없음"; rm -f $(PID_FILE); \
	fi

## 서버 재시작
restart: stop start

## 서버 상태 확인
ps:
	@if [ -f $(PID_FILE) ] && kill -0 $$(cat $(PID_FILE)) 2>/dev/null; then \
		echo "실행 중 (PID: $$(cat $(PID_FILE)))"; \
	else \
		echo "중지됨"; \
	fi

## 서버 로그 실시간 보기
tail:
	@tail -f $(LOG_FILE)

# ── 두 컴퓨터 전환 ─────────────────────────────────────────────────────────────

## 이 컴에서 작업 마무리 후 다른 컴으로 넘기기 (stop → git push)
handoff:
	@make stop
	@git add -A && git diff --cached --quiet || git commit -m "handoff: $(shell date '+%Y-%m-%d %H:%M')"
	@git push
	@echo "핸드오프 완료. 다른 컴에서 'make pickup' 실행"

## 다른 컴에서 이어받기 (git pull → start)
pickup:
	@git pull
	@make start
	@echo "이어받기 완료"

## Install Python dependencies
install:
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

## Run first-time setup
setup:
	bash scripts/setup.sh

## 서브 컴 전용: launchd에 등록 (부팅 시 자동 시작)
install-daemon:
	@cp com.os2.server.plist ~/Library/LaunchAgents/
	@launchctl load ~/Library/LaunchAgents/com.os2.server.plist
	@echo "launchd 등록 완료 — 재부팅 후에도 자동 시작됩니다"

## 서브 컴 전용: launchd 해제
uninstall-daemon:
	@launchctl unload ~/Library/LaunchAgents/com.os2.server.plist
	@rm -f ~/Library/LaunchAgents/com.os2.server.plist
	@echo "launchd 해제 완료"

# ── Status queries (no LLM) ──────────────────────────────────────────────────

## Show current project status
status:
	@.venv/bin/python3 -m server status

## Show ticket queue
queue:
	@.venv/bin/python3 -m server queue

## Show recent session logs
logs:
	@.venv/bin/python3 -m server logs

## Show pending approval plans
pending:
	@.venv/bin/python3 -m server pending

# ── Approval ─────────────────────────────────────────────────────────────────

## Approve latest pending plan (or: make approve P=plan-id)
approve:
	@.venv/bin/python3 -m server approve $(P)

## Reject latest pending plan: make reject R="reason" [P=plan-id]
reject:
	@if [ -z "$(R)" ]; then echo "Usage: make reject R='reason' [P=plan-id]"; exit 1; fi
	@.venv/bin/python3 -m server reject "$(R)" $(P)

# ── Dispatch ─────────────────────────────────────────────────────────────────

## Dispatch a ticket: make dispatch T=T-001
dispatch:
	@if [ -z "$(T)" ]; then echo "Usage: make dispatch T=T-001"; exit 1; fi
	@.venv/bin/python3 -m server dispatch $(T)

## Dispatch all todo tickets
dispatch-all:
	@.venv/bin/python3 -m server dispatch-all

# ── Gates / Verification ─────────────────────────────────────────────────────

## Run tests (gate command — wire to your stack)
test:
	@echo "WARN test runner not wired for this stack yet"

## Run queue schema unit tests
test-queue-schema:
	@python3 -m pytest tests/unit/test_queue_schema.py -v

## Scan for secrets (gate command)
scan-secrets:
	@printf '[1/4] scan-secrets\n'
	@if ! command -v gitleaks >/dev/null 2>&1; then \
		echo "❌ FAIL scan-secrets: gitleaks not found. Install with: brew install gitleaks"; \
		exit 1; \
	fi
	@if gitleaks git --no-banner --redact .; then \
		echo "✅ PASS scan-secrets"; \
	else \
		echo "❌ FAIL scan-secrets"; \
		exit 1; \
	fi

## Run security checks (tag-based gate for auth tickets)
security-check:
	@bash scripts/check-contract-sync.sh
	@bash scripts/check-ticket-scope.sh
	@bash scripts/check-session-log.sh

## Enforce test-first on required TDD tickets
check-tdd-first-commit:
	@bash scripts/check-tdd-first-commit.sh

## Run all checks
pr-check:
	@status=0; \
	$(MAKE) --no-print-directory scan-secrets || status=1; \
	$(MAKE) --no-print-directory security-check || status=1; \
	$(MAKE) --no-print-directory check-tdd-first-commit || status=1; \
	if [ "$$status" -eq 0 ]; then \
		echo "All baseline gates passed"; \
	else \
		echo "Baseline gates failed"; \
		exit $$status; \
	fi

# ── Help ─────────────────────────────────────────────────────────────────────

help:
	@echo "os2 Agentic Coding OS v3.0"
	@echo ""
	@echo "Setup:"
	@echo "  make setup            최초 설정 자동화"
	@echo "  make install          Python 의존성 설치"
	@echo ""
	@echo "Server:"
	@echo "  make start            서버 시작 (백그라운드)"
	@echo "  make stop             서버 종료"
	@echo "  make restart          서버 재시작"
	@echo "  make ps               서버 상태 확인"
	@echo "  make tail             서버 로그 실시간"
	@echo ""
	@echo "컴퓨터 전환:"
	@echo "  make handoff          서버 종료 + git push"
	@echo "  make pickup           git pull + 서버 시작"
	@echo ""
	@echo "Status:"
	@echo "  make status           프로젝트 상태"
	@echo "  make queue            티켓 큐"
	@echo "  make logs             최근 세션 로그"
	@echo "  make pending          승인 대기 플랜"
	@echo ""
	@echo "Approval:"
	@echo "  make approve          최신 플랜 승인"
	@echo "  make reject R='...'   최신 플랜 거절"
	@echo ""
	@echo "Dispatch:"
	@echo "  make dispatch T=T-001 티켓 디스패치"
	@echo "  make dispatch-all     준비된 티켓 전체 디스패치"
	@echo ""
	@echo "Gates:"
	@echo "  make test             테스트 실행"
	@echo "  make test-queue-schema queue schema 단위 테스트"
	@echo "  make scan-secrets     시크릿 스캔"
	@echo "  make pr-check         전체 검증"

release-template:
	bash scripts/release-template.sh
