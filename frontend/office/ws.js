/* ── Activity Feed ── */

const feedEntries = [];
const FEED_MAX = 8;
let feedFadeTimer = null;

function addFeedEntry(icon, text) {
  const time = new Date().toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
  feedEntries.unshift({ icon, text, time });
  if (feedEntries.length > FEED_MAX) feedEntries.pop();
  const el = document.getElementById('feed-entries');
  if (el) el.innerHTML = feedEntries.map(e =>
    `<div class="feed-entry"><span class="feed-time">${e.time}</span><span>${e.icon} ${e.text}</span></div>`
  ).join('');
  const feed = document.getElementById('activity-feed');
  if (feed) {
    feed.classList.remove('faded');
    clearTimeout(feedFadeTimer);
    feedFadeTimer = setTimeout(() => feed.classList.add('faded'), 10000);
  }
}

export class OfficeWS {
  constructor(agentManager, bubbleManager, hud) {
    this.am = agentManager;
    this.bm = bubbleManager;
    this.hud = hud;
    this.ws = null;
  }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(proto + '//' + location.host + '/ws');

    this.ws.onopen = () => {
      this.hud.setWSConnected(true);
    };

    this.ws.onclose = () => {
      this.hud.setWSConnected(false);
      setTimeout(() => this.connect(), 3000);
    };

    this.ws.onerror = () => this.ws.close();

    this.ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        this._dispatch(msg);
      } catch (err) {
        console.warn('WS parse error:', err);
      }
    };
  }

  _dispatch(msg) {
    const type = msg.type || '';

    switch (type) {
      case 'full_state':
        this._handleFullState(msg);
        break;

      case 'agent_spawned':
        this.am.spawnAgent(msg.agent_id, msg.agent_type || 'coder', msg.task || '');
        this.bm.showBubble(msg.agent_id, msg.task || 'Gestartet...');
        addFeedEntry('🤖', (msg.agent_type || 'Agent') + ' gestartet');
        break;

      // CrewAI EventBus events (flat format — no data wrapper)
      case 'agent_spawn': {
        const crew = msg.crew || msg.crew_id || 'Agent';
        this.am.onAgentSpawn(msg.crew, msg.crew_id, msg.task || '');
        this.bm.showBubble(msg.crew_id, msg.task || 'Gestartet...');
        addFeedEntry('🤖', crew + ' gestartet');
        break;
      }

      case 'tool_use': {
        const toolName = msg.tool || msg.tool_name || '';
        let bubbleText = msg.tool_name || msg.label || toolName;
        if (bubbleText.startsWith('mcp_')) {
          const icons = { reminder: '⏰', calendar: '📅', music: '🎵', homekit: '💡', note: '📝', shell: '💻' };
          for (const [key, icon] of Object.entries(icons)) {
            if (bubbleText.includes(key)) { bubbleText = `${icon} ${bubbleText.split('_').pop()}`; break; }
          }
        }
        this.am.onToolUse(msg.agent, toolName, msg.animation, msg.crew_id);
        addFeedEntry('🔧', toolName || bubbleText);
        break;
      }

      // Legacy agent_done/agent_error (with agent_id) handled above.
      // CrewAI crew events use crew_id — check for it:
      case 'agent_done': {
        const crew = msg.crew || msg.crew_id || 'Agent';
        if (msg.crew_id) {
          this.bm.showBubble(msg.crew_id, '\u2705 Fertig!');
          this.am.onAgentDone(msg.crew, msg.crew_id);
        } else {
          this.bm.showBubble(msg.agent_id, '\u2705 Fertig!');
          setTimeout(() => this.am.removeAgent(msg.agent_id), 3000);
        }
        addFeedEntry('✅', crew + ' fertig');
        break;
      }

      case 'agent_error': {
        const crew = msg.crew || msg.crew_id || 'Agent';
        if (msg.crew_id) {
          this.bm.showBubble(msg.crew_id, '\u274C ' + (msg.error || 'Fehler!'));
          this.am.onAgentError(msg.crew, msg.crew_id, msg.error);
        } else {
          this.bm.showBubble(msg.agent_id, '\u274C Fehler!');
          setTimeout(() => this.am.removeAgent(msg.agent_id), 3000);
        }
        addFeedEntry('❌', crew + ' Fehler');
        break;
      }

      case 'agent_progress':
        this.am.updateAgentStatus(msg.agent_id, msg.label || msg.tool || '');
        this.bm.showBubble(msg.agent_id, msg.label || `\uD83D\uDD27 ${msg.tool || '...'}`);
        break;

      case 'task_created':
        this._refreshTaskCount();
        break;

      case 'schedule_fired':
        this._refreshScheduleCount();
        break;

      case 'state_update':
        this._handleFullState(msg);
        break;
    }
  }

  _handleFullState(msg) {
    const agents = msg.active_agents || [];
    for (const a of agents) {
      const id = a.agent_id || a.id;
      if (!id) continue;
      if (!this.am.agents.has(id)) {
        this.am.spawnAgent(id, a.agent_type || a.type || 'coder', a.task || '');
      }
    }
    const activeIds = new Set(agents.map(a => a.agent_id || a.id));
    for (const id of this.am.agents.keys()) {
      if (id.startsWith('npc-')) continue;
      if (!activeIds.has(id)) {
        this.am.removeAgent(id);
      }
    }
    this._refreshTaskCount();
    this._refreshScheduleCount();
  }

  async _refreshTaskCount() {
    try {
      const res = await fetch('/api/admin/tasks?status=open&limit=1');
      const data = await res.json();
      this.hud.updateTaskCount(data.total || 0);
    } catch (_) {}
  }

  async _refreshScheduleCount() {
    try {
      const res = await fetch('/api/admin/schedules');
      const data = await res.json();
      const active = (data.tasks || []).filter(s => s.active).length;
      this.hud.updateScheduleCount(active);
    } catch (_) {}
  }
}
