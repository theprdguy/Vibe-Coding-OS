#!/usr/bin/env bash

set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

WARN_COUNT=0

GREEN="$(printf '\033[32m')"
YELLOW="$(printf '\033[33m')"
RED="$(printf '\033[31m')"
BLUE="$(printf '\033[34m')"
RESET="$(printf '\033[0m')"

section() {
  printf "\n${BLUE}%s${RESET}\n" "$1"
}

success() {
  printf "${GREEN}✅ %s${RESET}\n" "$1"
}

warn() {
  WARN_COUNT=$((WARN_COUNT + 1))
  printf "${YELLOW}⚠️ %s${RESET}\n" "$1"
}

error() {
  printf "${RED}❌ %s${RESET}\n" "$1" >&2
}

summary_warn() {
  printf "${YELLOW}⚠️ %s${RESET}\n" "$1"
}

load_env_file() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
    success "Loaded .env"
  else
    success "No .env found; continuing"
  fi
}

section "1/4 CLI 도구 확인"

check_required() {
  local tool="$1"
  local url="$2"
  if command -v "$tool" >/dev/null 2>&1; then
    success "$tool found"
  else
    error "$tool is required. Install: $url"
    exit 1
  fi
}

check_optional() {
  local tool="$1"
  local url="$2"
  if command -v "$tool" >/dev/null 2>&1; then
    success "$tool found"
  else
    warn "$tool not found. Install if needed: $url"
  fi
}

check_required "python3" "https://www.python.org/downloads/"
check_required "pip3" "https://pip.pypa.io/en/stable/installation/"
check_required "git" "https://git-scm.com/downloads"
check_optional "claude" "https://docs.anthropic.com/en/docs/claude-code/overview"
check_optional "codex" "https://platform.openai.com/docs/codex/overview"
check_optional "gemini" "https://github.com/google-gemini/gemini-cli"
check_optional "tmux" "https://github.com/tmux/tmux/wiki/Installing"
check_gitleaks() {
  if command -v gitleaks >/dev/null 2>&1; then
    success "gitleaks found ($(gitleaks version 2>/dev/null | head -1))"
    return
  fi
  local macos_major
  macos_major="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)"
  if [ "$macos_major" -ge 13 ] 2>/dev/null; then
    warn "gitleaks not found. Install: brew install gitleaks"
  else
    local arch
    arch="$(uname -m)"
    local suffix="darwin_x64"
    [ "$arch" = "arm64" ] && suffix="darwin_arm64"
    warn "gitleaks not found. macOS ${macos_major:-?} has no Homebrew bottle — install via direct binary:"
    printf "${YELLOW}   curl -L https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_8.30.1_${suffix}.tar.gz | tar xz && sudo mv gitleaks /usr/local/bin/${RESET}\n"
  fi
}

check_gitleaks

section "2/4 Python 의존성 설치"
VENV_DIR="$ROOT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
  success "Created virtual environment at .venv"
else
  success "Virtual environment already exists"
fi
"$VENV_DIR/bin/pip" install -r "$ROOT_DIR/requirements.txt" -q
success "Installed Python dependencies"

section "3/4 환경변수 설정"
load_env_file
success "Loaded local environment from .env when present"
success "Optional integrations can be configured in .env or .env.local"

section "4/4 PATH 설정"
BIN_DIR="$ROOT_DIR/bin"
if echo "$PATH" | tr ':' '\n' | grep -qx "$BIN_DIR"; then
  success "bin/ already on PATH"
else
  warn "bin/ is not on PATH — os3 commands won't work from outside this directory"
  printf "    Add to PATH with:\n"
  printf "      echo 'export PATH=\"%s:\$PATH\"' >> ~/.zshrc && source ~/.zshrc\n" "$BIN_DIR"
  printf "    Or for bash:\n"
  printf "      echo 'export PATH=\"%s:\$PATH\"' >> ~/.bashrc && source ~/.bashrc\n" "$BIN_DIR"
fi

printf "\n"
if [ "$WARN_COUNT" -eq 0 ]; then
  success "Setup complete with no warnings"
else
  summary_warn "Setup complete with ${WARN_COUNT} warning(s)"
fi
printf "\n"
printf "Next: open a Claude Code session in this directory:\n"
printf "  cd %s && claude\n" "$ROOT_DIR"
printf "Or enter a project: os3 open <project-name>\n"
