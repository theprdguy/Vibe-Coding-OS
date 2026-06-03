#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export ROOT_DIR

python3 - <<'PY'
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

root = Path(os.environ.get("ROOT_DIR", ".")).resolve()
repo = Path(tempfile.mkdtemp(prefix="approve-multiline-"))

(repo / "devos/plans/pending").mkdir(parents=True)
(repo / "devos/plans/approved").mkdir(parents=True)
(repo / "devos/logs").mkdir(parents=True)
(repo / "devos/tasks").mkdir(parents=True)
(repo / "devos/tasks/QUEUE.yaml").write_text("version: '3.0'\ntickets: []\n", encoding="utf-8")
(repo / "deos.yaml").write_text(
    "\n".join(
        [
            "project_root: .",
            "devos_dir: devos",
            "queue_file: devos/tasks/QUEUE.yaml",
            "plans_dir: devos/plans",
            "logs_dir: devos/logs",
            "agents: {}",
            "",
        ]
    ),
    encoding="utf-8",
)

multiline_context = """증상 I-3: 'make approve P=...' 가 "Plan approved. Tickets added to queue."
출력 직후 동일 파일에 대해 'yaml.scanner.ScannerError: while scanning a quoted scalar ...
line 517' 출력 + Make exit 1.

같은 파일을 다른 시점에 yaml.safe_load 하면 정상. PyYAML safe_dump가 multiline single-quoted scalar를
만들었을 때 동일 lib가 비결정적으로 거부할 수 있음.

해결 방향: default_style='|' (block scalar) 강제 + PyYAML 버전 핀(>=6.0).
"""

plan = {
    "id": "multiline-plan",
    "status": "pending",
    "tickets": [
        {
            "id": "T-MULTILINE-FIXTURE",
            "owner": "CODEX",
            "status": "done",
            "priority": "high",
            "goal": "approve 직후 QUEUE.yaml 검증이 multiline scalar로 인해 false-positive ScannerError를 내는 문제를 해소.",
            "context": multiline_context,
            "constraints": [
                "기존 QUEUE.yaml 호환 - 재dump 시 기존 short scalar는 그대로 유지한다.",
                "PyYAML 버전을 requirements.txt에 핀한다.",
            ],
            "dod": [
                "본 plan과 동일한 다중 multiline 본문 approve 시 ScannerError 없이 exit 0.",
                "approve 후 생성된 QUEUE.yaml을 yaml.safe_load로 즉시 재로드 시 예외 없음.",
            ],
            "files": ["server/ssot.py", "server/__main__.py", "requirements.txt"],
            "verify": [],
            "deps": [],
            "tdd": "required",
            "test_owner": "CLAUDE2",
            "impl_owner": "CODEX",
        }
    ],
}
(repo / "devos/plans/pending/multiline-plan.yaml").write_text(
    yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
    encoding="utf-8",
)

env = dict(os.environ)
env["PYTHONPATH"] = str(root)
result = subprocess.run(
    [sys.executable, "-m", "server", "approve", "multiline-plan"],
    cwd=repo,
    env=env,
    capture_output=True,
    text=True,
)

assert result.returncode == 0, result.stdout + result.stderr
assert "ScannerError" not in result.stdout + result.stderr
assert "Plan `multiline-plan` approved. Tickets added to queue." in result.stdout

queue_path = repo / "devos/tasks/QUEUE.yaml"
queue_text = queue_path.read_text(encoding="utf-8")
assert "context: |" in queue_text
assert "goal: approve" in queue_text

with queue_path.open(encoding="utf-8") as handle:
    loaded = yaml.safe_load(handle)

ticket = loaded["tickets"][0]
assert ticket["id"] == "T-MULTILINE-FIXTURE"
assert ticket["context"] == multiline_context

print("PASS: approve multiline queue reload")
PY
