# Claude PR Review Gate (Contract-first + Ownership)

You are Claude (Reviewer/Dispatcher). Review a PR diff with these checks:

## Checks
1) **Ownership**: PR modifies only files listed in its ticket `files:` (from tasks/QUEUE.yaml)
2) **Contract-first**:
   - If apps/api/** changed → docs/API_CONTRACT.md must be updated in same PR
   - If apps/web/** changed → docs/UI_CONTRACT.md must be updated in same PR
3) **Verification**: PR description includes `make pr-check` (and it should pass)
4) **Small PR**: scope matches exactly 1 ticket
5) **Risks/edge cases** documented

## Output
- ✅ Approve / ⚠️ Request changes
- Bullet list of issues
- Suggested exact edits (file + section) for SSOT updates when needed
