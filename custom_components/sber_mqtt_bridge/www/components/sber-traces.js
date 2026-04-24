/**
 * Sber MQTT Bridge — correlation-timeline viewer (DevTools #1).
 *
 * Subscribes to ``sber_mqtt_bridge/subscribe_traces`` and renders each
 * trace as an expandable row with a chronological list of its events
 * (sber_command, ha_service_call, ha_state_changed, publish_out,
 * silent_rejection).  A trace groups everything triggered by a single
 * HomeAssistant Context — which is HA's built-in correlation ID — so
 * the user can see the full "command → service call → state change →
 * publish → ack/rejection" chain in one place.
 */

import { LitElement, html, css } from "../lit-base.js";

const STATUS_LABEL = {
  active: "Active",
  success: "Success",
  failed: "Failed",
  timeout: "Timeout",
};

const EVENT_ARROW = {
  sber_command: "⬇",        // Sber → us
  ha_service_call: "→",     // us → HA
  ha_state_changed: "↻",    // HA reaction
  publish_out: "⬆",         // us → Sber
  silent_rejection: "✘",    // Sber silent no
};

class SberTraces extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _traces: { type: Array },
      _expanded: { type: Object },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this._traces = [];
    this._expanded = {};
    this._error = "";
    this._hassReady = false;
    this._unsub = null;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsubscribe();
  }

  updated(changedProps) {
    if (changedProps.has("hass") && this.hass && !this._hassReady) {
      this._hassReady = true;
      this._subscribe();
    }
  }

  async _subscribe() {
    if (this._unsub) return;
    try {
      this._unsub = await this.hass.connection.subscribeMessage(
        (event) => {
          if (event.snapshot) {
            this._traces = event.snapshot;
          } else if (event.trace) {
            this._applyLiveUpdate(event.kind, event.trace);
          }
        },
        { type: "sber_mqtt_bridge/subscribe_traces" }
      );
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  _unsubscribe() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  _applyLiveUpdate(kind, trace) {
    const existing = this._traces.findIndex((t) => t.trace_id === trace.trace_id);
    if (existing === -1) {
      this._traces = [...this._traces, trace];
      return;
    }
    const next = [...this._traces];
    next[existing] = trace;
    this._traces = next;
  }

  async _clearTraces() {
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/clear_traces" });
      this._traces = [];
      this._expanded = {};
      this._error = "";
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  _toggle(traceId) {
    this._expanded = {
      ...this._expanded,
      [traceId]: !this._expanded[traceId],
    };
  }

  _formatTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("ru-RU", { hour12: false }) +
      "." + String(d.getMilliseconds()).padStart(3, "0");
  }

  _relMs(trace, ts) {
    return Math.round((ts - trace.started_at) * 1000);
  }

  _eventSummary(ev) {
    if (!ev.payload) return "";
    if (ev.type === "ha_service_call") {
      const p = ev.payload || {};
      return `${p.domain || ""}.${p.service || ""}`;
    }
    if (ev.type === "ha_state_changed") {
      const p = ev.payload || {};
      return `state=${p.state ?? "?"}`;
    }
    if (ev.type === "publish_out") {
      const s = typeof ev.payload === "string" ? ev.payload : JSON.stringify(ev.payload);
      return s.length > 60 ? s.slice(0, 60) + "…" : s;
    }
    if (ev.type === "silent_rejection") {
      return "Sber did not acknowledge";
    }
    return "";
  }

  render() {
    const traces = [...this._traces].reverse(); // newest first
    return html`
      <div class="section">
        <div class="section-header">
          <h2>Correlation Timeline</h2>
          <div class="btn-group">
            <button class="btn-danger"
              ?disabled=${this._traces.length === 0}
              @click=${this._clearTraces}>
              Clear Traces
            </button>
          </div>
        </div>
        ${this._error ? html`<div class="error-text">${this._error}</div>` : ""}
        <div class="trace-container">
          ${traces.length === 0
            ? html`<div class="empty">No traces yet. A trace is opened for every Sber command or HA state change.</div>`
            : html`${traces.map((t) => this._renderTrace(t))}`}
        </div>
      </div>
    `;
  }

  _renderTrace(trace) {
    const open = !!this._expanded[trace.trace_id];
    return html`
      <div class="trace trace-${trace.status}">
        <div class="trace-header" @click=${() => this._toggle(trace.trace_id)}>
          <span class="caret ${open ? "open" : ""}">&#9654;</span>
          <span class="status-badge status-${trace.status}">${STATUS_LABEL[trace.status] || trace.status}</span>
          <span class="trigger">${trace.trigger}</span>
          <span class="entities">${trace.entity_ids.join(", ") || "(no entity)"}</span>
          <span class="counts">${trace.events.length} ev</span>
          <span class="time">${this._formatTime(trace.started_at)}</span>
        </div>
        ${open ? html`
          <table class="event-table">
            <thead>
              <tr>
                <th class="col-t">t+ms</th>
                <th class="col-type">Event</th>
                <th class="col-entity">Entity</th>
                <th class="col-detail">Detail</th>
              </tr>
            </thead>
            <tbody>
              ${trace.events.map((ev) => html`
                <tr class="event event-${ev.type}">
                  <td class="col-t">${this._relMs(trace, ev.ts)}</td>
                  <td class="col-type">
                    <span class="arrow">${EVENT_ARROW[ev.type] || ""}</span>
                    ${ev.type}
                  </td>
                  <td class="col-entity">${ev.entity_id || ""}</td>
                  <td class="col-detail" title="${JSON.stringify(ev.payload ?? "")}">${this._eventSummary(ev)}</td>
                </tr>
              `)}
            </tbody>
          </table>
        ` : ""}
      </div>
    `;
  }

  static get styles() {
    return css`
      .section {
        background: var(--card-background-color);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
      }
      .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 12px;
      }
      h2 { margin: 0; font-size: 1.1em; color: var(--primary-text-color); }
      .btn-danger {
        background: var(--error-color, #f44336);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 6px 12px;
        cursor: pointer;
      }
      .btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
      .error-text { color: var(--error-color, #f44336); margin-bottom: 8px; font-size: 0.9em; }
      .empty { color: var(--secondary-text-color); font-style: italic; padding: 16px; text-align: center; }
      .trace {
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        margin-bottom: 6px;
        overflow: hidden;
      }
      .trace-active { border-left: 3px solid var(--primary-color, #03a9f4); }
      .trace-success { border-left: 3px solid var(--success-color, #4caf50); }
      .trace-failed { border-left: 3px solid var(--error-color, #f44336); }
      .trace-timeout { border-left: 3px solid var(--warning-color, #ff9800); }
      .trace-header {
        display: grid;
        grid-template-columns: 24px 80px 120px 1fr 60px 110px;
        gap: 8px;
        padding: 8px 12px;
        cursor: pointer;
        align-items: center;
        font-size: 0.9em;
      }
      .trace-header:hover { background: var(--secondary-background-color); }
      .caret { display: inline-block; transition: transform 0.15s; color: var(--secondary-text-color); }
      .caret.open { transform: rotate(90deg); }
      .status-badge {
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75em;
        font-weight: 600;
        text-align: center;
        text-transform: uppercase;
      }
      .status-active { background: rgba(3, 169, 244, 0.15); color: var(--primary-color, #03a9f4); }
      .status-success { background: rgba(76, 175, 80, 0.15); color: var(--success-color, #4caf50); }
      .status-failed { background: rgba(244, 67, 54, 0.15); color: var(--error-color, #f44336); }
      .status-timeout { background: rgba(255, 152, 0, 0.15); color: var(--warning-color, #ff9800); }
      .trigger { color: var(--secondary-text-color); font-family: monospace; font-size: 0.85em; }
      .entities { color: var(--primary-text-color); font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .counts { color: var(--secondary-text-color); font-size: 0.8em; text-align: right; }
      .time { color: var(--secondary-text-color); font-family: monospace; font-size: 0.8em; text-align: right; }
      .event-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85em;
        background: var(--secondary-background-color);
      }
      .event-table th {
        text-align: left;
        padding: 6px 12px;
        border-bottom: 1px solid var(--divider-color);
        color: var(--secondary-text-color);
        font-weight: 500;
      }
      .event-table td { padding: 4px 12px; vertical-align: top; }
      .col-t { width: 70px; color: var(--secondary-text-color); font-family: monospace; text-align: right; }
      .col-type { width: 180px; font-family: monospace; }
      .col-entity { width: 200px; font-family: monospace; color: var(--primary-text-color); }
      .col-detail { color: var(--secondary-text-color); font-family: monospace; word-break: break-all; }
      .arrow { display: inline-block; width: 16px; margin-right: 4px; }
      .event-sber_command { color: var(--primary-color, #03a9f4); }
      .event-ha_service_call { color: var(--success-color, #4caf50); }
      .event-ha_state_changed { color: var(--warning-color, #ff9800); }
      .event-publish_out { color: var(--primary-color, #03a9f4); }
      .event-silent_rejection { color: var(--error-color, #f44336); font-weight: 600; }
    `;
  }
}

customElements.define("sber-traces", SberTraces);
