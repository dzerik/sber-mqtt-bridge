/**
 * Sber MQTT Bridge — Statistics grid component.
 *
 * Renders bridge statistics (uptime, messages, errors, etc.) in a responsive grid.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);

function formatUptime(seconds) {
  if (seconds == null) return "\u2014";
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

class SberStatsGrid extends LitElement {
  static get properties() {
    return {
      status: { type: Object },
    };
  }

  constructor() {
    super();
    this.status = null;
  }

  static get styles() {
    return css`
      :host {
        display: block;
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
      .unack-section {
        margin-top: 16px;
      }
      .unack-section h3 {
        margin: 0 0 8px;
        font-size: 15px;
        font-weight: 500;
      }
      .unack-list {
        font-size: 12px;
        color: var(--secondary-text-color);
      }
      .unack-list div {
        padding: 2px 0;
      }
    `;
  }

  render() {
    const s = this.status;
    if (!s) {
      return html`<div style="text-align:center;padding:24px;color:var(--secondary-text-color)">Loading status...</div>`;
    }

    const stats = s.stats || {};
    // Not `unacknowledged`: that list holds everything for a while after
    // every restart, because the acknowledgement mark is per-session and
    // the cloud has no reason to speak up until something asks it for
    // state.  Showing it as a problem was issue #57.
    const unack = s.never_confirmed || [];

    return html`
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
          <span
            class="stat-label"
            title="Devices the Sber cloud has never once asked about. Survives restarts, so a device listed here is genuinely not getting through."
          >
            Never confirmed
          </span>
          <span class="stat-value">${unack.length}</span>
        </div>
      </div>

      ${unack.length > 0
        ? html`
            <div class="unack-section">
              <h3>Never confirmed by Sber</h3>
              <div class="unack-list">
                ${unack.map((e) => html`<div><code>${e}</code></div>`)}
              </div>
            </div>
          `
        : ""}
    `;
  }
}

customElements.define("sber-stats-grid", SberStatsGrid);
