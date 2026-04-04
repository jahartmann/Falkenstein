# Pixel-Büro — Design Spec

## Überblick

Interaktive Pixel-Art Büro-Visualisierung mit Phaser.js. Zeigt Agents als Charaktere die durch ein Tiled-Büro laufen, an Schreibtischen arbeiten und Pausen machen. Der Spieler steuert einen eigenen Charakter (Hybrid: WASD + Zoom-Out für Übersicht). Interaktive Objekte (Whiteboard, Monitore, Schedule-Tafel etc.) zeigen Live-Daten vom Backend. Öffnet sich als eigener Browser-Tab via Sidebar-Button im Dashboard.

## Vorhandene Assets

- **Tiled Map:** `frontend/assets/office.tmj` — 60×48 Tiles, 48px
  - Layer: Walkable, Blocked, Furniture, WalkableFurniture, Stühle
  - Object-Layer "Benamung": 9 benannte Räume mit Positionen
  - Object-Layer "Arbeitsplätze": 15 Desk-Objekte
- **Tilesets (48px):**
  - `Room_Builder_Office_48x48.png` (firstgid: 1, 224 tiles)
  - `Modern_Office_Black_Shadow.png` (firstgid: 225, 85 tiles)
  - `Modern_Office_Black_Shadow_48x48.png` (firstgid: 310, 848 tiles)
- **Character Sprites (16×16):** Adam, Alex, Amelia, Bob — jeweils idle/run/sit/phone Spritesheets
- **Zusätzliche Chars:** char_0 bis char_5

### Tileset-Pfad-Fix

Die TMJ referenziert `../Modern_Office_Revamped_v1/...`. Für Phaser müssen die Tilesets manuell geladen und die Pfade auf `/static/assets/` gemappt werden, oder die TMJ wird angepasst.

**Entscheidung:** TMJ-Pfade beim Laden im Code umschreiben (nicht die Datei ändern, damit Tiled-Kompatibilität erhalten bleibt).

## Architektur

### Dateien

| Datei | Zweck |
|-------|-------|
| `frontend/office.html` | Eigenständige HTML-Seite, lädt Phaser.js + office.js |
| `frontend/office.js` | Phaser-Game: Scenes, Entities, UI |
| `frontend/office.css` | HUD-Styling, Popup-Panels |
| `backend/main.py` | Neue Route `GET /office` → serviert office.html |

### Keine neuen Backend-Abhängigkeiten

Das Büro nutzt den bestehenden WebSocket (`/ws`) und die Admin-API (`/api/admin/*`). Kein neuer Backend-Code nötig außer der Route.

## Steuerung (Hybrid)

### Nahansicht (Standard)
- WASD / Pfeiltasten bewegen den Spieler-Charakter
- Kamera folgt dem Charakter mit Smooth-Follow
- Leertaste / E-Taste interagiert mit nahegelegenen Objekten
- Mausklick auf Agents zeigt deren Info

### Fernansicht (Zoom-Out)
- Mausrad zoomt raus (max 0.5x) / rein (max 2x)
- Ab Zoom < 0.8x: Klick-Interaktion statt WASD
- Klick auf beliebigen Punkt: Kamera fährt hin
- Klick auf Agent/Objekt: öffnet Popup-Panel

## Agents

### Darstellung
- Jeder Agent-Typ bekommt einen festen Character-Sprite zugewiesen:
  - `coder` → Adam
  - `researcher` → Alex
  - `writer` → Amelia
  - `ops` → Bob
  - MainAgent → char_0 (immer im Büro Boss-Raum)
  - Spieler → char_1
- Sprites sind 16×16, werden 3× skaliert auf 48px (passend zu Tile-Größe)

### Raum-Zuordnung

| Raum | Agent-Typ | Beschreibung |
|------|-----------|-------------|
| Büro Boss | MainAgent | Immer besetzt, sitzt am Schreibtisch |
| Team Büro | coder | Mehrere Arbeitsplätze |
| Deep-Dive 1 | researcher | Einzelarbeitsplatz |
| Deep-Dive 2 | researcher | Einzelarbeitsplatz |
| Fokus-Büro | writer | Ruhiger Bereich |
| Teamleitung | ops | Ops-Zentrale |
| Küche | — | Pausen-Ziel |
| Lounge | — | Pausen-Ziel |
| Gemeinschaftsraum | — | Whiteboard-Standort |

