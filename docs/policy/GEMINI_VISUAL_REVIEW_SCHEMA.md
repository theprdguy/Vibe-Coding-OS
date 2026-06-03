# deos Gemini Visual Review Schema

Status: draft

Implements doctrine principles:

- UI Production work needs rendered outcome review.
- Gemini reviews objective visual/user-outcome issues, not code or final taste.
- Capture failure is an infrastructure failure, not a visual pass.

## Input Schema

```yaml
ticket: T-XXX
mode: exploration | productization | production
user_outcome: string
work_type: ui
review_round: 1
screens:
  - name: desktop
    viewport: 1440x900
    image: path/to/desktop.png
  - name: mobile
    viewport: 390x844
    image: path/to/mobile.png
expected_states:
  - loading
  - empty
  - error
  - success
privacy_masking: true | false
notes: string
```

## Output Schema

```yaml
verdict: pass | request_changes | needs_human_judgment | infra_failure
issues:
  - severity: blocker | warning | note
    category: layout | clipping | overlap | blank_screen | responsive | state_missing | intent_mismatch | privacy | taste
    evidence: string
    recommendation: string
human_review_required: true | false
same_issue_as_previous_round: true | false
```

## Authority Limits

Gemini may identify:

- Layout breakage.
- Text overlap or clipping.
- Blank or broken screens.
- Desktop/mobile responsive regressions.
- Missing loading, empty, error, or success states.
- Mismatch between ticket intent and rendered screen.
- Privacy exposure visible in screenshots.

Gemini must not approve or reject:

- Code quality.
- Security correctness.
- Business logic correctness.
- Hidden state behavior.
- Product strategy.
- Final visual taste.

## Production UI Policy

For `mode: production` and `work_type: ui`:

- Missing capture is `infra_failure` and blocks.
- First `request_changes` blocks.
- Builder should address objective issues and request another visual review.
- If the same issue remains on a later review:
  - objective breakage continues to block;
  - taste/tradeoff becomes `needs_human_judgment`.
- PM can approve taste/tradeoff through waiver or request further iteration.
