#!/bin/bash
cd "$(dirname "$0")"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== Falkenstein Setup ===${NC}"

# 1. Python check
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 nicht gefunden. Bitte installiere Python 3.11+${NC}"
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "Python: ${PY_VERSION}"

# 2. Virtual environment
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Erstelle Virtual Environment...${NC}"
    python3 -m venv venv
fi
source venv/bin/activate

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
        echo -e "${YELLOW}Hinweis: gemma4 Modell nicht gefunden. Lade mit: ollama pull gemma4:26b${NC}"
    fi
else
    echo -e "${YELLOW}Hinweis: Ollama nicht installiert. Siehe https://ollama.ai${NC}"
fi

# 7. Git-Pull Watcher (background): checks every 60s, restarts server on changes
_git_watch() {
    while true; do
        sleep 60
        OLD_HEAD=$(git rev-parse HEAD 2>/dev/null)
        git pull --ff-only -q 2>/dev/null || continue
        NEW_HEAD=$(git rev-parse HEAD 2>/dev/null)
        if [ "$OLD_HEAD" != "$NEW_HEAD" ]; then
            echo -e "\n${GREEN}[Git] Neue Änderungen gezogen. Server wird neugestartet...${NC}"
            pip install -q -r requirements.txt 2>/dev/null
            kill $SERVER_PID 2>/dev/null
        fi
    done
}

# 8. Start (auto-restart loop)
PORT=$(grep FRONTEND_PORT .env 2>/dev/null | cut -d= -f2 || echo 8080)
echo -e "${GREEN}Starte Falkenstein auf Port ${PORT}...${NC}"
echo -e "Dashboard: http://localhost:${PORT}"
echo -e "Büro:      http://localhost:${PORT}/office"
echo ""

# Trap SIGINT (Ctrl+C) to kill watcher and exit cleanly
trap 'echo -e "\n${YELLOW}Server gestoppt.${NC}"; kill $WATCHER_PID 2>/dev/null; exit 0' INT

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
    sleep 2
done
