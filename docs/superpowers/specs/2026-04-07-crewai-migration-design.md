# Falkenstein: CrewAI-Migration & Native Ollama Integration

**Datum:** 2026-04-07
**Ansatz:** CrewAI als Library — FastAPI bleibt Rückgrat, CrewAI ersetzt nur die Agent-Engine
**Strategie:** Clean Cut — altes Agent-System komplett raus

---

## 1. Flow-Engine (ersetzt MainAgent + classify)

### Ist-Zustand
`InputGuard -> IntentPrefilter -> PromptConsolidator -> IntentEngine.parse() -> classify() -> dispatch`
Bis zu 3 sequenzielle LLM-Calls bevor ein SubAgent startet.

### Soll-Zustand
Ein CrewAI `Flow` namens `FalkensteinFlow`:

```python
class FalkensteinFlow(Flow):

    @start()
    def receive_message(self):
        # InputGuard (bleibt, kein LLM)
        # PromptConsolidator (bleibt, kein LLM)
        # Rule-Engine: Regex + Keyword-Matching
        #   -> Match? -> self.state.crew_type = "coder"/"researcher"/etc.
        #   -> Kein Match? -> weiter zu classify

    @router(receive_message)
    def route(self):
        if self.state.crew_type:
            return self.state.crew_type
        return "classify"

    @listen("classify")
    def classify_with_llm(self):
        # 1 LLM-Call mit e4b (structured output, ~200ms)
        # Gibt crew_type zurueck

    @listen("coder")
    def run_coder_crew(self): ...

    @listen("researcher")
    def run_researcher_crew(self): ...

    # ... weitere Crews analog
```

### Was wegfaellt
- `IntentEngine.parse()` (extra LLM-Call)
- `main_agent.py` classify-Methode
- `DynamicAgent` + `SubAgent` komplett

### Was bleibt
- `InputGuard` (Security, kein LLM)
- `PromptConsolidator` (Text-Processing, kein LLM)
- Regex-Patterns aus `IntentPrefilter` wandern in die Rule-Engine des Flows

---

## 2. Crews & Agents

### Crew-Uebersicht

| Crew | Agent(s) | LLM | Tools | Typische Tasks |
|---|---|---|---|---|
| **CoderCrew** | Coder-Agent | 26b + e4b dispatch | shell_runner, code_executor, FileReadTool, FileWriterTool, GithubSearchTool | Python, Backend, Scripts, Debugging |
| **WebDesignCrew** | Designer-Agent + Coder-Agent | 26b + e4b dispatch | FileReadTool, FileWriterTool, ScrapeWebsiteTool, shell_runner | HTML/CSS/JS, Tailwind, Landing Pages |
| **SwiftCrew** | Swift-Agent | 26b + e4b dispatch | FileReadTool, FileWriterTool, shell_runner, code_executor | SwiftUI, iOS/macOS Apps |
| **ResearcherCrew** | Researcher-Agent | 26b + e4b dispatch | SerperDevTool, ScrapeWebsiteTool, obsidian_manager | Web-Recherche, Zusammenfassungen |
| **WriterCrew** | Writer-Agent | 26b | obsidian_manager, FileReadTool, FileWriterTool | Texte, Doku, Guides, Cheat-Sheets |
| **KI-ExpertCrew** | KI-Agent | 26b + e4b dispatch | shell_runner, code_executor, SerperDevTool, ollama_manager | ML-Pipelines, Prompt-Engineering, Fine-Tuning |
| **OpsCrew** | Ops-Agent | e4b | ollama_manager, self_config, system_shell | Server, Docker, Deployment |
| **AnalystCrew** | Analyst-Agent | 26b + e4b dispatch | code_executor, FileReadTool, CSVSearchTool | Datenanalyse, Visualisierung, Reports |
| **PremiumCrew** | Premium-Agent | Claude/Gemini API | alle verfuegbaren Tools | Komplexe Tasks die lokale Modelle ueberfordern |

### YAML-Konfiguration

