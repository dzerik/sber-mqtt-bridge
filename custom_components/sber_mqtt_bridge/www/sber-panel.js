/**
 * Sber MQTT Bridge — SPA Panel for Home Assistant sidebar.
 *
 * Uses LitElement (bundled with HA) and HA WebSocket API.
 * No build step required.
 */

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html ?? (await import("https://unpkg.com/lit@3/index.js?module")).html;
const css = LitElement?.prototype.css ?? (await import("https://unpkg.com/lit@3/index.js?module")).css;

/* ---------- helpers ---------- */

function formatUptime(seconds) {
  if (seconds == null) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  if (m) parts.push(`${m}m`);
  parts.push(`${s}s`);
  return parts.join(" ");
}

/* ---------- main panel ---------- */

class SberMqttPanel extends LitElement {

  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      _tab: { type: Number },
      _devices: { type: Array },
      _devicesExtra: { type: Object },
      _status: { type: Object },
      _loading: { type: Boolean },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this._tab = 0;
    this._devices = [];
    this._devicesExtra = {};
    this._status = null;
    this._loading = false;
    this._error = "";
    this._autoRefresh = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._fetchAll();
    this._autoRefresh = setInterval(() => this._fetchAll(), 15000);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._autoRefresh) {
      clearInterval(this._autoRefresh);
      this._autoRefresh = null;
    }
  }

  /* ---------- data ---------- */

  async _fetchAll() {
    try {
      const [devResult, statusResult] = await Promise.all([
        this.hass.callWS({ type: "sber_mqtt_bridge/devices" }),
        this.hass.callWS({ type: "sber_mqtt_bridge/status" }),
      ]);
      this._devices = devResult.devices || [];
      this._devicesExtra = {
        total: devResult.total,
        acknowledged_count: devResult.acknowledged_count,
        unacknowledged_count: devResult.unacknowledged_count,
        unacknowledged: devResult.unacknowledged || [],
      };
      this._status = statusResult;
      this._error = "";
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  async _republish() {
    this._loading = true;
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/republish" });
      await this._fetchAll();
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  /* ---------- styles ---------- */

  static get styles() {
    return css`
      :host {
        display: block;
        padding: 16px;
        font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif);
        color: var(--primary-text-color);
        background: var(--primary-background-color);
        --sber-green: #4caf50;
        --sber-red: #f44336;
        --sber-grey: #9e9e9e;
      }

      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
        flex-wrap: wrap;
        gap: 8px;
      }

      .header h1 {
        margin: 0;
        font-size: 24px;
        font-weight: 400;
      }

      .tabs {
        display: flex;
        border-bottom: 2px solid var(--divider-color, #e0e0e0);
        margin-bottom: 16px;
      }

      .tab {
        padding: 12px 24px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--secondary-text-color);
        border-bottom: 2px solid transparent;
        margin-bottom: -2px;
        transition: color 0.2s, border-color 0.2s;
        user-select: none;
      }

      .tab:hover {
        color: var(--primary-color);
      }

      .tab.active {
        color: var(--primary-color);
        border-bottom-color: var(--primary-color);
      }

      .card {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.1));
        padding: 16px;
        margin-bottom: 16px;
      }

      .card h2 {
        margin: 0 0 12px;
        font-size: 18px;
        font-weight: 500;
      }

      .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 12px;
      }

      .stat-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 12px;
        border-radius: 8px;
        background: var(--secondary-background-color, #f5f5f5);
      }

      .stat-label {
        font-size: 13px;
        color: var(--secondary-text-color);
      }

      .stat-value {
        font-size: 16px;
        font-weight: 500;
      }

      .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 500;
        color: #fff;
      }

      .badge-green { background: var(--sber-green); }
      .badge-red { background: var(--sber-red); }
      .badge-grey { background: var(--sber-grey); }

      .connection-indicator {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 16px;
        font-weight: 500;
      }

      .dot {
        width: 12px; height: 12px;
        border-radius: 50%;
        display: inline-block;
      }

      .dot-green { background: var(--sber-green); }
      .dot-red { background: var(--sber-red); }

      /* --- table --- */
      .table-wrapper {
        overflow-x: auto;
      }

      table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }

      th {
        text-align: left;
        padding: 10px 8px;
        font-weight: 500;
        color: var(--secondary-text-color);
        border-bottom: 2px solid var(--divider-color, #e0e0e0);
        white-space: nowrap;
      }

      td {
        padding: 8px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
        vertical-align: middle;
      }

      tr.online { }
      tr.offline td { opacity: 0.55; }

      .features {
        display: flex;
        flex-wrap: wrap;
        gap: 4px;
      }

      .feature-tag {
        display: inline-block;
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 11px;
        background: var(--secondary-background-color, #eee);
        color: var(--secondary-text-color);
      }

      .actions {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
      }

      .btn {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 8px 16px;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        transition: background 0.15s;
      }

      .btn-primary {
        background: var(--primary-color);
        color: #fff;
      }

      .btn-primary:hover { opacity: 0.85; }
      .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

      .btn-secondary {
        background: var(--secondary-background-color, #eee);
        color: var(--primary-text-color);
      }

      .btn-secondary:hover { opacity: 0.8; }

      .counters {
        display: flex;
        gap: 16px;
        flex-wrap: wrap;
        margin-bottom: 12px;
        font-size: 14px;
      }

      .counter-item {
        display: flex;
        align-items: center;
        gap: 6px;
      }

      .error-banner {
        background: var(--sber-red);
        color: #fff;
        padding: 8px 16px;
        border-radius: 8px;
        margin-bottom: 12px;
        font-size: 13px;
      }

      .empty-state {
        text-align: center;
        padding: 48px 16px;
        color: var(--secondary-text-color);
        font-size: 15px;
      }

      .unack-list {
        margin-top: 8px;
        font-size: 12px;
        color: var(--secondary-text-color);
      }
    `;
  }

  /* ---------- render ---------- */

  render() {
    return html`
      <div class="header">
        <h1>Sber MQTT Bridge</h1>
        <div class="actions">
          <button class="btn btn-secondary" @click=${this._fetchAll}>
            Refresh
          </button>
          <button class="btn btn-primary" ?disabled=${this._loading} @click=${this._republish}>
            ${this._loading ? "Publishing..." : "Re-publish config"}
          </button>
        </div>
      </div>

      ${this._error ? html`<div class="error-banner">${this._error}</div>` : ""}

      <div class="tabs">
        <div class="tab ${this._tab === 0 ? "active" : ""}" @click=${() => this._tab = 0}>
          Devices
        </div>
        <div class="tab ${this._tab === 1 ? "active" : ""}" @click=${() => this._tab = 1}>
          Status
        </div>
      </div>

      ${this._tab === 0 ? this._renderDevices() : this._renderStatus()}
    `;
  }

  /* ---------- tab: devices ---------- */

  _renderDevices() {
    const extra = this._devicesExtra;
    return html`
      <div class="card">
        <div class="counters">
          <div class="counter-item">
            <span class="stat-label">Total exposed:</span>
            <strong>${extra.total ?? 0}</strong>
          </div>
          <div class="counter-item">
            <span class="stat-label">Acknowledged:</span>
            <span class="badge badge-green">${extra.acknowledged_count ?? 0}</span>
          </div>
          <div class="counter-item">
            <span class="stat-label">Unacknowledged:</span>
            <span class="badge ${(extra.unacknowledged_count ?? 0) > 0 ? "badge-red" : "badge-grey"}">
              ${extra.unacknowledged_count ?? 0}
            </span>
          </div>
        </div>

        ${(extra.unacknowledged?.length ?? 0) > 0
          ? html`<div class="unack-list">
              Unacknowledged: ${extra.unacknowledged.join(", ")}
            </div>`
          : ""}
      </div>

      <div class="card">
        ${this._devices.length === 0
          ? html`<div class="empty-state">No exposed devices found</div>`
          : html`
            <div class="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Entity ID</th>
                    <th>Name</th>
                    <th>Sber Category</th>
                    <th>Room</th>
                    <th>Features</th>
                    <th>State</th>
                    <th>Online</th>
                  </tr>
                </thead>
                <tbody>
                  ${this._devices.map(d => html`
                    <tr class="${d.is_online ? "online" : "offline"}">
                      <td><code>${d.entity_id}</code></td>
                      <td>${d.name || "—"}</td>
                      <td><code>${d.sber_category}</code></td>
                      <td>${d.room || "—"}</td>
                      <td>
                        <div class="features">
                          ${(d.features || []).map(f => html`
                            <span class="feature-tag">${f}</span>
                          `)}
                        </div>
                      </td>
                      <td>${d.state ?? "—"}</td>
                      <td>
                        <span class="badge ${d.is_online ? "badge-green" : "badge-grey"}">
                          ${d.is_online ? "Online" : "Offline"}
                        </span>
                      </td>
                    </tr>
                  `)}
                </tbody>
              </table>
            </div>
          `}
      </div>
    `;
  }

  /* ---------- tab: status ---------- */

  _renderStatus() {
    const s = this._status;
    if (!s) {
      return html`<div class="card"><div class="empty-state">Loading status...</div></div>`;
    }

    const stats = s.stats || {};
    const connected = s.connected;

    return html`
      <div class="card">
        <h2>Connection</h2>
        <div class="connection-indicator">
          <span class="dot ${connected ? "dot-green" : "dot-red"}"></span>
          ${connected ? "Connected" : "Disconnected"}
        </div>
      </div>

      <div class="card">
        <h2>Statistics</h2>
        <div class="stats-grid">
          <div class="stat-item">
            <span class="stat-label">Uptime</span>
            <span class="stat-value">${formatUptime(stats.connection_uptime_seconds)}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Messages received</span>
            <span class="stat-value">${stats.messages_received ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Messages sent</span>
            <span class="stat-value">${stats.messages_sent ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Commands</span>
            <span class="stat-value">${stats.commands_received ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Config requests</span>
            <span class="stat-value">${stats.config_requests ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Status requests</span>
            <span class="stat-value">${stats.status_requests ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Sber errors</span>
            <span class="stat-value">${stats.errors_from_sber ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Publish errors</span>
            <span class="stat-value">${stats.publish_errors ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Reconnects</span>
            <span class="stat-value">${stats.reconnect_count ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Entities exposed</span>
            <span class="stat-value">${s.entities_count ?? 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Unacknowledged</span>
            <span class="stat-value">${(s.unacknowledged || []).length}</span>
          </div>
        </div>
      </div>

      ${(s.unacknowledged || []).length > 0
        ? html`
          <div class="card">
            <h2>Unacknowledged Entities</h2>
            <div class="unack-list">
              ${s.unacknowledged.map(e => html`<div><code>${e}</code></div>`)}
            </div>
          </div>
        `
        : ""}
    `;
  }
}

customElements.define("sber-mqtt-panel", SberMqttPanel);
