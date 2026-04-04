# Master Architecture Document: Gamified AI Office & Life Sim

## 1. Projektübersicht & Vision
Dieses Projekt ist ein "KI-Betriebssystem" mit einem visuellen 2D-Pixelart-Frontend. Es kombiniert eine produktive, dateibasierte KI-Workforce mit einer autonomen Lebenssimulation. 
Das System minimiert API-Kosten durch intelligentes "LLM-Routing": Kostenlose lokale Modelle (Ollama) übernehmen 95% der Arbeit (Planung, Simulation, Recherche), während teure Premium-Modelle (Gemini/Claude via CLI) nur für finale, komplexe Ausführungen (Code, finale Texte) aufgerufen werden.

### Die zwei Kern-Modi:
1. **WORK-Mode (Prio 1):** Agenten bearbeiten zugewiesene Tasks. Vollständiger Zugriff auf Tools (Web, lokales Filesystem/Obsidian).
2. **SIM-Mode / IDLE (Prio 2):** Wenn keine Tasks anstehen, generiert Ollama autonom "menschliches" Verhalten (Gespräche, Bewegung im Büro, Beziehungsaufbau).

---

## 2. Tech Stack
* **Frontend:** Phaser.js (TILT Tilemap, Pixel-Agent-Sprites), HTML/CSS (UI Overlays für Taskboard & Sim-Dashboard). Easystar.js für Pathfinding.
* **Backend:** Python (FastAPI) mit WebSockets für Echtzeit-Kommunikation mit dem Frontend.
* **LLM Engine Lokal:** Ollama (z.B. Llama 3 / Mistral) via Python-Library.
* **LLM Engine Premium:** Subprocess-Calls an die lokalen `gemini` oder `claude` CLI-Tools des Users.
* **Datenbanken:** \* `SQLite` (Relational: Tasks, Agenten-Status, Beziehungsgeflechte).
  * `ChromaDB` (Vektor-DB: Langzeitgedächtnis / RAG).
* **Externe Interfaces:** lokaler Obsidian-Vault (Markdown) und Telegram-Bot-API.

---

## 3. Die LLM-Routing Logik (Kosten-Effizienz)
Das Backend fungiert als "Agentur". Kein Task geht direkt an die Premium-APIs.
1. **Projektmanager (Ollama):** Empfängt den Task (z.B. via Telegram oder UI), zerlegt ihn in Teilaufgaben und erstellt einen JSON-Plan.
2. **Junior Agent (Ollama):** Führt Web-Recherchen aus, sammelt Kontext aus Obsidian und erstellt Vorab-Entwürfe/Pseudocode.
3. **Triage-Entscheidung:** Ollama entscheidet: Ist der Task simpel? -\> Ollama beendet ihn selbst. Ist er hochkomplex (z.B. fehlerfreier Code)? -\> Übergabe an den Experten.
4. **Senior Expert (Claude/Gemini CLI):** Das Backend generiert einen finalen, komprimierten Prompt ("Hier ist der Plan und die Recherche. Schreibe den finalen Code.") und ruft die CLI auf. Limit-/Abo-Verbrauch auf ein Minimum reduziert.
5. **Review (Ollama):** Prüft das CLI-Ergebnis gegen die Ursprungsanforderung.

---

## 4. Tool Registry (Function Calling)
Die Agenten agieren in der echten Welt. Wenn ein LLM (Ollama oder CLI) ein JSON-Tool-Kommando ausgibt, führt das Backend dieses in Python aus und gibt das Ergebnis in den Prompt-Kontext zurück.

### Tool-Module (`/backend/tools/`):
* **`obsidian_manager.py` (Filesystem):**
  * Greift auf `$OBSIDIAN_VAULT_PATH` zu.
  * Erstellt zwingend saubere Strukturen: `/Projekte/[Projektname]/`.
  * Aktualisiert Kanban-Boards (`/Management/Inbox.md`) und schreibt `Daily_Report_YYYY-MM-DD.md`.
* **`web_surfer.py`:** Nutzt `duckduckgo-search` und `BeautifulSoup` für kostenlose Webrecherche durch Ollama.
* **`code_executor.py`:** Führt generierten Python-Code lokal im isolierten `/workspace` via `subprocess` aus und gibt Konsolen-Errors zur Selbstkorrektur an das LLM zurück.
* **`image_gen.py`:** (Optional) Generiert Bilder via lokaler Stable Diffusion API oder dediziertem CLI-Call.

---

## 5. Das 3-Tier Memory System
Um Kontextverlust zu vermeiden (besonders bei Telegram-Sessions) und projektübergreifend zu lernen.

1. **Short-Term / Session Memory (RAM):** \* Verwaltet durch `session.py`. 
   2. Speichert die letzten 15 Nachrichten einer aktiven Telegram-Chat-ID. Wird bei jeder neuen Nachricht an den Ollama-PM als Kontext übergeben. Verfällt nach 30 Min.
2. **Episodic Memory / Long-Term (ChromaDB):** \* Nach Abschluss eines jeden Tasks wird eine strukturierte Zusammenfassung ("Agent X hat Modul Y für Projekt Z programmiert") vektorisiert.
   4. **RAG-Integration:** Bevor der PM-Agent einen neuen Task plant, fragt er ChromaDB nach relevanten vergangenen Lösungen ab.
3. **Semantic Memory (SQLite):** \* Speichert den aktuellen "harten" Status der Welt (Wo steht Agent X in Phaser? Wie hoch ist das Stresslevel? Welche Tasks sind in der DB "open"?).

---

## 6. Externe Interfaces
* **Telegram Bot:** Läuft als asynchroner Task in FastAPI. Eingehende Nachrichten werden direkt in den "Task-Eingang" des Ollama-PMs geroutet (unter Berücksichtigung des Session-Memories).
* **Phaser Frontend:** Hört nur auf den WebSocket. 
  * JSON-Payloads wie `{"action": "move", "agent": "Bob", "x": 12, "y": 5}` triggern Animationen. 
  * Arbeiten die Agenten an Tools (Websuche, Obsidian schreiben), erscheinen entsprechende Icons (Lupe, Diskette) über den Pixel-Sprites.

---

## 7. Projektstruktur
\`\`\`text
/gamified-office
│
├── /frontend
│   ├── index.html        # UI Overlays & Phaser Container
│   ├── game.js           # Phaser Logic (Tilemap, Pathfinding, Sprites)
│   ├── ui.js             # HTML DOM Updates (Sim-Dashboard, Task-Board)
│   └── /assets           # TILT JSON, Tilesets
│
├── /backend
│   ├── main.py           # FastAPI, WebSockets & App Entry
│   ├── orchestrator.py   # Triage-Logik & State Machine (Work vs. Sim)
│   ├── /memory
│   │   ├── chroma\_db/    # Vektor DB Speicherort
│   │   ├── rag\_engine.py # Embedding & Retrieval
│   │   └── session.py    # Telegram Session Buffer
│   ├── /tools
│   │   ├── obsidian\_manager.py
│   │   ├── web\_surfer.py
│   │   └── code\_executor.py
│   ├── /interfaces
│   │   ├── telegram\_bot.py
│   │   └── cli\_bridge.py # Subprocess Wrapper für Gemini/Claude CLI
│   └── database.py       # SQLite CRUD
│
├── /workspace            # Isolierter Ordner für Code-Execution
└── requirements.txt