```yaml
# agents.yaml
coder:
  role: "Senior Developer"
  goal: "Code schreiben, debuggen, Shell-Befehle ausfuehren"
  backstory: "Erfahrener Entwickler mit Zugriff auf Shell und Dateisystem"
  llm: ollama_chat/gemma4:26b
  function_calling_llm: ollama_chat/gemma4:e4b
  max_iter: 10

web_designer:
  role: "UI/UX Designer"
  goal: "Moderne, responsive Web-Designs entwerfen"
  backstory: "Erfahrener Designer mit Fokus auf Clean UI und Tailwind CSS"
  llm: ollama_chat/gemma4:26b

web_coder:
  role: "Frontend Developer"
  goal: "Designs pixel-perfect in HTML/CSS/JS umsetzen"
  backstory: "Frontend-Spezialist fuer moderne Web-Standards"
  llm: ollama_chat/gemma4:26b
  function_calling_llm: ollama_chat/gemma4:e4b

researcher:
  role: "Web Researcher"
  goal: "Informationen finden, zusammenfassen, in Obsidian ablegen"
  backstory: "Recherche-Spezialist mit Web-Zugriff und Wissensdatenbank"
  llm: ollama_chat/gemma4:26b
  function_calling_llm: ollama_chat/gemma4:e4b
  max_iter: 8

swift_dev:
  role: "Swift Developer"
  goal: "SwiftUI Apps fuer iOS und macOS entwickeln"
  backstory: "Apple-Plattform-Spezialist mit SwiftUI und SwiftData Erfahrung"
  llm: ollama_chat/gemma4:26b
  function_calling_llm: ollama_chat/gemma4:e4b

ki_expert:
  role: "KI/ML Engineer"
  goal: "ML-Pipelines bauen, Modelle evaluieren, Prompt-Engineering"
  backstory: "KI-Spezialist mit Erfahrung in lokalen Modellen, Fine-Tuning und MLOps"
  llm: ollama_chat/gemma4:26b
  function_calling_llm: ollama_chat/gemma4:e4b

analyst:
  role: "Data Analyst"
  goal: "Daten analysieren, visualisieren und Reports erstellen"
  backstory: "Datenanalyst mit Python, Pandas und Visualisierungs-Expertise"
  llm: ollama_chat/gemma4:26b
  function_calling_llm: ollama_chat/gemma4:e4b

writer:
  role: "Technical Writer"
  goal: "Klare, strukturierte Texte und Dokumentation schreiben"
  backstory: "Technischer Redakteur mit Fokus auf verstaendliche Kommunikation"
  llm: ollama_chat/gemma4:26b

ops:
  role: "DevOps Engineer"
  goal: "Systeme verwalten, deployen, ueberwachen"
  backstory: "Ops-Spezialist mit Server- und Container-Erfahrung"
  llm: ollama_chat/gemma4:e4b

premium:
  role: "Senior AI Assistant"
  goal: "Komplexe Aufgaben loesen die lokale Modelle ueberfordern"
  backstory: "Premium-Agent mit Zugriff auf Claude und Gemini APIs"
  llm: anthropic/claude-sonnet-4-20250514
```

### Multi-Agent Crews
`WebDesignCrew` hat zwei Agents (Designer + Coder). CrewAI orchestriert sequenziell: Designer gibt Spec, Coder implementiert.

### Dynamische Erweiterung
Neue Crews = YAML-Eintrag + `@listen`-Handler im Flow. Kein Code-Umbau noetig.

### Quick-Reply vs. Crew-Dispatch
Nicht jede Nachricht braucht eine Crew. Die Rule-Engine entscheidet:
- **Quick-Reply (NativeOllamaClient, kein Crew-Overhead):** Gruss, Danke, kurze Ja/Nein-Fragen, Status-Abfragen, einfache Wissensfragen
- **Crew-Dispatch:** Alles was Tools braucht, laenger als 1 Antwort dauert, oder eine Aktion ausloest

