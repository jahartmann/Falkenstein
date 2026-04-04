export class PanelManager {
  constructor() {
    this.overlay = document.getElementById('panel-overlay');
    this.content = document.getElementById('panel-content');
    this.currentPanel = null;
    this._onKeydown = (e) => { if (e.key === 'Escape') this.close(); };
  }

  create() {
    document.addEventListener('keydown', this._onKeydown);
    window.panelManager = this;
    return this;
  }

  open(title, htmlContent) {
    this.content.innerHTML = `
      <button class="panel-close" onclick="window.panelManager.close()">&times;</button>
      <h2>${title}</h2>
      ${htmlContent}
    `;
    this.overlay.classList.remove('hidden');
    this.currentPanel = title;
  }

  close() {
    this.overlay.classList.add('hidden');
    this.currentPanel = null;
  }

  isOpen() {
    return this.currentPanel !== null;
  }
}
