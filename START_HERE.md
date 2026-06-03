# START HERE — dev-os (Host-OS)

> 랩탑별 총괄 호스트 OS(`~/dev-os`) + 하위 독립 프로젝트. 빠른 시작 가이드.
> 전체 사용법·아키텍처: `README.md` · 운영 룰: `.claude/CLAUDE.md` · 에이전트 헌법: `devos/AI.md`.

## 1. 최초 1회 설정

```bash
# 1) 호스트 OS 클론 (랩탑마다 한 번) — 이미 ~/dev-os 가 있으면 생략
git clone <your-os-repo> ~/dev-os && cd ~/dev-os

# 2) Python 의존성
pip install -r requirements.txt

# 3) deos 명령을 어디서든 쓰도록 PATH 등록 (한 번만)
echo 'export PATH="$HOME/dev-os/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
deos projects   # 동작 확인
```

### 상시 서버 (서브 랩탑)
```bash
# com.deos.server.plist 의 WorkingDirectory 를 ~/dev-os 로 수정 후
cp ~/dev-os/com.deos.server.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.deos.server.plist
```

---

## 2. 데일리 루틴

### 출근 — 현황 파악
```bash
cd ~/dev-os && git pull
deos overview            # 전 프로젝트 todo/doing/blocked + OS 피드백
```

### 작업 — 프로젝트 진입
```bash
deos open myproject        # 어디서 실행해도 됨. cd + 호스트 settings 주입 + claude
#   세션 안: PRD 제출 → 티켓 분해 → deos approve → deos dispatch T-XXX
```

### OS 자체 정비
```bash
cd ~/dev-os && claude   # 호스트 루트에서 엔진/룰 수정 (sync 불필요)
```

### 퇴근
```bash
deos archive --project myproject   # done 티켓 정리
cd ~/dev-os && git push          # 호스트 동기화 (각 프로젝트는 자기 remote로 따로 push)
```

---

## 3. ★ 새 프로젝트 추가

> ⚠ **줄 단위로 복사하세요.** zsh가 `#` 주석을 명령으로 해석할 수 있어 인라인 주석을 뺐습니다.
> (한 번에 붙이려면 먼저 `setopt interactive_comments`.)

```bash
cd ~/dev-os/projects
git init newtool && cd newtool
printf 'name: newtool\n' > .deos.yaml
mkdir -p devos/tasks
cd ~/dev-os
deos register newtool projects/newtool
deos open newtool
```
의미: ① 독립 git 레포 생성(기존 레포면 `git clone <url> ~/dev-os/projects/newtool`) ② `.deos.yaml` 마커(**필수**)
③ `devos/tasks` task 상태 위치 ④ 호스트 레지스트리 등록 ⑤ 작업 시작.
> 프로젝트는 제품 코드 + 자기 task 상태만 보유. 엔진·에이전트·doctrine은 호스트가 제공.

---

## 4. 명령어 치트시트

```bash
# 호스트 레벨
deos overview                  # 전 프로젝트 현황 + 피드백
deos projects                  # 등록 프로젝트 목록
deos register <name> <path>    # 프로젝트 등록
deos open <name>               # 프로젝트 세션 진입
deos feedback "<text>"         # OS 중앙 피드백 백로그

# 프로젝트 레벨 (--project <name> 또는 프로젝트 폴더 안)
deos status   --project <name>
deos queue    --project <name>
deos pending  --project <name>
deos approve  --project <name>
deos reject "이유" --project <name>
deos dispatch T-XXX --project <name>
deos dispatch-codex T-XXX
deos dispatch-all
deos archive  --project <name>
deos verify   T-XXX
deos pr-check
```

---

## 5. 자주 묻는 것

- **프로젝트 작업은 어디서 시작하나요?** `deos open <name>` 한 줄. 디렉터리를 직접 찾아 들어갈 필요 없음 — 이름이 곧 인자.
- **OS를 고치면 프로젝트마다 반영해야 하나요?** 아니요. 엔진이 호스트 1곳에만 있어, 고치면 다음에 어느 프로젝트를 열든 자동 적용. sync 명령 없음.
- **프로젝트가 호스트 밖에 있으면?** `~/dev-os/projects/` 하위가 아니면 호스트 `.claude`(CLAUDE.md·agents) 자동 발견이 안 됨. 반드시 `projects/` 아래에 둘 것.
- **`--project` 를 매번 써야 하나요?** 프로젝트 폴더 안에서는 `.deos.yaml` 마커로 자동 인식되어 생략 가능. 호스트 루트 등 밖에서는 `--project <name>` 명시.
- **CLAUDE2 (Account B)?** sunset. builder sub-agent(in-session, Account A)로 흡수.
- **make 명령은?** 제거됨. `deos` 로 대체.
