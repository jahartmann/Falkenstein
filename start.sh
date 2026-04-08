#!/bin/bash
cd "$(dirname "$0")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Falkenstein Setup ===${NC}"

# 1. Python 3.12 check (CrewAI requires Python <3.14)
PYTHON_BIN=""
for candidate in python3.12 python3.13 python3.11; do
    if command -v "$candidate" &> /dev/null; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    # Fallback: check if default python3 is <3.14
    if command -v python3 &> /dev/null; then
        PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
        if [ "$PY_MINOR" -lt 14 ]; then
            PYTHON_BIN="python3"
        fi
    fi
fi

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${YELLOW}Python 3.11-3.13 nicht gefunden. Versuche automatische Installation...${NC}"
    if command -v brew &> /dev/null; then
        echo -e "${YELLOW}Installiere Python 3.12 via Homebrew...${NC}"
        brew install python@3.12
        PYTHON_BIN="$(brew --prefix python@3.12)/bin/python3.12"
    elif command -v apt &> /dev/null; then
        echo -e "${YELLOW}Installiere Python 3.12 via apt...${NC}"
        sudo apt update && sudo apt install -y python3.12 python3.12-venv
        PYTHON_BIN="python3.12"
    fi
    if [ -z "$PYTHON_BIN" ] || ! command -v "$PYTHON_BIN" &> /dev/null; then
        echo -e "${RED}Python 3.12 konnte nicht installiert werden.${NC}"
        echo -e "${RED}Bitte manuell installieren: brew install python@3.12${NC}"
        exit 1
    fi
fi

PY_VERSION=$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "Python: ${PY_VERSION} (${PYTHON_BIN})"

# 2. Virtual environment (venv312)
VENV_DIR="venv312"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Erstelle Virtual Environment mit ${PYTHON_BIN}...${NC}"
    $PYTHON_BIN -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

# 3. Dependencies
echo -e "${YELLOW}Installiere Abhängigkeiten...${NC}"
pip install -q -r requirements.txt

# 4. .env setup
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}Erstelle .env aus .env.example...${NC}"
    cp .env.example .env
    echo -e "${YELLOW}Bitte passe .env an deine Konfiguration an (Telegram, Ollama etc.)${NC}"
fi

# 5. Directories
mkdir -p workspace data

# 6. Ollama check
if command -v ollama &> /dev/null; then
    echo -e "Ollama: $(ollama --version 2>/dev/null || echo 'installiert')"
    if ! ollama list 2>/dev/null | grep -q "gemma4"; then
        echo -e "${YELLOW}Lade gemma4 Modelle...${NC}"
        ollama pull gemma4:e4b 2>/dev/null &
        ollama pull gemma4:26b 2>/dev/null &
        wait
    fi
else
    echo -e "${YELLOW}Hinweis: Ollama nicht installiert. Siehe https://ollama.ai${NC}"
fi

# 7. Cleanup & Process Management
_kill_server() {
    # Kill server process + all children (MCP subprocesses etc.)
    if [ -n "$SERVER_PID" ] && kill -0 $SERVER_PID 2>/dev/null; then
        kill $SERVER_PID 2>/dev/null
        for i in 1 2 3; do
            kill -0 $SERVER_PID 2>/dev/null || break
            sleep 1
        done
        kill -9 $SERVER_PID 2>/dev/null
    fi
    # Kill any orphaned backend.main or MCP node processes from this project
    _kill_orphans
}

_kill_orphans() {
    # Orphaned Python server processes
    pgrep -f "python.*backend\.main" 2>/dev/null | while read pid; do
        [ "$pid" != "$$" ] && [ "$pid" != "$SERVER_PID" ] && kill -9 "$pid" 2>/dev/null
    done
    # Orphaned MCP node processes spawned by us (apple-mcp, mcp-obsidian, desktop-commander)
    pgrep -f "node.*(apple-mcp|mcp-obsidian|desktop-commander)" 2>/dev/null | xargs kill -9 2>/dev/null
    # Port cleanup
    lsof -ti:${PORT:-8080} 2>/dev/null | xargs kill -9 2>/dev/null
}

# 8. Git-Pull Watcher (background): checks every 60s, restarts server on changes
_git_watch() {
    while true; do
        sleep 60
        OLD_HEAD=$(git rev-parse HEAD 2>/dev/null)
        git pull --ff-only -q 2>/dev/null || continue
        NEW_HEAD=$(git rev-parse HEAD 2>/dev/null)
        if [ "$OLD_HEAD" != "$NEW_HEAD" ]; then
            echo -e "\n${GREEN}[Git] Neue Änderungen gezogen. Server wird neugestartet...${NC}"
            source "$VENV_DIR/bin/activate" && pip install -q -r requirements.txt 2>/dev/null
            _kill_server
        fi
    done
}

# 9. Start (auto-restart loop)
PORT=$(grep FRONTEND_PORT .env 2>/dev/null | cut -d= -f2 || echo 8080)

# Kill zombies from previous runs before starting
_kill_orphans
echo -e "${GREEN}Starte Falkenstein auf Port ${PORT}...${NC}"
echo -e "Dashboard: http://localhost:${PORT}"
echo -e "Büro:      http://localhost:${PORT}/office"
echo ""

# Trap SIGINT/SIGTERM to clean up properly
trap 'echo -e "\n${YELLOW}Server gestoppt.${NC}"; _kill_server; kill $WATCHER_PID 2>/dev/null; exit 0' INT TERM

while true; do
    python -m backend.main &
    SERVER_PID=$!

    # Start git watcher on first loop
    if [ -z "$WATCHER_PID" ]; then
        _git_watch &
        WATCHER_PID=$!
    fi

    wait $SERVER_PID || true
    EXIT_CODE=$?

    echo -e "\n${YELLOW}Server beendet (Exit $EXIT_CODE). Neustart in 2s...${NC}"
    _kill_orphans
    sleep 2
done