### Lebenszyklus eines Agents

1. **Spawn:** Backend sendet `agent_started` via WS → Agent-Sprite erscheint an der Eingangstür (unterer Kartenrand)
2. **Zum Arbeitsplatz:** A*-Pathfinding zum passenden Raum, wählt freien Arbeitsplatz (aus "Arbeitsplätze"-Layer)
3. **Arbeiten:** Sprite wechselt auf `sit`-Animation. Sprechblase zeigt aktuelle Aufgabe (gekürzt, max 30 Zeichen)
4. **Pausen-Verhalten:** Zufällig alle 15-30s (Spielzeit) steht Agent auf und läuft zu:
   - Küche (Kaffeemaschine)
   - Lounge (setzt sich kurz hin)
   - Gemeinschaftsraum (steht am Whiteboard)
   - Telefoniert am Platz (`phone`-Animation)
   - Nach 5-10s zurück zum Arbeitsplatz
5. **Fertig:** Backend sendet `agent_finished` → Agent steht auf, läuft zur Tür, Sprite wird entfernt

### Pathfinding

- A*-Algorithmus auf dem "Blocked"-Layer (Tile-ID > 0 = blockiert)
- "Walkable"-Layer definiert begehbare Flächen
- Grid-basiert (60×48), ein Pfad-Node pro Tile
- Agents weichen einander aus (kein Stacking auf selber Tile)
- Bibliothek: `easystarjs` (klein, bewährt für Phaser) oder eigene A*-Implementierung

## Interaktive Objekte

Alle Objekte haben einen Interaktionsradius (2 Tiles). Nahansicht: E-Taste wenn in Reichweite. Fernansicht: Klick.

### 1. Whiteboard / Kanban-Board

- **Position:** Gemeinschaftsraum (Wand)
- **Daten:** `GET /api/admin/tasks` — offene Tasks
- **Panel:** Kanban-Spalten (Open → In Progress → Done). Tasks als Pixel-Post-Its mit Farbe je Status. Klick auf Post-It zeigt Detail. Button "Neuer Task" erstellt Task.
- **Live-Update:** WS `task_created`, `task_updated` Events

### 2. Agent-Monitore

- **Position:** Jeder besetzte Schreibtisch
- **Daten:** Agent-Status aus WS `state_update`
- **Panel:** Zeigt aktuellen Task, genutztes Tool, Fortschritt, Laufzeit. Scrollbare Tool-Log-Liste.
- **Visuell:** Monitor-Tile am Schreibtisch leuchtet grün wenn Agent aktiv

### 3. Schedule-Tafel

- **Position:** Neben der Eingangstür (Flur)
- **Daten:** `GET /api/admin/schedules`
- **Panel:** Liste der nächsten Schedule-Runs sortiert nach Zeit. Zeigt Name, Agent-Typ, nächster Run, Countdown. Ähnlich Abfahrtstafel.
- **Live-Update:** WS `schedule_fired` Event

### 4. Sprechblasen

- **Kein Popup-Panel** — direkt über Agent-Sprites
- **Inhalt:** Kurzer Status-Text, max 30 Zeichen
- **Trigger:**
  - Agent startet Task → "Recherchiere..."
  - Agent nutzt Tool → "🔍 Web-Suche..."
  - Agent fertig → "✅ Fertig!"
  - Agent Fehler → "❌ Fehler!"
- **Auto-Hide:** Nach 5 Sekunden ausblenden, bei neuem Event ersetzen

### 5. Kaffeemaschine

- **Position:** Küche
- **Panel:** System-Stats als "Kaffee-Bon":
  - Uptime
  - Tasks heute (gesamt / erfolgreich / fehlgeschlagen)
  - Aktive Agents gerade
  - Letzter Task abgeschlossen
- **Fun:** Brüh-Animation (2s) bevor Stats angezeigt werden

### 6. Telegram-Briefkasten

- **Position:** Eingangstür
- **Daten:** Letzte Telegram-Messages (falls verfügbar über API)
- **Panel:** Chat-Ansicht der letzten Nachrichten. Falls keine Telegram-API verfügbar: zeigt Activity-Feed stattdessen.
- **Visuell:** Briefkasten-Flag geht hoch wenn neue Nachricht da ist

## HUD (Head-Up Display)