Die Rule-Engine prueft zuerst auf Quick-Reply-Patterns (Regex). Nur wenn kein Match: weiter zu Crew-Keywords oder LLM-Classify.

### Crew-Routing Keywords

```python
CREW_KEYWORDS = {
    "web_design": ["website", "landing page", "html", "css", "tailwind", "responsive", "frontend"],
    "swift": ["swift", "swiftui", "ios", "macos", "xcode", "app store"],
    "ki_expert": ["modell", "training", "fine-tuning", "prompt", "embedding", "neural", "ml"],
    "analyst": ["daten", "csv", "statistik", "chart", "visualisierung", "analyse"],
    "coder": ["code", "python", "script", "debug", "fix", "implementier", "programmier"],
    "researcher": ["recherchier", "such", "find", "vergleich", "zusammenfass"],
    "writer": ["schreib", "text", "doku", "guide", "artikel", "zusammenfassung"],
    "ops": ["server", "docker", "deploy", "systemd", "backup", "update"],
}
```

---

## 3. Tool-Mapping

### Entscheidungstabelle

| Tool | Entscheidung | Ersatz |
|---|---|---|
| `web_surfer` | Ersetzen | CrewAI `SerperDevTool` + `ScrapeWebsiteTool` |
| `file_manager` | Ersetzen | CrewAI `FileReadTool` + `FileWriterTool` + `DirectoryReadTool` |
| `vision` | Ersetzen | CrewAI `VisionTool` (nutzt Gemma 4 multimodal via Ollama) |
| `code_executor` | Behalten + wrappen | Kein CrewAI-Aequivalent mit Sandbox |
| `shell_runner` | Behalten + wrappen | Restricted Shell mit Whitelist, sicherheitskritisch |
| `system_shell` | Behalten + wrappen | Unrestricted Shell, nur in OpsCrew |
| `obsidian_manager` | Behalten + wrappen | Wird SmartObsidianTool mit VaultIndex |
| `ollama_manager` | Behalten + wrappen | Falkenstein-spezifisch |
| `self_config` | Behalten + wrappen | Falkenstein-spezifisch |
| `ops_executor` | Behalten + wrappen | Custom Confirmation-Gate |
| `cli_bridge` | Entfernen | CrewAI native LLM-Provider (Anthropic/Google SDK) |

### Wrapper-Pattern

```python
from crewai.tools import BaseTool

class ObsidianManagerTool(BaseTool):
    name: str = "obsidian_manager"
    description: str = "Liest und schreibt Notizen in der Obsidian-Wissensbasis"

    def _run(self, action: str, path: str = "", content: str = "") -> str:
        return obsidian_manager.execute(action, path, content)
```

**Ergebnis:** 5 ersetzt, 6 gewrapped, 1 entfernt.

---

## 4. Callback-Bridge & Live-Dashboard

### FalkensteinEventBus

Zentrale Schicht zwischen CrewAI Callbacks und allen Ausgabe-Kanaelen:

```
CrewAI Callbacks -> EventBus -> WebSocket (Dashboard/Phaser)
                             -> Telegram (Sofort-Feedback + Streaming)
                             -> DB (crews/tasks/tool_log Tabellen)
```

### Callback-Ebenen

| Callback | Wann | Aktion |
|---|---|---|
| `before_kickoff` | Crew startet | Telegram: Bestaetigung / DB: Crew-Eintrag / WS: Agent spawnt |
| `step_callback` | Jeder Tool-Call | WS: Animation wechselt / Telegram: Zwischen-Update / DB: tool_log |
| `task_callback` | Task in Crew fertig | WS: Fortschritt / Telegram: "Schritt 1/3 fertig" |
| `after_kickoff` | Crew fertig | Telegram: Finale Antwort / DB: Status done / WS: Agent idle/weg |

### EventBus-Implementierung

