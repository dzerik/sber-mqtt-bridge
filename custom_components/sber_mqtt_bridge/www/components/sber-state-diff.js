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

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { formatSberValue } = await import(`../utils.js${_q}`);
await import(`./sber-copy-button.js${_q}`);

/** Hard cap on the live diff buffer (live appends are unbounded on the
 * wire — the backend ring buffer only trims the initial snapshot). */
const MAX_DIFFS = 500;

class SberStateDiff extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _diffs: { type: Array },
      _query: { type: String },
      _expanded: { type: Object },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this._diffs = [];
    this._query = "";
    /** entity_id → true when its earlier diffs are unfolded. */
    this._expanded = {};
    this._error = "";
    this._unsub = null;
    this._subscribing = false;
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
    /* Re-subscribe on re-attach (HA navigation reuses the instance). */
    if (this.hass) this._subscribe();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsubscribe();
  }

  updated(changedProps) {
    if (changedProps.has("hass") && this.hass) this._subscribe();
  }

  async _subscribe() {
    if (this._unsub || this._subscribing) return;
    this._subscribing = true;
    try {
      const unsub = await this.hass.connection.subscribeMessage(
        (event) => {
          if (event.snapshot) {
            this._diffs = event.snapshot.slice(-MAX_DIFFS);
          } else if (event.diff) {
            // The backend ring buffer only bounds the *snapshot*; live
            // appends are unbounded, so cap them here too.
            const appended = [...this._diffs, event.diff];
            this._diffs =
              appended.length > MAX_DIFFS ? appended.slice(-MAX_DIFFS) : appended;
          }
        },
        { type: "sber_mqtt_bridge/subscribe_state_diffs" }
      );
      if (!this.isConnected) {
        /* Detached mid-round-trip — drop instead of leaking. */
        unsub();
        return;
      }
      this._unsub = unsub;
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._subscribing = false;
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

  /**
   * Diffs grouped per entity, the most recently changed entity first and
   * each group newest first.  A flat list interleaves chatty sensors with
   * the device being debugged; grouping keeps one device's history together.
   */
  _groups() {
    const needle = this._query.trim().toLowerCase();
    const groups = new Map();
    for (let i = this._diffs.length - 1; i >= 0; i--) {
      const d = this._diffs[i];
      if (needle && !String(d.entity_id).toLowerCase().includes(needle)) continue;
      if (!groups.has(d.entity_id)) groups.set(d.entity_id, []);
      groups.get(d.entity_id).push(d);
    }
    return [...groups.entries()];
  }

  render() {
    const groups = this._groups();
    return html`
      <div class="section">
        <div class="section-header">
          <h2>${t(this.hass, "diff.title")}</h2>
          <div class="btn-group">
            <button class="btn-danger"
              ?disabled=${this._diffs.length === 0}
              @click=${this._clear}>
              ${t(this.hass, "diff.clear")}
            </button>
          </div>
        </div>
        <div class="hint">${t(this.hass, "diff.hint")}</div>
        ${this._error ? html`<div class="error-text">${this._error}</div>` : ""}
        <input type="search" class="search"
          aria-label=${t(this.hass, "diff.search")}
          placeholder=${t(this.hass, "diff.search")}
          .value=${this._query}
          @input=${(e) => { this._query = e.target.value; }}>
        <div class="diff-container">
          ${groups.length === 0
            ? html`<div class="empty">${this._diffs.length === 0 ? t(this.hass, "diff.empty") : t(this.hass, "diff.nothing_matches")}</div>`
            : groups.map(([entityId, diffs]) => this._renderGroup(entityId, diffs))}
        </div>
      </div>
    `;
  }

  _renderGroup(entityId, diffs) {
    const open = !!this._expanded[entityId];
    const earlier = diffs.length - 1;
    return html`
      <div class="group">
        ${this._renderDiff(diffs[0], diffs.length)}
        ${earlier > 0 ? html`
          <button class="more" aria-expanded=${open ? "true" : "false"}
            @click=${() => { this._expanded = { ...this._expanded, [entityId]: !open }; }}>
            ${t(this.hass, open ? "diff.hide_earlier" : "diff.show_earlier", { count: earlier })}
          </button>
          ${open ? diffs.slice(1).map((d) => this._renderDiff(d)) : ""}
        ` : ""}
      </div>
    `;
  }

  _renderDiff(d, count = 0) {
    const changedKeys = Object.keys(d.changed || {}).sort();
    const addedKeys = Object.keys(d.added || {}).sort();
    const removedKeys = Object.keys(d.removed || {}).sort();
    return html`
      <div class="diff ${d.is_initial ? "diff-initial" : ""}">
        <div class="diff-header">
          <span class="entity">${d.entity_id}</span>
          ${count > 1 ? html`<span class="count-badge" title=${t(this.hass, "diff.count_title", { count })}>×${count}</span>` : ""}
          <span class="topic">${d.topic}</span>
          ${d.is_initial ? html`<span class="initial-badge">${t(this.hass, "diff.initial")}</span>` : ""}
          <span class="time">${this._formatTime(d.ts)}</span>
        </div>
        <table class="delta-table">
          <tbody>
            ${changedKeys.map((k) => html`
              <tr class="delta delta-changed">
                <td class="copy-cell"><sber-copy-button .hass=${this.hass} .value=${{ key: k, ...d.changed[k] }}></sber-copy-button></td>
                <td class="op">~</td>
                <td class="key">${k}</td>
                <td class="from">${formatSberValue(d.changed[k].before)}</td>
                <td class="arrow">→</td>
                <td class="to">${formatSberValue(d.changed[k].after)}</td>
              </tr>
            `)}
            ${addedKeys.map((k) => html`
              <tr class="delta delta-added">
                <td class="copy-cell"><sber-copy-button .hass=${this.hass} .value=${{ key: k, after: d.added[k] }}></sber-copy-button></td>
                <td class="op">+</td>
                <td class="key">${k}</td>
                <td class="from"></td>
                <td class="arrow"></td>
                <td class="to">${formatSberValue(d.added[k])}</td>
              </tr>
            `)}
            ${removedKeys.map((k) => html`
              <tr class="delta delta-removed">
                <td class="copy-cell"><sber-copy-button .hass=${this.hass} .value=${{ key: k, before: d.removed[k] }}></sber-copy-button></td>
                <td class="op">−</td>
                <td class="key">${k}</td>
                <td class="from">${formatSberValue(d.removed[k])}</td>
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
      button:focus-visible,
      input:focus-visible,
      select:focus-visible,
      textarea:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
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
        flex-wrap: wrap;
        align-items: center;
        gap: 4px 12px;
        margin-bottom: 6px;
        font-size: 0.9em;
      }
      .entity { font-family: monospace; font-weight: 600; color: var(--primary-text-color); overflow-wrap: anywhere; }
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
      /* Fixed layout: with automatic layout the fixed-width key column left
       * the values a single character per line on a phone. */
      .delta-table { width: 100%; table-layout: fixed; border-collapse: collapse; font-family: monospace; font-size: 0.9em; }
      .delta td { padding: 2px 8px; vertical-align: top; }
      .op {
        width: 18px;
        font-weight: 700;
        text-align: center;
      }
      /* Fixed layout: the copy column needs a real width, not a share;
       * the narrow marker columns give it back so values keep their room. */
      .delta .copy-cell { width: 30px; padding: 2px 0 2px 4px; }
      .copy-cell sber-copy-button { margin-right: 0; }
      .delta .op, .delta .arrow { padding: 2px 2px; }
      .key { width: 30%; color: var(--primary-text-color); overflow-wrap: anywhere; }
      .from { color: var(--secondary-text-color); overflow-wrap: anywhere; }
      .arrow { width: 20px; text-align: center; color: var(--secondary-text-color); }
      .to { color: var(--primary-text-color); overflow-wrap: anywhere; }
      .delta-changed .op { color: var(--warning-color, #ff9800); }
      .delta-added .op { color: var(--success-color, #4caf50); }
      .delta-removed .op { color: var(--error-color, #f44336); }
      .delta-removed .from { text-decoration: line-through; }
      .search {
        width: 100%;
        box-sizing: border-box;
        margin-bottom: 8px;
        padding: 4px 8px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      .group { margin-bottom: 8px; }
      .group .diff { margin-bottom: 4px; }
      .count-badge {
        border: 1px solid var(--divider-color);
        border-radius: 10px;
        padding: 0 6px;
        font-size: 0.75em;
        color: var(--secondary-text-color);
      }
      .more {
        background: none;
        border: none;
        color: var(--primary-color, #03a9f4);
        cursor: pointer;
        font-size: 0.85em;
        padding: 2px 0 6px;
      }
    `;
  }
}

customElements.define("sber-state-diff", SberStateDiff);
