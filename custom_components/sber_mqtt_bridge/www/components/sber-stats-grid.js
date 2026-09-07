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
const { t, ensurePanelTranslations, sberErrorText } = await import(`../localize.js${_q}`);

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
      /** Home Assistant object — carries `localize` for the panel strings. */
      hass: { type: Object },
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
      .last-error {
        margin-top: 16px;
        padding: 8px 12px;
        border-radius: 8px;
        background: rgba(244, 67, 54, 0.12);
        font-size: 13px;
      }
      /* Sber answered after this error, so it is history, not an alarm:
         same words, no red. */
      .last-error.superseded {
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--secondary-text-color);
      }
      .last-error .code {
        font-weight: 600;
        color: var(--error-color, #f44336);
      }
      .last-error.superseded .code {
        color: inherit;
      }
      .last-error .when {
        margin-left: 8px;
        color: var(--secondary-text-color);
      }
      .last-error .detail {
        display: block;
        margin-top: 4px;
        color: var(--secondary-text-color);
        overflow-wrap: anywhere;
      }
    `;
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
  }

  render() {
    const s = this.status;
    if (!s) {
      return html`<div style="text-align:center;padding:24px;color:var(--secondary-text-color)">${t(this.hass, "stats.loading")}</div>`;
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
          <span class="stat-label">${t(this.hass, "stats.uptime")}</span>
          <span class="stat-value">${formatUptime(stats.connection_uptime_seconds)}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.messages_received")}</span>
          <span class="stat-value">${stats.messages_received ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.messages_sent")}</span>
          <span class="stat-value">${stats.messages_sent ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.commands")}</span>
          <span class="stat-value">${stats.commands_received ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.config_requests")}</span>
          <span class="stat-value">${stats.config_requests ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.status_requests")}</span>
          <span class="stat-value">${stats.status_requests ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.sber_errors")}</span>
          <span class="stat-value">${stats.errors_from_sber ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.publish_errors")}</span>
          <span class="stat-value">${stats.publish_errors ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.reconnects")}</span>
          <span class="stat-value">${stats.reconnect_count ?? 0}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">${t(this.hass, "stats.entities_exposed")}</span>
          <span class="stat-value">${s.entities_count ?? 0}</span>
        </div>
        <div class="stat-item">
          <span
            class="stat-label"
            title="${t(this.hass, 'stats.never_confirmed_hint')}"
          >
            ${t(this.hass, "stats.never_confirmed")}
          </span>
          <span class="stat-value">${unack.length}</span>
        </div>
      </div>

      ${unack.length > 0
        ? html`
            <div class="unack-section">
              <h3>${t(this.hass, "stats.never_confirmed_title")}</h3>
              <div class="unack-list">
                ${unack.map((e) => html`<div><code>${e}</code></div>`)}
              </div>
            </div>
          `
        : ""}
      ${this._renderLastError(s.last_error)}
    `;
  }

  /**
   * Wall-clock moment of an event, in the user's own locale.
   *
   * @param {?number} moment - Seconds since the epoch, or null when the
   *   error is older than the message log remembers.
   * @returns {string} Localized date and time, or "" when there is no
   *   moment to print \u2014 a guessed one would be worse than none.
   */
  _moment(moment) {
    if (typeof moment !== "number" || !Number.isFinite(moment)) return "";
    const when = new Date(moment * 1000);
    return Number.isNaN(when.getTime()) ? "" : when.toLocaleString(this.hass?.locale?.language || this.hass?.language);
  }

  /**
   * The last error Sber sent, with its code spelled out and dated.
   *
   * "Sber errors: 3" in the grid above says something went wrong and
   * nothing about what: a wrong password (403) and a cloud outage (503)
   * produce the identical tile.  The documented meaning of the code is
   * the difference between the two, so it is shown next to the number.
   *
   * The bridge never clears the error either, so an undated tile stays
   * red for the rest of the Home Assistant session \u2014 long after the user
   * fixed the password and the bridge went back to work.  Hence the two
   * extra facts the backend now sends: when the error happened, and
   * whether Sber has addressed the bridge since.  If it has, the tile
   * steps back to a plain note: still worth reading, no longer an alarm.
   *
   * @param {{code: ?number, message: string, device_id: string,
   *   at: ?number, superseded: boolean}|null} error - Decoded error from
   *   `sber_mqtt_bridge/status`, or null when the cloud has not reported
   *   one.
   * @returns {unknown} Lit template, or "" when there is nothing to show.
   */
  _renderLastError(error) {
    if (!error) return "";
    const meaning = sberErrorText(this.hass, error.code);
    const when = this._moment(error.at);
    return html`
      <div class="last-error ${error.superseded ? "superseded" : ""}">
        <span class="stat-label">${t(this.hass, "stats.last_error")}</span>
        <span class="code"> ${error.code ?? "\u2014"}</span>${meaning ? html` \u2014 ${meaning}` : ""}
        ${when ? html`<span class="when">${when}</span>` : ""}
        ${error.message || error.device_id
          ? html`<span class="detail">${error.message}${error.device_id ? html` (${error.device_id})` : ""}</span>`
          : ""}
        ${error.superseded
          ? html`<span class="detail">${t(this.hass, "stats.last_error_superseded")}</span>`
          : ""}
      </div>
    `;
  }
}

customElements.define("sber-stats-grid", SberStatsGrid);