```python
class FalkensteinEventBus:
    def __init__(self, ws_manager, telegram_bot, db):
        self.ws = ws_manager
        self.tg = telegram_bot
        self.db = db

    async def on_crew_start(self, crew_name, task_description, chat_id):
        await self.tg.send(chat_id, f"{crew_name} arbeitet: {task_description}")
        await self.db.create_crew(crew_name, status="active")
        await self.ws.broadcast({"type": "agent_spawn", "crew": crew_name})

    async def on_tool_call(self, agent_name, tool_name, result):
        await self.ws.broadcast({"type": "tool_use", "agent": agent_name, "tool": tool_name})
        if self.should_stream(tool_name):
            await self.tg.send(self.chat_id, f"{tool_name}: {truncate(result)}")
        await self.db.log_tool(agent_name, tool_name, result)

    async def on_crew_done(self, crew_name, result, chat_id):
        await self.tg.send(chat_id, result)
        await self.db.update_crew(crew_name, status="done")
        await self.ws.broadcast({"type": "agent_done", "crew": crew_name})
```

### Telegram-Streaming-Regeln
- **Immer streamen:** Web-Search Ergebnisse, Obsidian-Writes, Shell-Output
- **Nie streamen:** File-Reads, interne Zwischen-Schritte, classify
- **Nur bei langen Tasks (>30s):** Fortschritts-Updates

---

## 4b. Pixel Agents Assets & Animationen

### Von Pixel Agents uebernehmen (MIT-Lizenz)

| Asset/Konzept | Quelle | Verwendung |
|---|---|---|
| Character Sprites | `webview-ui/src/assets/` | Direkt uebernehmen oder als Vorlage |
| State Machine | `webview-ui/src/game/` | Konzept 1:1, an CrewAI Callbacks anpassen |
| Office Tiles | Floor, Walls, Furniture Sprites | An Phaser.js Grid anpassen |
| Furniture Manifest | `manifest.json` pro Asset-Folder | Modulares Furniture-System |
| BFS Pathfinding | Figuren-Bewegung | In Phaser.js Tiled-Map integrieren |

### State-Machine Mapping

| CrewAI Callback | Phaser Animation |
|---|---|
| Kein aktiver Task | Figur sitzt, atmet (idle) |
| tool_use: code/file/shell | Figur tippt am PC (typing) |
| tool_use: web/search/read | Figur schaut auf Monitor (reading) |
| crew_start / neuer Agent | Figur laeuft zum Schreibtisch (running) |
| LLM-Call laeuft (kein Tool) | Figur kratzt sich am Kopf (thinking) |
| on_crew_done / Ergebnis | Sprechblase mit Kurztext (speech_bubble) |
| Task erfolgreich | Figur springt (celebrating) |

### Tool-zu-Animation Mapping

```python
TOOL_TO_ANIMATION = {
    "code_executor": "typing",
    "shell_runner": "typing",
    "file_manager": "typing",
    "web_search": "reading",
    "scrape_website": "reading",
    "obsidian_manager": "reading",
    "vision": "thinking",
}
```

### Anpassungen
- **Grid-Size:** Pixel Agents 64x64 -> Falkenstein 48px (Assets skalieren oder Grid anpassen)
- **Multi-Agent:** Jede Crew bekommt eigenen Schreibtisch/Bereich
- **Crew-spezifische Skins:** Coder=Hoodie, Researcher=Brille, Writer=Stift, Ops=Werkzeug, KI-Expert=Roboter-Look
- **Buero-Layout:** Dev-Ecke, Research-Bibliothek, Ops-Serverraum

---

## 5. Obsidian — Zwei-Bereich-Architektur

### Vault-Struktur

```
Obsidian Vault/
+-- KI-Buero/                          <- Fuer den User sichtbar, organisiert
|   +-- Kanban.md
|   +-- Daily/
|   +-- Ideen/
|   +-- Recherchen/
|   +-- Guides/
|   +-- Code/
|   +-- Reports/
|   +-- Projekte/
|       +-- Falkenstein/
|
+-- Agenten-Wissensbasis/             <- Langzeitspeicher der Agents
    +-- Kontext/                      <- Fakten, Praeferenzen, Projekte
    +-- Gelerntes/                    <- Was Agents aus Tasks gelernt haben
    +-- Referenzen/                   <- Links, API-Docs, haeufig gebrauchte Infos
    +-- Fehler-Log/                   <- Was schiefging und warum
```

