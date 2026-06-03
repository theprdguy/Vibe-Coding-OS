#!/usr/bin/env node
// Vendored from gsd-build/get-shit-done hooks/gsd-context-monitor.js
// Original: https://github.com/gsd-build/get-shit-done/blob/main/hooks/gsd-context-monitor.js
// License: MIT (https://github.com/gsd-build/get-shit-done/blob/main/LICENSE)
// Modifications:
//   - Vendoring header added
//   - GSD-specific .planning/ config check kept (inert when absent)
//   - gsd-tools.cjs spawn block removed (we don't ship gsd-tools)
//   - Advisory messages adapted to os2 context (devos/ SSOT references)
//
// Context Monitor - PostToolUse hook
// Reads context metrics from the statusline bridge file and injects
// warnings when context usage is high. Makes the AGENT aware of context
// limits (the statusline only shows the user).
//
// Pair file: .claude/hooks/statusline.js (writes /tmp/claude-ctx-{session_id}.json)
//
// Thresholds:
//   WARNING  (remaining <= 35%): Agent should wrap up current task
//   CRITICAL (remaining <= 25%): Agent should stop immediately and save state
//
// Debounce: 5 tool uses between warnings to avoid spam
// Severity escalation bypasses debounce (WARNING -> CRITICAL fires immediately)

const fs = require('fs');
const os = require('os');
const path = require('path');

const WARNING_THRESHOLD = 35;
const CRITICAL_THRESHOLD = 25;
const STALE_SECONDS = 60;
const DEBOUNCE_CALLS = 5;

let input = '';
const stdinTimeout = setTimeout(() => process.exit(0), 10000);
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', () => {
  clearTimeout(stdinTimeout);
  try {
    const data = JSON.parse(input);
    const sessionId = data.session_id;

    if (!sessionId) {
      process.exit(0);
    }

    // Reject session IDs with path traversal sequences or path separators.
    // session_id is used to construct file paths in /tmp — an unsanitized
    // value could escape the temp directory and read or write arbitrary files.
    if (/[/\\]|\.\./.test(sessionId)) {
      process.exit(0);
    }

    const tmpDir = os.tmpdir();
    const metricsPath = path.join(tmpDir, `claude-ctx-${sessionId}.json`);

    // If no metrics file, this is a subagent or fresh session — exit silently
    if (!fs.existsSync(metricsPath)) {
      process.exit(0);
    }

    const metrics = JSON.parse(fs.readFileSync(metricsPath, 'utf8'));
    const now = Math.floor(Date.now() / 1000);

    if (metrics.timestamp && (now - metrics.timestamp) > STALE_SECONDS) {
      process.exit(0);
    }

    const remaining = metrics.remaining_percentage;
    const usedPct = metrics.used_pct;

    if (remaining > WARNING_THRESHOLD) {
      process.exit(0);
    }

    // Debounce
    const warnPath = path.join(tmpDir, `claude-ctx-${sessionId}-warned.json`);
    let warnData = { callsSinceWarn: 0, lastLevel: null };
    let firstWarn = true;

    if (fs.existsSync(warnPath)) {
      try {
        warnData = JSON.parse(fs.readFileSync(warnPath, 'utf8'));
        firstWarn = false;
      } catch (e) {
        // Corrupted file, reset
      }
    }

    warnData.callsSinceWarn = (warnData.callsSinceWarn || 0) + 1;

    const isCritical = remaining <= CRITICAL_THRESHOLD;
    const currentLevel = isCritical ? 'critical' : 'warning';

    const severityEscalated = currentLevel === 'critical' && warnData.lastLevel === 'warning';
    if (!firstWarn && warnData.callsSinceWarn < DEBOUNCE_CALLS && !severityEscalated) {
      fs.writeFileSync(warnPath, JSON.stringify(warnData));
      process.exit(0);
    }

    warnData.callsSinceWarn = 0;
    warnData.lastLevel = currentLevel;
    fs.writeFileSync(warnPath, JSON.stringify(warnData));

    // Build advisory warning message — adapted to os2 context
    let message;
    if (isCritical) {
      message = `CONTEXT CRITICAL: Usage at ${usedPct}%. Remaining: ${remaining}%. ` +
        'Context is nearly exhausted. Inform the user and ask how to proceed. ' +
        'Do NOT autonomously start new complex work or write handoff files. ' +
        'Consider /clear with a handoff log per devos/prompts/common/handoff-3lines.md.';
    } else {
      message = `CONTEXT WARNING: Usage at ${usedPct}%. Remaining: ${remaining}%. ` +
        'Be aware that context is getting limited. Avoid unnecessary exploration ' +
        'or starting new complex work. If between defined plan steps, prepare to pause.';
    }

    const output = {
      hookSpecificOutput: {
        hookEventName: 'PostToolUse',
        additionalContext: message
      }
    };

    process.stdout.write(JSON.stringify(output));
  } catch (e) {
    // Silent fail — never block tool execution
    process.exit(0);
  }
});
