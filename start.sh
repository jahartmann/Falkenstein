#!/bin/bash
set -e

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

# 7. Start
echo -e "${GREEN}Starte Falkenstein auf Port $(grep FRONTEND_PORT .env 2>/dev/null | cut -d= -f2 || echo 8080)...${NC}"
echo -e "Dashboard: http://localhost:$(grep FRONTEND_PORT .env 2>/dev/null | cut -d= -f2 || echo 8080)"
echo -e "Büro:      http://localhost:$(grep FRONTEND_PORT .env 2>/dev/null | cut -d= -f2 || echo 8080)/office"
echo ""
python -m backend.main
