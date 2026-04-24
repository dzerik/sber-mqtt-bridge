/**
 * Sber MQTT Bridge — state-payload diff viewer (DevTools #2).
 *
 * Subscribes to ``sber_mqtt_bridge/subscribe_state_diffs`` and renders
 * each diff as a compact "what actually changed" row.  Sber payloads
 * re-send every feature every publish, so the raw log buries the
 * signal in noise — this view surfaces just the delta:
 *
 *     light.kitchen
 *       ~ light_brightness : 50 → 75
 *       + light_colour     : [255, 0, 0]
 *       − on_off
 */

import { LitElement, html, css } from "../lit-base.js";

class SberStateDiff extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _diffs: { type: Array },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this._diffs = [];
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
            this._diffs = event.snapshot;
          } else if (event.diff) {
            // Ring-buffer behaviour on the backend caps size — on the UI
            // side we mirror the append and trust the backend to trim.
            this._diffs = [...this._diffs, event.diff];
          }
        },
        { type: "sber_mqtt_bridge/subscribe_state_diffs" }
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
      await this.hass.callWS({ type: "sber_mqtt_bridge/clear_state_diffs" });
      this._diffs = [];
      this._error = "";
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  _formatTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("ru-RU", { hour12: false }) +
      "." + String(d.getMilliseconds()).padStart(3, "0");
  }

  /** Extract a short human-friendly representation of a Sber value dict. */
  _formatValue(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v !== "object") return String(v);
    // Sber values are {"type": "BOOL", "bool_value": true} etc. — prefer
    // the typed field when present, fall back to JSON for unusual shapes.
    const type = v.type;
    if (type === "BOOL" && "bool_value" in v) return String(v.bool_value);
    if (type === "INTEGER" && "integer_value" in v) return String(v.integer_value);
    if (type === "DOUBLE" && "double_value" in v) return String(v.double_value);
    if (type === "STRING" && "string_value" in v) return JSON.stringify(v.string_value);
    if (type === "ENUM" && "enum_value" in v) return String(v.enum_value);
    if (type === "COLOUR" && "colour_value" in v) {
      const c = v.colour_value;
      if (c && typeof c === "object" && "h" in c) {
        return `h=${c.h} s=${c.s} v=${c.v}`;
      }
    }
    return JSON.stringify(v);
  }

  render() {
    const rows = [...this._diffs].reverse();
    return html`
      <div class="section">
        <div class="section-header">
          <h2>State Diffs</h2>
          <div class="btn-group">
            <button class="btn-danger"
              ?disabled=${this._diffs.length === 0}
              @click=${this._clear}>
              Clear Diffs
            </button>
          </div>
        </div>
        <div class="hint">
          Each row is the delta between two consecutive state publishes for one device — no delta is emitted when the payload is identical.
        </div>
        ${this._error ? html`<div class="error-text">${this._error}</div>` : ""}
        <div class="diff-container">
          ${rows.length === 0
            ? html`<div class="empty">No diffs yet. The first real state change will appear here.</div>`
            : html`${rows.map((d) => this._renderDiff(d))}`}
        </div>
      </div>
    `;
  }

  _renderDiff(d) {
    const changedKeys = Object.keys(d.changed || {}).sort();
    const addedKeys = Object.keys(d.added || {}).sort();
    const removedKeys = Object.keys(d.removed || {}).sort();
    return html`
      <div class="diff ${d.is_initial ? "diff-initial" : ""}">
        <div class="diff-header">
          <span class="entity">${d.entity_id}</span>
          <span class="topic">${d.topic}</span>
          ${d.is_initial ? html`<span class="initial-badge">initial</span>` : ""}
          <span class="time">${this._formatTime(d.ts)}</span>
        </div>
        <table class="delta-table">
          <tbody>
            ${changedKeys.map((k) => html`
              <tr class="delta delta-changed">
                <td class="op">~</td>
                <td class="key">${k}</td>
                <td class="from">${this._formatValue(d.changed[k].before)}</td>
                <td class="arrow">→</td>
                <td class="to">${this._formatValue(d.changed[k].after)}</td>
              </tr>
            `)}
            ${addedKeys.map((k) => html`
              <tr class="delta delta-added">
                <td class="op">+</td>
                <td class="key">${k}</td>
                <td class="from"></td>
                <td class="arrow"></td>
                <td class="to">${this._formatValue(d.added[k])}</td>
              </tr>
            `)}
            ${removedKeys.map((k) => html`
              <tr class="delta delta-removed">
                <td class="op">−</td>
                <td class="key">${k}</td>
                <td class="from">${this._formatValue(d.removed[k])}</td>
                <td class="arrow"></td>
                <td class="to"></td>
              </tr>
            `)}
          </tbody>
        </table>
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
        margin-bottom: 6px;
      }
      h2 { margin: 0; font-size: 1.1em; color: var(--primary-text-color); }
      .hint { color: var(--secondary-text-color); font-size: 0.85em; margin-bottom: 12px; }
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
      .diff {
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        padding: 8px 12px;
        margin-bottom: 6px;
        background: var(--primary-background-color);
      }
      .diff-initial { border-left: 3px solid var(--secondary-text-color); }
      .diff-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 6px;
        font-size: 0.9em;
      }
      .entity { font-family: monospace; font-weight: 600; color: var(--primary-text-color); }
      .topic { font-family: monospace; color: var(--secondary-text-color); font-size: 0.85em; }
      .initial-badge {
        background: var(--secondary-background-color);
        color: var(--secondary-text-color);
        padding: 1px 8px;
        border-radius: 10px;
        font-size: 0.7em;
        text-transform: uppercase;
        font-weight: 600;
      }
      .time { margin-left: auto; color: var(--secondary-text-color); font-family: monospace; font-size: 0.8em; }
      .delta-table { width: 100%; border-collapse: collapse; font-family: monospace; font-size: 0.9em; }
      .delta td { padding: 2px 8px; vertical-align: top; }
      .op {
        width: 18px;
        font-weight: 700;
        text-align: center;
      }
      .key { width: 220px; color: var(--primary-text-color); }
      .from { color: var(--secondary-text-color); word-break: break-all; }
      .arrow { width: 20px; text-align: center; color: var(--secondary-text-color); }
      .to { color: var(--primary-text-color); word-break: break-all; }
      .delta-changed .op { color: var(--warning-color, #ff9800); }
      .delta-added .op { color: var(--success-color, #4caf50); }
      .delta-removed .op { color: var(--error-color, #f44336); }
      .delta-removed .from { text-decoration: line-through; }
    `;
  }
}

customElements.define("sber-state-diff", SberStateDiff);
