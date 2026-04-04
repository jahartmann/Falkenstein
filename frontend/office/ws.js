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
      const msg = JSON.parse(e.data);
      this._dispatch(msg);
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
        break;

      case 'agent_done':
        this.bm.showBubble(msg.agent_id, '\u2705 Fertig!');
        setTimeout(() => this.am.removeAgent(msg.agent_id), 3000);
        break;

      case 'agent_error':
        this.bm.showBubble(msg.agent_id, '\u274C Fehler!');
        setTimeout(() => this.am.removeAgent(msg.agent_id), 3000);
        break;

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
      const id = a.agent_id || a.id || `agent-${Math.random().toString(36).slice(2, 8)}`;
      if (!this.am.agents.has(id)) {
        this.am.spawnAgent(id, a.agent_type || a.type || 'coder', a.task || '');
      }
    }
    const activeIds = new Set(agents.map(a => a.agent_id || a.id));
    for (const id of this.am.agents.keys()) {
      if (id === 'main-agent') continue;
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
