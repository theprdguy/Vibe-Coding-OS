# CLAUDE2 글로벌 skill 격리 — 가능성 조사

**작성:** 2026-04-27 · CLAUDE1 (T-OS2-V32-06)
**목적:** `CLAUDE_CONFIG_DIR=.claude-b` 로 분리한 CLAUDE2가 글로벌 `~/.claude/skills/` 를 공유하는 문제(이슈 I-7)를 환경 변수로 격리할 수 있는지 검증.

## 결론

**미지원.** Anthropic 공식 문서 시점(2026-04, Claude Code skills 페이지)에 `CLAUDE_SKILLS_DIR` 또는 동등한 env var는 존재하지 않는다. Claude Code가 skill을 검색하는 위치는 다음 4개로 **하드코딩**되어 있다.

| Location | Path | Applies to |
|---|---|---|
| Enterprise | managed settings 경로 | All users in your organization |
| Personal | `~/.claude/skills/<skill-name>/SKILL.md` | All your projects |
| Project | `.claude/skills/<skill-name>/SKILL.md` | This project only |
| Plugin | `<plugin>/skills/<skill-name>/SKILL.md` | Where plugin is enabled |

(출처 인용: `code.claude.com/docs/en/skills` — "Where skills live" 표.)

`CLAUDE_CONFIG_DIR`은 settings/credentials/history 디렉토리는 옮길 수 있으나, **skill 검색 경로는 분리되지 않는다**는 보고가 있다 (`anthropics/claude-code` 이슈 #3833 — "CLAUDE_CONFIG_DIR environment variable behavior unclear - still creates local .claude/ directories"). 즉, `CLAUDE_CONFIG_DIR=.claude-b` 만으로 `~/.claude/skills/` 공유를 끊을 수 없다.

settings reference에 명시된 env var 중 skill 위치를 제어하는 항목은 없다 (`CLAUDE_CODE_ENABLE_TELEMETRY`, `CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS`, `CLAUDE_CODE_SKIP_PROMPT_HISTORY` 등은 모두 다른 기능 토글).

## 우회 가능한 메커니즘 (대안)

skill의 **검색 경로**는 격리할 수 없지만, **활성화 여부**와 **위험 차단**은 다음 3가지로 부분 격리 가능.

1. **Permission rule로 deny** — `.claude-b/.claude/settings.json` 의 `permissions.deny`에 `Skill(<name>)` 을 추가하면 해당 세션이 그 skill을 invoke하지 못한다. 형식:
   - `Skill(deploy)` — 정확 매치
   - `Skill(deploy *)` — prefix + 인자 와일드카드
   - `Skill` 만 적으면 모든 skill 차단
   다만 description은 여전히 context에 로드됨 (1% 컨텍스트 예산 차지).

2. **`disable-model-invocation: true`** — 개별 skill의 frontmatter에 추가하면 자동 호출은 막히고 `/skill-name` 사용자 invoke만 허용. 깨진 skill 자체를 fix할 수 없을 때는 효과 없음.

3. **`disableSkillShellExecution: true`** (settings) — skill 안의 ` !`...` ` 또는 ` ```! ` shell 실행을 일괄 차단. broken symlink 자체는 막지 못함.

## 본 프로젝트(I-7) 관점에서의 의미

- **skill 검색 경로 격리**: 불가능. CLAUDE2도 CLAUDE1과 동일한 `~/.claude/skills/` 를 본다.
- **broken symlink로 인한 abort 위험**: 글로벌 영역 자체는 격리 안 되므로, 이 위험은 CLAUDE2도 동일 보유.
- **현 시점 가장 효과적인 방어:** preflight 검증 (T-OS2-H1로 구현 완료). dispatch 직전에 `~/.claude/skills/*` 의 dangling symlink를 차단하는 방식이 env var 격리를 대체한다.

## 후속 plan 필요 여부

**불필요 (현 시점).** 이유:
- env var 격리가 미지원이라 코드 변경으로 해결할 수단이 없음.
- T-OS2-H1 preflight가 깨진 symlink 시나리오를 이미 차단함 (DOD 검증 완료).
- Anthropic이 미래에 `CLAUDE_SKILLS_DIR` 또는 동등 옵션을 도입하면 그때 1줄 env 추가로 적용 가능. 그 시점이 오기 전까지 새로운 ticket을 미리 만들 가치가 낮음.

**모니터링 권장:**
- `anthropics/claude-code` 이슈 #25762 ("Add environment variable to configure .claude config directory location") — close/release 시 재검토.
- Claude Code 새 minor version 릴리스 노트에서 `CLAUDE_*_DIR` 또는 `CLAUDE_SKILLS_*` 키워드 검색.

## 참조

- Claude Code Skills 공식 문서: <https://code.claude.com/docs/en/skills>
- Claude Code Settings reference: <https://code.claude.com/docs/en/settings>
- 이슈 #3833 (CLAUDE_CONFIG_DIR 동작 불명확): <https://github.com/anthropics/claude-code/issues/3833>
- 이슈 #25762 (config dir env var 요청): <https://github.com/anthropics/claude-code/issues/25762>