### VaultIndex — Vault-Awareness

```python
class VaultIndex:
    def __init__(self, vault_path: str):
        self.vault_path = vault_path
        self.structure = {}

    async def scan(self):
        """Scannt die Vault und baut Index auf."""

    def find_best_folder(self, content_type: str, topic: str) -> str:
        """Findet passenden Ordner. Legt NIEMALS eigene an."""

    def find_related_note(self, topic: str) -> Optional[str]:
        """Findet existierende Notiz zum Thema -> ergaenzen statt neu."""

    def as_context(self) -> str:
        """Vault-Struktur als Text fuer Agent-Prompt."""
```

### Drei Regeln fuer alle Agents
1. NIEMALS eigene Ordner anlegen. Nur bestehende Vault-Struktur nutzen.
2. Vor jedem Schreiben: VaultIndex pruefen ob passende Notiz existiert -> ergaenzen statt neu.
3. Ergebnisse fuer User -> KI-Buero/. Eigenes Wissen -> Agenten-Wissensbasis/.

### SmartObsidianTool

```python
class SmartObsidianTool(BaseTool):
    name = "obsidian"
    description = "Liest und schreibt in der Obsidian-Wissensbasis. Kennt die Vault-Struktur."

    def _run(self, action: str, content: str, topic: str = "") -> str:
        if action == "write_result":
            folder = self.vault_index.find_best_folder(self.crew_type, topic)
            existing = self.vault_index.find_related_note(topic)
            if existing:
                return self.append_to_note(existing, content)
            return self.create_note(folder, topic, content)

        elif action == "save_knowledge":
            category = self.classify_knowledge(content)
            folder = f"Agenten-Wissensbasis/{category}"
            return self.create_or_append(folder, topic, content)

        elif action == "read_context":
            return self.vault_index.get_relevant_context(topic)
```

### Crew-zu-Ordner Mapping

```python
CREW_TO_FOLDER = {
    "researcher":  "Recherchen",
    "writer":      "Guides",
    "coder":       "Code",
    "ki_expert":   "Recherchen",
    "analyst":     "Reports",
    "web_design":  "Code",
    "swift":       "Code",
    "ops":         "Reports",
}
```

### Kontext-Laden vor Crew-Start
Jede Crew bekommt relevanten Kontext aus der Agenten-Wissensbasis als Task-Context mitgegeben.

### Wissens-Extraktion nach Crew-Ende
Nach Abschluss: Crew wird gefragt ob etwas Gelerntes fuer zukuenftige Tasks nuetzlich ist -> automatisch in Agenten-Wissensbasis gespeichert.

---

## 6. Datenbankschema

### Tabellen

```sql
CREATE TABLE crews (
    id TEXT PRIMARY KEY,
    crew_type TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    trigger_source TEXT,
    chat_id TEXT,
    task_description TEXT,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    token_count INTEGER DEFAULT 0,
    result_path TEXT
);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    crew_id TEXT REFERENCES crews(id),
    description TEXT,
    status TEXT DEFAULT 'pending',
    sequence INTEGER,
    created_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    chat_id TEXT,
    role TEXT,
    content TEXT,
    crew_id TEXT,
    created_at TIMESTAMP
);

CREATE TABLE tool_log (
    id TEXT PRIMARY KEY,
    crew_id TEXT REFERENCES crews(id),
    agent_name TEXT,
    tool_name TEXT,
    tool_input TEXT,
    tool_output TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP
);

CREATE TABLE knowledge_log (
    id TEXT PRIMARY KEY,
    crew_id TEXT REFERENCES crews(id),
    vault_path TEXT,
    knowledge_type TEXT,
    topic TEXT,
    created_at TIMESTAMP
);
```

