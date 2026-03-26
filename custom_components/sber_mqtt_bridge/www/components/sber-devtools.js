/**
 * Sber MQTT Bridge — DevTools component for MQTT protocol debugging.
 *
 * Three collapsible sections:
 * 1. Raw Config Payload — JSON sent to up/config
 * 2. Raw State Payload — JSON sent to up/status
 * 3. MQTT Message Log — real-time ring buffer of last 50 messages
 */

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

class SberDevtools extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _configPayload: { type: String },
      _statesPayload: { type: String },
      _messages: { type: Array },
      _configLoading: { type: Boolean },
      _statesLoading: { type: Boolean },
      _logLoading: { type: Boolean },
      _configError: { type: String },
      _statesError: { type: String },
      _logError: { type: String },
      _configOpen: { type: Boolean },
      _statesOpen: { type: Boolean },
      _configEditable: { type: String },
      _statesEditable: { type: String },
      _sendingConfig: { type: Boolean },
      _sendingStates: { type: Boolean },
    };
  }

  constructor() {
    super();
    this._configPayload = "";
    this._statesPayload = "";
    this._messages = [];
    this._configLoading = false;
    this._statesLoading = false;
    this._logLoading = false;
    this._configError = "";
    this._statesError = "";
    this._logError = "";
    this._hassReady = false;
    this._configOpen = false;
    this._statesOpen = false;
    this._configEditable = "";
    this._statesEditable = "";
    this._sendingConfig = false;
    this._sendingStates = false;
    this._msgUnsub = null;
  }

  connectedCallback() {
    super.connectedCallback();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsubscribeMessages();
  }

  updated(changedProps) {
    if (changedProps.has("hass") && this.hass && !this._hassReady) {
      this._hassReady = true;
      this._subscribeMessages();
    }
  }

  async _subscribeMessages() {
    if (this._msgUnsub) return;
    try {
      this._msgUnsub = await this.hass.connection.subscribeMessage(
        (event) => {
          if (event.snapshot) {
            this._messages = event.snapshot;
          } else if (event.message) {
            this._messages = [...this._messages, event.message];
          }
        },
        { type: "sber_mqtt_bridge/subscribe_messages" }
      );
    } catch (e) {
      this._logError = e.message || String(e);
    }
  }

  _unsubscribeMessages() {
    if (this._msgUnsub) {
      this._msgUnsub();
      this._msgUnsub = null;
    }
  }

  /* ---------- data ---------- */

  async _loadConfig() {
    this._configLoading = true;
    this._configError = "";
    try {
      const result = await this.hass.callWS({ type: "sber_mqtt_bridge/raw_config" });
      this._configPayload = this._formatJson(result.payload);
      this._configEditable = this._configPayload;
      this._configOpen = true;
    } catch (e) {
      this._configError = e.message || String(e);
    } finally {
      this._configLoading = false;
    }
  }

  async _loadStates() {
    this._statesLoading = true;
    this._statesError = "";
    try {
      const result = await this.hass.callWS({ type: "sber_mqtt_bridge/raw_states" });
      this._statesPayload = this._formatJson(result.payload);
      this._statesEditable = this._statesPayload;
      this._statesOpen = true;
    } catch (e) {
      this._statesError = e.message || String(e);
    } finally {
      this._statesLoading = false;
    }
  }

  async _fetchLog() {
    if (!this.hass) return;
    try {
      const result = await this.hass.callWS({ type: "sber_mqtt_bridge/message_log" });
      this._messages = result.messages || [];
      this._logError = "";
    } catch (e) {
      this._logError = e.message || String(e);
    }
  }

  async _clearLog() {
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/clear_message_log" });
      this._messages = [];
      this._logError = "";
    } catch (e) {
      this._logError = e.message || String(e);
    }
  }

  async _sendConfig() {
    this._sendingConfig = true;
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/send_raw_config", payload: this._configEditable });
      this._toast("Config sent to Sber", "success");
    } catch (e) {
      this._toast("Send failed: " + (e.message || e), "error");
    } finally {
      this._sendingConfig = false;
    }
  }

  async _sendStates() {
    this._sendingStates = true;
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/send_raw_state", payload: this._statesEditable });
      this._toast("States sent to Sber", "success");
    } catch (e) {
      this._toast("Send failed: " + (e.message || e), "error");
    } finally {
      this._sendingStates = false;
    }
  }

  /* ---------- helpers ---------- */

  _formatJson(str) {
    try {
      return JSON.stringify(JSON.parse(str), null, 2);
    } catch {
      return str;
    }
  }

  _copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        () => this._toast("Copied to clipboard", "success"),
        () => this._fallbackCopy(text),
      );
    } else {
      this._fallbackCopy(text);
    }
  }

  _fallbackCopy(text) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      this._toast("Copied to clipboard", "success");
    } catch {
      this._toast("Copy failed", "error");
    }
    document.body.removeChild(ta);
  }

  _toast(message, type) {
    this.dispatchEvent(new CustomEvent("devtools-toast", {
      bubbles: true, composed: true,
      detail: { message, type },
    }));
  }

  _formatTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("en-GB", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" })
      + "." + String(d.getMilliseconds()).padStart(3, "0");
  }

  _truncate(str, maxLen = 120) {
    if (!str) return "";
    return str.length > maxLen ? str.substring(0, maxLen) + "..." : str;
  }

  /* ---------- styles ---------- */

  static get styles() {
    return css`
      :host {
        display: block;
      }

      .section {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0, 0, 0, 0.1));
        padding: 16px;
        margin-bottom: 16px;
      }

      .section-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
      }

      .section-header h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 500;
      }

      .section-title {
        display: flex;
        align-items: center;
        gap: 8px;
        cursor: pointer;
        user-select: none;
      }

      .collapse-icon {
        transition: transform 0.2s;
        font-size: 18px;
        color: var(--secondary-text-color);
      }

      .collapse-icon.open {
        transform: rotate(90deg);
      }

      .btn-group {
        display: flex;
        gap: 8px;
      }

      button {
        padding: 6px 16px;
        border: none;
        border-radius: 6px;
        cursor: pointer;
        font-size: 13px;
        font-weight: 500;
        transition: background 0.2s, opacity 0.2s;
      }

      button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }

      .btn-primary {
        background: var(--primary-color, #03a9f4);
        color: #fff;
      }

      .btn-primary:hover:not(:disabled) {
        opacity: 0.85;
      }

      .btn-secondary {
        background: var(--secondary-background-color, #e0e0e0);
        color: var(--primary-text-color);
      }

      .btn-secondary:hover:not(:disabled) {
        opacity: 0.85;
      }

      .btn-danger {
        background: var(--error-color, #f44336);
        color: #fff;
      }

      .btn-danger:hover:not(:disabled) {
        opacity: 0.85;
      }

      .json-viewer {
        background: #1e1e1e;
        color: #d4d4d4;
        border-radius: 8px;
        padding: 12px;
        overflow-x: auto;
        max-height: 500px;
        overflow-y: auto;
        font-family: "Fira Code", "Consolas", "Monaco", monospace;
        font-size: 12px;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-all;
      }

      .json-editor {
        width: 100%;
        min-height: 120px;
        max-height: 300px;
        background: #1e1e1e;
        color: #d4d4d4;
        border: 1px solid var(--divider-color, #555);
        border-radius: 8px;
        padding: 12px;
        font-family: "Fira Code", "Consolas", "Monaco", monospace;
        font-size: 12px;
        line-height: 1.5;
        resize: vertical;
        margin-top: 8px;
        box-sizing: border-box;
      }

      .send-bar {
        display: flex;
        justify-content: flex-end;
        margin-top: 8px;
        gap: 8px;
      }

      .json-viewer:empty::before {
        content: "Click the button above to load data...";
        color: #666;
        font-style: italic;
      }

      .collapsible-content {
        overflow: hidden;
        transition: max-height 0.3s ease;
      }

      .error-text {
        color: var(--error-color, #f44336);
        font-size: 13px;
        margin-top: 4px;
      }

      /* ---------- message log ---------- */

      .log-table {
        width: 100%;
        border-collapse: collapse;
        font-family: "Fira Code", "Consolas", "Monaco", monospace;
        font-size: 12px;
      }

      .log-table th {
        text-align: left;
        padding: 6px 8px;
        border-bottom: 2px solid var(--divider-color, #e0e0e0);
        font-weight: 600;
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--secondary-text-color);
      }

      .log-table td {
        padding: 4px 8px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        vertical-align: top;
      }

      .log-row-in {
        color: var(--info-color, #2196f3);
      }

      .log-row-out {
        color: var(--success-color, #4caf50);
      }

      .log-row-error {
        color: var(--error-color, #f44336);
      }

      .direction-badge {
        display: inline-block;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 600;
        min-width: 18px;
        text-align: center;
      }

      .badge-in {
        background: rgba(33, 150, 243, 0.15);
        color: var(--info-color, #2196f3);
      }

      .badge-out {
        background: rgba(76, 175, 80, 0.15);
        color: var(--success-color, #4caf50);
      }

      .topic-cell {
        max-width: 300px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .payload-cell {
        max-width: 400px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: var(--secondary-text-color);
      }

      .empty-log {
        text-align: center;
        padding: 24px;
        color: var(--secondary-text-color);
        font-style: italic;
      }

      .log-container {
        max-height: 400px;
        overflow-y: auto;
        border-radius: 8px;
      }
    `;
  }

  /* ---------- render ---------- */

  render() {
    return html`
      ${this._renderConfigSection()}
      ${this._renderStatesSection()}
      ${this._renderLogSection()}
    `;
  }

  _renderConfigSection() {
    return html`
      <div class="section">
        <div class="section-header">
          <div class="section-title" @click=${() => { this._configOpen = !this._configOpen; }}>
            <span class="collapse-icon ${this._configOpen ? "open" : ""}">&#9654;</span>
            <h2>Raw Config Payload</h2>
          </div>
          <div class="btn-group">
            <button class="btn-primary"
              ?disabled=${this._configLoading}
              @click=${this._loadConfig}>
              ${this._configLoading ? "Loading..." : "Load Config"}
            </button>
            ${this._configPayload ? html`
              <button class="btn-secondary"
                @click=${() => this._copyToClipboard(this._configPayload)}>
                Copy
              </button>
            ` : ""}
          </div>
        </div>
        ${this._configError ? html`<div class="error-text">${this._configError}</div>` : ""}
        ${this._configOpen ? html`
          <div class="json-viewer">${this._configPayload}</div>
          <textarea class="json-editor"
            .value=${this._configEditable}
            @input=${(e) => { this._configEditable = e.target.value; }}
            placeholder="Edit JSON and click Send to publish to Sber..."></textarea>
          <div class="send-bar">
            <button class="btn-danger"
              ?disabled=${this._sendingConfig || !this._configEditable}
              @click=${this._sendConfig}>
              ${this._sendingConfig ? "Sending..." : "Send Config to Sber"}
            </button>
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderStatesSection() {
    return html`
      <div class="section">
        <div class="section-header">
          <div class="section-title" @click=${() => { this._statesOpen = !this._statesOpen; }}>
            <span class="collapse-icon ${this._statesOpen ? "open" : ""}">&#9654;</span>
            <h2>Raw State Payload</h2>
          </div>
          <div class="btn-group">
            <button class="btn-primary"
              ?disabled=${this._statesLoading}
              @click=${this._loadStates}>
              ${this._statesLoading ? "Loading..." : "Load States"}
            </button>
            ${this._statesPayload ? html`
              <button class="btn-secondary"
                @click=${() => this._copyToClipboard(this._statesPayload)}>
                Copy
              </button>
            ` : ""}
          </div>
        </div>
        ${this._statesError ? html`<div class="error-text">${this._statesError}</div>` : ""}
        ${this._statesOpen ? html`
          <div class="json-viewer">${this._statesPayload}</div>
          <textarea class="json-editor"
            .value=${this._statesEditable}
            @input=${(e) => { this._statesEditable = e.target.value; }}
            placeholder="Edit JSON and click Send to publish to Sber..."></textarea>
          <div class="send-bar">
            <button class="btn-danger"
              ?disabled=${this._sendingStates || !this._statesEditable}
              @click=${this._sendStates}>
              ${this._sendingStates ? "Sending..." : "Send States to Sber"}
            </button>
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderLogSection() {
    const messages = [...this._messages].reverse();

    return html`
      <div class="section">
        <div class="section-header">
          <h2>MQTT Message Log</h2>
          <div class="btn-group">
            <button class="btn-secondary" @click=${this._fetchLog}>
              Refresh
            </button>
            <button class="btn-danger"
              ?disabled=${this._messages.length === 0}
              @click=${this._clearLog}>
              Clear Log
            </button>
          </div>
        </div>
        ${this._logError ? html`<div class="error-text">${this._logError}</div>` : ""}
        <div class="log-container">
          ${messages.length === 0
            ? html`<div class="empty-log">No MQTT messages yet. Messages will appear here as they are sent/received.</div>`
            : html`
              <table class="log-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Dir</th>
                    <th>Topic</th>
                    <th>Payload</th>
                  </tr>
                </thead>
                <tbody>
                  ${messages.map(m => html`
                    <tr class="${m.direction === "in" ? "log-row-in" : "log-row-out"}">
                      <td>${this._formatTime(m.time)}</td>
                      <td>
                        <span class="direction-badge ${m.direction === "in" ? "badge-in" : "badge-out"}">
                          ${m.direction === "in" ? "\u2190" : "\u2192"}
                        </span>
                      </td>
                      <td class="topic-cell" title="${m.topic}">${m.topic}</td>
                      <td class="payload-cell" title="${m.payload}">${this._truncate(m.payload)}</td>
                    </tr>
                  `)}
                </tbody>
              </table>
            `}
        </div>
      </div>
    `;
  }
}

customElements.define("sber-devtools", SberDevtools);
