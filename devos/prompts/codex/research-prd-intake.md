# CODEX — PRD intake 사전조사 (Phase 1)

> CLAUDE1 main 이 PRD decomposition 직전에 CODEX 에게 사전조사를 위임하는 protocol.
> 목적: CLAUDE1 (Opus, C1) 의 reasoning 시간을 architectural 결정에 집중시키고, 정형
> lookup (context7, 버전 핀, 의존성 호환성) 을 CODEX (C0, 별도 청구) 로 이전.

## 호출 시점

- `devos/prompts/claude/decompose-prd.md` Step 0.3 (기술 환경 조사) 직전
- 또는 `devos/prompts/claude/prd-intake-checklist.md` 의 도메인 키워드 트리거 후

## 호출 방식 (CLAUDE1 main 책임)

```bash
codex exec "$(cat <<'EOF'
You are doing PRD intake research for the deos project. Return findings as
structured markdown — no recommendations on architecture, just facts.

## PRD topic
{PRD slug + 한 문단 요약}

## Tech stack hints (if any from PRD)
{stack 키워드 — react/vue/fastapi/django/postgres/etc. 사용자 표현 그대로}

## Research targets
1. Library version compatibility — for each named library/framework, query context7
   for current stable version, breaking changes since 6 months ago, deprecation notes.
2. API surface stability — flag any API change in the past 1 year.
3. Dependency compatibility — peer dependency conflicts among named libraries.
4. Web search (default cached) for: recent CVE in named libraries, recent security
   advisories, recent migration guides.

## Output format
```yaml
research:
  date: 2026-MM-DD
  libraries:
    - name: <lib>
      current_stable: <version>
      breaking_changes_recent: [<list>]
      cve_recent: [<id>: <severity>]
      migration_notes: <text or "none">
  peer_conflicts: [<text>]
  api_changes_1y: [<text>]
  web_search_summary: <2-3 sentence summary>
references:
  - <url 1>
  - <url 2>
```

Do NOT recommend architecture. Do NOT decide on a stack. Facts only.
EOF
)" --output-schema /tmp/codex-research-schema.json -o /tmp/codex-research-result.json
```

(주의: 위 명령은 prompt template — 실제 호출 시 PRD 내용 inline 치환.)

## context7 사용

CODEX 측에 context7 MCP 가 1회 셋업되어 있어야 함 (Phase 1 셋업 명령):

```bash
codex mcp add context7 -- npx -y @upstash/context7-mcp
```

위 명령은 사용자 측 `~/.codex/config.toml` 에 영구 등록. 1회 실행 후 모든 codex
세션에서 context7 호출 가능.

## CLAUDE1 의 결과 통합

CODEX 결과 (`/tmp/codex-research-result.json` 또는 stdout) 를 CLAUDE1 이 Read 하여:
1. 사실 검증 — CODEX 결과가 plausible 한가? (간단한 sanity check)
2. ticket `context:` 필드에 발췌 (인용 + URL)
3. PRD intake Step 0.6 (designer review) 직전 사용자에게 요약 제시

## 한계

- CODEX 가 hallucinate 한 버전/CVE 정보는 1차 신호 — **항상 reference URL 따라가서 확인**
- 사용자에게 보일 때 "CODEX 사전조사 결과 (검증 후)" 명시 — 신뢰도 표시

## 비용

- C0 (CODEX 별도 청구). C1 (CLAUDE1 Opus) 의 lookup 시간 ↓.
- 추정: PRD 1건당 CODEX 호출 1회 = ~10-30K input + 1-3K output. 단가 OpenAI 측.

## Anti-patterns

- CODEX 결과를 사용자에게 검증 없이 그대로 노출 → 신뢰 손실 위험
- CODEX 에게 architecture 결정 위임 → ETHOS 위반 (CLAUDE1 의 역할)
- context7 결과만 의존하고 web search 결과 무시 → 최신 CVE 누락