### Migration
Einmalig per SQL-Script. Alte `agents`-Eintraege -> `crews`. Token-Tracking via Ollama `prompt_eval_count` + `eval_count`.

---

## 7. Projektstruktur

```
backend/
+-- main.py                          <- FastAPI App (bleibt, angepasst)
+-- config.py                        <- pydantic-settings (bleibt)
+-- database.py                      <- aiosqlite (neues Schema)
+-- event_bus.py                     <- NEU: FalkensteinEventBus
+-- vault_index.py                   <- NEU: Obsidian VaultIndex
|
+-- flow/
|   +-- falkenstein_flow.py          <- NEU: CrewAI Flow (ersetzt main_agent.py)
|   +-- rule_engine.py              <- NEU: Regex/Keyword-Router
|
+-- crews/
|   +-- base_crew.py                <- NEU: Gemeinsame Crew-Config
|   +-- coder_crew.py
|   +-- researcher_crew.py
|   +-- writer_crew.py
|   +-- ops_crew.py
|   +-- web_design_crew.py
|   +-- swift_crew.py
|   +-- ki_expert_crew.py
|   +-- analyst_crew.py
|   +-- premium_crew.py
|
+-- config/
|   +-- agents.yaml                 <- NEU: CrewAI Agent-Definitionen
|   +-- tasks.yaml                  <- NEU: CrewAI Task-Templates
|
+-- tools/
|   +-- crewai_wrappers.py         <- NEU: BaseTool-Wrapper
|   +-- code_executor.py            <- Bleibt (gewrapped)
|   +-- shell_runner.py             <- Bleibt (gewrapped)
|   +-- system_shell.py             <- Bleibt (gewrapped)
|   +-- obsidian_manager.py         <- Bleibt (wird SmartObsidianTool)
|   +-- ollama_manager.py           <- Bleibt (gewrapped)
|   +-- self_config.py              <- Bleibt (gewrapped)
|   +-- ops_executor.py             <- Bleibt (gewrapped)
|
+-- telegram/
|   +-- bot.py                      <- Bleibt (ruft Flow statt MainAgent)
|
+-- websocket/
    +-- manager.py                  <- Bleibt (empfaengt von EventBus)

frontend/
+-- assets/
|   +-- pixel-agents/              <- Geforkte Assets von Pixel Agents
+-- src/
    +-- ...                         <- Phaser-Code, angepasst an neue WS-Events
```

### Dateien die geloescht werden
- `main_agent.py` (-> flow/falkenstein_flow.py)
- `sub_agent.py` (-> crews/)
- `dynamic_agent.py` (-> crews/)
- `llm_client.py` (-> CrewAI LLM() + NativeOllamaClient)
- `llm_router.py` (-> Flow-Router + agents.yaml)
- `intent_engine.py` (-> rule_engine.py + classify im Flow)
- `tools/web_surfer.py` (-> CrewAI SerperDevTool)
- `tools/file_manager.py` (-> CrewAI FileReadTool/FileWriterTool)
- `tools/vision.py` (-> CrewAI VisionTool)
- `tools/cli_bridge.py` (-> CrewAI native LLM-Provider)

---

## 8. Native Ollama-Anbindung

### Zwei Ebenen

**Ebene 1: CrewAI Crews** nutzen Ollama via `/v1/chat/completions` (OpenAI-kompatibel) mit nativen Tool-Calls.

**Ebene 2: NativeOllamaClient** fuer schnelle Einzelcalls ohne Crew-Overhead:

