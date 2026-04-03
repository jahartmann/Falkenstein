class FalkensteinWS {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.handlers = {};
        this.reconnectDelay = 2000;
    }

    connect() {
        this.ws = new WebSocket(this.url);
        this.ws.onopen = () => {
            console.log('WS connected');
            this.emit('connected');
        };
        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.emit(data.type, data);
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };
        this.ws.onerror = (err) => {
            console.error('WS error:', err);
        };
        this.ws.onclose = () => {
            console.log('WS closed, reconnecting...');
            setTimeout(() => this.connect(), this.reconnectDelay);
        };
    }

    on(type, handler) {
        if (!this.handlers[type]) this.handlers[type] = [];
        this.handlers[type].push(handler);
    }

    emit(type, data) {
        const handlers = this.handlers[type] || [];
        handlers.forEach(h => h(data));
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        }
    }

    submitTask(title, description, project) {
        this.send({ type: 'submit_task', title, description, project });
    }
}