### Obere Leiste
- Links: "Falkenstein Büro" Label
- Mitte: Aktive Agents (Zahl + kleine Sprite-Icons), offene Tasks, aktive Schedules
- Rechts: WebSocket-Status (grün/rot), Zoom-Level

### Minimap (unten-rechts)
- Kleine Übersichtskarte des gesamten Büros (ca. 150×120px)
- Zeigt Spieler-Position (blauer Punkt)
- Zeigt Agent-Positionen (farbige Punkte je Typ)
- Klick auf Minimap teleportiert Kamera

### Popup-Panels
- Pixel-Art Rahmen (passend zum Büro-Stil)
- Dunkler semi-transparenter Hintergrund
- Schließbar mit X-Button oder ESC
- Maximal 1 Panel gleichzeitig offen
- Position: zentriert über dem Spiel

## WebSocket-Events (bestehend, genutzt)

| Event | Auslöser | Büro-Aktion |
|-------|----------|-------------|
| `full_state` | Verbindungsaufbau | Alle aktiven Agents platzieren |
| `state_update` | Agent-Statusänderung | Sprechblase aktualisieren, Monitor updaten |
| `task_created` | Neuer Task | Post-It ans Whiteboard, Notification |
| `schedule_fired` | Schedule ausgelöst | Schedule-Tafel updaten, Agent spawnt |
| `sub_agent_progress` | SubAgent arbeitet | Sprechblase + Monitor-Update |

## Phaser.js Scene-Struktur

```
OfficeGame
├── BootScene          — Lädt alle Assets (Tilesets, Sprites, TMJ)
├── OfficeScene        — Hauptszene: Map, Spieler, Agents, Objekte
│   ├── TilemapManager — Lädt TMJ, erstellt Layer, Kollisionen
│   ├── PlayerEntity   — Spieler-Charakter, Input, Kamera
│   ├── AgentManager   — Spawnt/entfernt Agents, Pathfinding
│   ├── ObjectManager  — Interaktive Objekte, Proximity-Check
│   └── BubbleManager  — Sprechblasen über Agents
└── UIScene            — Parallel-Szene: HUD, Minimap, Panels (DOM-basiert)
```

## Technische Details

### Phaser-Config
- Renderer: Canvas (Pixel-Art, kein Anti-Aliasing)
- Größe: Fenster-Füllend (responsive)
- Pixel-Art: `pixelArt: true`, `roundPixels: true`
- Physics: Arcade (für einfache Kollision Spieler ↔ Wände)

### Tile-Kollision
- "Blocked"-Layer: alle Tiles mit ID > 0 sind Kollisions-Tiles
- Phaser `setCollisionByExclusion([-1, 0])` auf Blocked-Layer
- Spieler kollidiert mit Blocked-Layer via Arcade Physics

### Character-Animation
- 16×16 Sprites, frameWidth: 16, frameHeight: 16
- Skalierung: `setScale(3)` → 48px
- Animationen:
  - `idle` (idle_anim Spritesheet, ~6 Frames, 8 FPS)
  - `run` (run Spritesheet, ~6 Frames, 10 FPS)
  - `sit` (sit Spritesheet, statisch oder 2 Frames)
  - `phone` (phone Spritesheet, ~4 Frames, 6 FPS)

### Pathfinding-Implementierung
- Eigene A*-Implementierung (kein externes Paket nötig)
- Grid aus Blocked-Layer extrahieren beim Scene-Start
- Agent bewegt sich Tile-für-Tile mit Tween (200ms pro Tile)
- Bei Pfad-Blockade (anderer Agent): 500ms warten, Pfad neu berechnen

### WebSocket-Integration
- Gleiche WS-Verbindung wie Dashboard (`ws://host:8080/ws`)
- Events dispatchen an AgentManager und ObjectManager
- Reconnect-Logic mit Backoff (wie dashboard.js)

## Scope-Abgrenzung

**In Scope:**
- Büro-Rendering mit Tiled-Map
- Spieler-Steuerung (WASD + Zoom)
- Agent-Lifecycle (Spawn → Arbeiten → Pausen → Exit)
- 6 interaktive Objekte mit Popup-Panels
- HUD + Minimap
- WebSocket-Integration für Live-Updates

**Out of Scope:**
- Multiplayer (nur 1 Spieler)
- Speichern von Spieler-Position
- Sound/Musik
- Anpassbare Charakter-Skins
- Chat im Büro