```python
class NativeOllamaClient:
    def __init__(self, host, model_light, model_heavy):
        self.host = host
        self.model_light = model_light  # gemma4:e4b
        self.model_heavy = model_heavy  # gemma4:26b

    async def classify(self, message: str) -> dict:
        """Structured Output mit e4b — erzwingt JSON-Schema."""
        response = await self._chat(
            model=self.model_light,
            messages=[{"role": "user", "content": message}],
            format={
                "type": "object",
                "properties": {
                    "crew_type": {"type": "string", "enum": [
                        "coder", "researcher", "writer", "ops",
                        "web_design", "swift", "ki_expert", "analyst"
                    ]},
                    "task_description": {"type": "string"},
                    "priority": {"type": "string", "enum": ["normal", "premium"]}
                },
                "required": ["crew_type", "task_description"]
            }
        )
        return json.loads(response)

    async def quick_reply(self, message: str, context: str = "") -> str:
        """Direkte Antwort ohne Crew fuer einfache Fragen."""
        return await self._chat(
            model=self.model_light,
            messages=[
                {"role": "system", "content": context},
                {"role": "user", "content": message}
            ]
        )

    async def _chat(self, model, messages, format=None, tools=None):
        """Async Ollama Call ueber httpx."""
        async with httpx.AsyncClient() as client:
            payload = {"model": model, "messages": messages, "stream": False}
            if format:
                payload["format"] = format
            if tools:
                payload["tools"] = tools
            r = await client.post(f"{self.host}/api/chat", json=payload)
            return r.json()["message"]["content"]
```

### Gemma 4 Native Features

| Feature | Vorher | Nachher |
|---|---|---|
| Tool-Calling | Ignoriert, Prompt-Hacking | Nativ ueber `tools`-Parameter |
| Structured Output | Regex-Parsing | `format`-Parameter erzwingt JSON-Schema |
| Vision | Eigenes Tool mit extra Call | Direkt im Chat: Bild als Base64 |
| Thinking | `<think>`-Tags manuell gestrippt | `think: true/false` je nach Bedarf |
| Parallel Tool-Calls | 1 Tool pro ReAct-Step | Mehrere Tools gleichzeitig |

### Ollama Performance-Config

```python
class OllamaSettings(BaseSettings):
    host: str = "http://localhost:11434"
    model_light: str = "gemma4:e4b"
    model_heavy: str = "gemma4:26b"
    keep_alive: str = "30m"           # Modell im RAM halten
    num_ctx: int = 8192               # Context fuer Light
    num_ctx_heavy: int = 32768        # Context fuer Heavy
    stream_tools: bool = False        # Streaming Bug mit Gemma 4 Tool-Calls
    stream_text: bool = True
```

### Bekannte Caveats (als Defaults eingebaut)
- `stream: false` bei Tool-Calls (Streaming + Gemma 4 Thinking = Parser-Bug)
- `think: true` wenn `format` benutzt wird (`think: false` + `format` = Bug, Ollama Issue #15260)
- `keep_alive: 30m` damit Modell nicht bei jedem Call neu geladen wird

### Call-Routing

```
Telegram-Nachricht
    |
    +-- Rule-Engine matched? -> NativeOllamaClient.quick_reply() [kein Crew-Overhead]
    |                           oder direkt zur Crew
    |
    +-- Kein Match? -> NativeOllamaClient.classify() [e4b, structured output, ~200ms]
    |
    +-- Crew-Type bekannt -> CrewAI Crew kickoff [26b + e4b dispatch, native tools]
```

### Was wegfaellt
- `llm_client.py` komplett
- `CLILLMClient` mit String-Parsing
- Alles ReAct-Prompt-Engineering
- Manuelles `<think>`-Tag Stripping

---

## Abhaengigkeiten

### Neue Python-Packages
```
crewai                    # Core Agent Framework
crewai[tools]             # Nur benoetigte: SerperDevTool, ScrapeWebsiteTool, FileReadTool, etc.
httpx                     # Async Ollama Client (ersetzt synchronen ollama-Client)
```

### Entfernte Packages
```
ollama                    # Ersetzt durch httpx + Ollama REST API direkt
```

### Externe Voraussetzungen
- Ollama >= v0.20.0 (Gemma 4 Tool-Calling Support)
- Gemma 4 Modelle: `ollama pull gemma4:e4b` + `ollama pull gemma4:26b`
- SerperDev API Key (fuer Web-Search Tool, in .env)
