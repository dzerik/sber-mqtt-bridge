/**
 * Sber MQTT Bridge — schema validation issues (DevTools #4).
 *
 * Subscribes to ``sber_mqtt_bridge/subscribe_validation_issues`` and
 * surfaces everything the validator finds in every outbound publish:
 *
 *   - Missing obligatory feature (error)   → Sber silently drops the device.
 *   - Type mismatch (error)                → Sber rejects the value.
 *   - Unknown feature for category (warn)  → Future-proof nudge.
 *   - Not in declared features (info)      → Value never reaches Sber.
 *
 * Two-tab layout:
 *
 *   "By entity" — latest status per entity (clean vs issues).  Best
 *                 for "which devices are broken right now".
 *   "Timeline"  — chronological feed (newest first).  Best for "what
 *                 happened during this debug session".
 */

import { LitElement, html, css } from "../lit-base.js";

class SberValidation extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _byEntity: { type: Object },
      _recent: { type: Array },
      _tab: { type: String },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this._byEntity = {};
    this._recent = [];
    this._tab = "by_entity";
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
            this._byEntity = event.snapshot.by_entity || {};
            this._recent = event.snapshot.recent || [];
          } else if (event.issues) {
            // Live batch — append to timeline and re-group by entity.
            const updated = { ...this._byEntity };
            for (const issue of event.issues) {
              updated[issue.entity_id] = (updated[issue.entity_id] || []).filter(
                // Per-entity view holds only the latest batch for the entity —
                // same contract as the server.
                () => false
              );
            }
            for (const issue of event.issues) {
              (updated[issue.entity_id] ||= []).push(issue);
            }
            this._byEntity = updated;
            this._recent = [...this._recent, ...event.issues];
          }
        },
        { type: "sber_mqtt_bridge/subscribe_validation_issues" }
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

  async _clear() {
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/clear_validation_issues" });
      this._byEntity = {};
      this._recent = [];
      this._error = "";
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  _formatTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("ru-RU", { hour12: false });
  }

  _counts() {
    let errors = 0;
    let warnings = 0;
    let infos = 0;
    for (const list of Object.values(this._byEntity)) {
      for (const i of list) {
        if (i.severity === "error") errors++;
        else if (i.severity === "warning") warnings++;
        else infos++;
      }
    }
    return { errors, warnings, infos };
  }

  render() {
    const { errors, warnings, infos } = this._counts();
    return html`
      <div class="section">
        <div class="section-header">
          <h2>Schema Validation</h2>
          <div class="btn-group">
            <button class="btn-danger"
              ?disabled=${this._recent.length === 0}
              @click=${this._clear}>
              Clear
            </button>
          </div>
        </div>
        <div class="summary">
          <span class="chip chip-error">${errors} errors</span>
          <span class="chip chip-warning">${warnings} warnings</span>
          <span class="chip chip-info">${infos} info</span>
          <span class="hint">Every outbound publish is checked against the auto-generated Sber spec.</span>
        </div>
        ${this._error ? html`<div class="error-text">${this._error}</div>` : ""}
        <div class="tabs">
          <button class="tab ${this._tab === "by_entity" ? "active" : ""}"
            @click=${() => { this._tab = "by_entity"; }}>
            By entity
          </button>
          <button class="tab ${this._tab === "timeline" ? "active" : ""}"
            @click=${() => { this._tab = "timeline"; }}>
            Timeline
          </button>
        </div>
        ${this._tab === "by_entity" ? this._renderByEntity() : this._renderTimeline()}
      </div>
    `;
  }

  _renderByEntity() {
    const entities = Object.keys(this._byEntity).sort();
    if (entities.length === 0) {
      return html`<div class="empty">No publishes validated yet.</div>`;
    }
    return html`
      <table class="issue-table">
        <thead>
          <tr>
            <th class="col-entity">Entity</th>
            <th class="col-sev"></th>
            <th class="col-type">Issue</th>
            <th class="col-key">Feature</th>
            <th class="col-desc">Description</th>
          </tr>
        </thead>
        <tbody>
          ${entities.flatMap((eid) => {
            const issues = this._byEntity[eid] || [];
            if (issues.length === 0) {
              return [html`
                <tr class="clean">
                  <td class="entity">${eid}</td>
                  <td class="sev"><span class="badge badge-clean">clean</span></td>
                  <td colspan="3">No issues</td>
                </tr>
              `];
            }
            return issues.map((i, idx) => html`
              <tr class="sev-${i.severity}">
                <td class="entity">${idx === 0 ? eid : ""}</td>
                <td class="sev"><span class="badge badge-${i.severity}">${i.severity}</span></td>
                <td class="type">${i.type}</td>
                <td class="key">${i.key || "—"}</td>
                <td class="desc">${i.description}</td>
              </tr>
            `);
          })}
        </tbody>
      </table>
    `;
  }

  _renderTimeline() {
    const rows = [...this._recent].reverse();
    if (rows.length === 0) {
      return html`<div class="empty">No issues yet.</div>`;
    }
    return html`
      <table class="issue-table">
        <thead>
          <tr>
            <th class="col-time">Time</th>
            <th class="col-entity">Entity</th>
            <th class="col-sev"></th>
            <th class="col-type">Issue</th>
            <th class="col-key">Feature</th>
            <th class="col-desc">Description</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((i) => html`
            <tr class="sev-${i.severity}">
              <td class="t">${this._formatTime(i.ts)}</td>
              <td class="entity">${i.entity_id}</td>
              <td class="sev"><span class="badge badge-${i.severity}">${i.severity}</span></td>
              <td class="type">${i.type}</td>
              <td class="key">${i.key || "—"}</td>
              <td class="desc">${i.description}</td>
            </tr>
          `)}
        </tbody>
      </table>
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
      .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
      h2 { margin: 0; font-size: 1.1em; color: var(--primary-text-color); }
      .summary { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
      .chip {
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.8em;
        font-weight: 600;
      }
      .chip-error { background: rgba(244, 67, 54, 0.15); color: var(--error-color, #f44336); }
      .chip-warning { background: rgba(255, 152, 0, 0.15); color: var(--warning-color, #ff9800); }
      .chip-info { background: rgba(3, 169, 244, 0.15); color: var(--primary-color, #03a9f4); }
      .hint { color: var(--secondary-text-color); font-size: 0.85em; margin-left: 8px; }
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
      .tabs { display: flex; gap: 0; border-bottom: 1px solid var(--divider-color); margin-bottom: 10px; }
      .tab {
        background: none;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 6px 14px;
        color: var(--secondary-text-color);
        font-size: 0.9em;
        cursor: pointer;
      }
      .tab.active { color: var(--primary-text-color); border-bottom-color: var(--primary-color, #03a9f4); }
      .issue-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
      .issue-table th {
        text-align: left;
        padding: 6px 8px;
        border-bottom: 1px solid var(--divider-color);
        color: var(--secondary-text-color);
        font-weight: 500;
      }
      .issue-table td { padding: 4px 8px; vertical-align: top; }
      .t { font-family: monospace; color: var(--secondary-text-color); width: 80px; }
      .entity { font-family: monospace; font-weight: 500; color: var(--primary-text-color); }
      .type { font-family: monospace; color: var(--secondary-text-color); }
      .key { font-family: monospace; color: var(--primary-text-color); }
      .desc { color: var(--primary-text-color); }
      .clean .entity, .clean td { color: var(--secondary-text-color); }
      .badge {
        display: inline-block;
        padding: 1px 8px;
        border-radius: 10px;
        font-size: 0.7em;
        font-weight: 600;
        text-transform: uppercase;
      }
      .badge-error { background: rgba(244, 67, 54, 0.15); color: var(--error-color, #f44336); }
      .badge-warning { background: rgba(255, 152, 0, 0.15); color: var(--warning-color, #ff9800); }
      .badge-info { background: rgba(3, 169, 244, 0.15); color: var(--primary-color, #03a9f4); }
      .badge-clean { background: rgba(76, 175, 80, 0.15); color: var(--success-color, #4caf50); }
      .sev-error .desc { color: var(--error-color, #f44336); }
      .sev-warning .desc { color: var(--warning-color, #ff9800); }
    `;
  }
}

customElements.define("sber-validation", SberValidation);
