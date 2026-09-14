/**
 * Sber MQTT Bridge — command confirmation viewer (DevTools).
 *
 * Subscribes to ``sber_mqtt_bridge/subscribe_command_confirmations`` and
 * shows, for every Sber command, whether the state the bridge published
 * back to Sber afterwards carries the commanded values — key by key.
 *
 * A trace only proves a service call was made; this view answers the next
 * question, "did the device actually do it?" (issue #63: a cloud lamp took
 * ``turn_on`` and stayed off).
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { copyText, formatSberValue } = await import(`../utils.js${_q}`);
await import(`./sber-copy-button.js${_q}`);

/** Hard cap on the live buffer — live events are unbounded on the wire. */
const MAX_COMMANDS = 250;

/** Statuses in display order; each has a chip, a badge and a label. */
const STATUSES = ["pending", "confirmed", "partial", "not_confirmed", "superseded"];

class SberCommandConfirm extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _commands: { type: Array },
      _statusFilter: { type: String },
      _query: { type: String },
      _expanded: { type: Object },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this._commands = [];
    this._statusFilter = "";
    this._query = "";
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
            this._commands = event.snapshot.slice(-MAX_COMMANDS);
          } else if (event.command) {
            this._upsert(event.command);
          }
        },
        { type: "sber_mqtt_bridge/subscribe_command_confirmations" }
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

  _upsert(command) {
    const index = this._commands.findIndex((c) => c.command_id === command.command_id);
    if (index === -1) {
      const appended = [...this._commands, command];
      this._commands = appended.length > MAX_COMMANDS ? appended.slice(-MAX_COMMANDS) : appended;
      return;
    }
    const next = [...this._commands];
    next[index] = command;
    this._commands = next;
  }

  async _clear() {
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/clear_command_confirmations" });
      this._commands = [];
      this._expanded = {};
      this._error = "";
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  _toggle(commandId) {
    this._expanded = { ...this._expanded, [commandId]: !this._expanded[commandId] };
  }

  _formatTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString(this.hass?.locale?.language || this.hass?.language || undefined, { hour12: false }) +
      "." + String(d.getMilliseconds()).padStart(3, "0");
  }

  _visible() {
    const needle = this._query.trim().toLowerCase();
    return this._commands
      .filter((c) => !this._statusFilter || c.status === this._statusFilter)
      .filter((c) => !needle || c.entity_id.toLowerCase().includes(needle))
      .slice()
      .reverse();
  }

  render() {
    const counts = Object.fromEntries(STATUSES.map((s) => [s, 0]));
    for (const c of this._commands) counts[c.status] = (counts[c.status] || 0) + 1;
    const rows = this._visible();
    return html`
      <div class="section">
        <div class="section-header">
          <h2>${t(this.hass, "confirm.title")}</h2>
          <button class="btn-danger" ?disabled=${this._commands.length === 0} @click=${this._clear}>
            ${t(this.hass, "confirm.clear")}
          </button>
        </div>
        <div class="hint">${t(this.hass, "confirm.hint")}</div>
        ${this._error ? html`<div class="error-text">${this._error}</div>` : ""}
        <div class="filters">
          <div class="chips" role="group" aria-label=${t(this.hass, "confirm.filter_status")}>
            ${STATUSES.map((s) => html`
              <button class="chip status-${s} ${this._statusFilter === s ? "active" : ""}"
                aria-pressed=${this._statusFilter === s ? "true" : "false"}
                @click=${() => { this._statusFilter = this._statusFilter === s ? "" : s; }}>
                ${t(this.hass, `confirm.status_${s}`)} · ${counts[s]}
              </button>
            `)}
          </div>
          <input type="search" class="search"
            aria-label=${t(this.hass, "confirm.search")}
            placeholder=${t(this.hass, "confirm.search")}
            .value=${this._query}
            @input=${(e) => { this._query = e.target.value; }}>
        </div>
        <div class="list">
          ${rows.length === 0
            ? html`<div class="empty">${this._commands.length === 0 ? t(this.hass, "confirm.empty") : t(this.hass, "confirm.nothing_matches")}</div>`
            : rows.map((c) => this._renderCommand(c))}
        </div>
      </div>
    `;
  }

  _renderCommand(c) {
    const open = !!this._expanded[c.command_id];
    const matched = c.keys.filter((k) => k.matched).length;
    return html`
      <div class="command status-border-${c.status}">
        <div class="command-header" role="button" tabindex="0"
          aria-expanded=${open ? "true" : "false"}
          @click=${() => this._toggle(c.command_id)}
          @keydown=${(e) => {
            if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
            e.preventDefault();
            this._toggle(c.command_id);
          }}>
          <span class="caret ${open ? "open" : ""}">&#9654;</span>
          <span class="badge status-${c.status}">${t(this.hass, `confirm.status_${c.status}`)}</span>
          <span class="entity">${c.entity_id}</span>
          <span class="keys-count">${matched}/${c.keys.length}</span>
          <span class="time">${this._formatTime(c.sent_at)}</span>
        </div>
        ${open ? html`
          <div class="row-actions">
            <button class="btn-secondary" @click=${() => this._copy(c)}>${t(this.hass, "confirm.copy")}</button>
          </div>
          <table class="keys">
            <thead>
              <tr>
                <th class="copy-cell"><span class="visually-hidden">${t(this.hass, "json.copy")}</span></th>
                <th>${t(this.hass, "confirm.col_key")}</th>
                <th>${t(this.hass, "confirm.col_sent")}</th>
                <th>${t(this.hass, "confirm.col_reported")}</th>
                <th><span class="visually-hidden">${t(this.hass, "confirm.col_match")}</span></th>
              </tr>
            </thead>
            <tbody>
              ${c.keys.map((k) => html`
                <tr class=${k.matched ? "key-ok" : k.reported ? "key-diff" : "key-wait"}>
                  <td class="copy-cell"><sber-copy-button .hass=${this.hass} .value=${k}></sber-copy-button></td>
                  <td class="mono">${k.key}</td>
                  <td class="mono">${formatSberValue(k.sent)}</td>
                  <td class="mono">${formatSberValue(k.reported)}</td>
                  <td title=${t(this.hass, k.matched ? "confirm.key_matched" : k.reported ? "confirm.key_differs" : "confirm.key_not_reported")}>
                    ${k.matched ? "✓" : k.reported ? "✗" : "…"}
                  </td>
                </tr>
              `)}
            </tbody>
          </table>
        ` : ""}
      </div>
    `;
  }

  async _copy(command) {
    await copyText(JSON.stringify(command, null, 2));
  }

  static get styles() {
    return css`
      button:focus-visible,
      input:focus-visible,
      .command-header:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .section {
        background: var(--card-background-color);
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
        container: commands / inline-size;
      }
      .section-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 8px;
        margin-bottom: 6px;
      }
      h2 { margin: 0; font-size: 1.1em; color: var(--primary-text-color); }
      .hint { color: var(--secondary-text-color); font-size: 0.85em; margin-bottom: 12px; }
      .btn-danger, .btn-secondary {
        border: none;
        border-radius: 4px;
        padding: 6px 12px;
        cursor: pointer;
      }
      .btn-danger { background: var(--error-color, #f44336); color: white; }
      .btn-secondary {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
      }
      .btn-danger:disabled { opacity: 0.5; cursor: not-allowed; }
      .error-text { color: var(--error-color, #f44336); margin-bottom: 8px; font-size: 0.9em; }
      .empty { color: var(--secondary-text-color); font-style: italic; padding: 16px; text-align: center; }
      .filters { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 8px; }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .chip {
        border: 1px solid var(--divider-color);
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        border-radius: 12px;
        padding: 2px 10px;
        font-size: 0.8em;
        cursor: pointer;
      }
      .chip.active { border-color: currentColor; font-weight: 600; }
      .search {
        flex: 1 1 12em;
        min-width: 0;
        padding: 4px 8px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
      }
      .command {
        border: 1px solid var(--divider-color);
        border-left-width: 3px;
        border-radius: 4px;
        margin-bottom: 6px;
        overflow: hidden;
      }
      .command-header {
        display: grid;
        grid-template-columns: 16px auto minmax(0, 1fr) auto auto;
        gap: 8px;
        align-items: center;
        padding: 8px 12px;
        cursor: pointer;
        font-size: 0.9em;
      }
      .command-header:hover { background: var(--secondary-background-color); }
      .caret { color: var(--secondary-text-color); transition: transform 0.15s; display: inline-block; }
      .caret.open { transform: rotate(90deg); }
      .badge {
        padding: 2px 8px;
        border-radius: 12px;
        font-size: 0.75em;
        font-weight: 600;
        text-transform: uppercase;
        white-space: nowrap;
      }
      .entity { font-family: monospace; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .keys-count, .time { color: var(--secondary-text-color); font-family: monospace; font-size: 0.85em; }
      .status-pending { color: var(--primary-color, #03a9f4); }
      .status-confirmed { color: var(--success-color, #4caf50); }
      .status-partial { color: var(--warning-color, #ff9800); }
      .status-not_confirmed { color: var(--error-color, #f44336); }
      .status-superseded { color: var(--secondary-text-color); }
      .badge.status-pending { background: rgba(3, 169, 244, 0.15); }
      .badge.status-confirmed { background: rgba(76, 175, 80, 0.15); }
      .badge.status-partial { background: rgba(255, 152, 0, 0.15); }
      .badge.status-not_confirmed { background: rgba(244, 67, 54, 0.15); }
      .badge.status-superseded { background: var(--secondary-background-color); }
      .status-border-pending { border-left-color: var(--primary-color, #03a9f4); }
      .status-border-confirmed { border-left-color: var(--success-color, #4caf50); }
      .status-border-partial { border-left-color: var(--warning-color, #ff9800); }
      .status-border-not_confirmed { border-left-color: var(--error-color, #f44336); }
      .status-border-superseded { border-left-color: var(--divider-color); }
      .keys {
        width: 100%;
        table-layout: fixed;
        border-collapse: collapse;
        font-size: 0.85em;
        background: var(--secondary-background-color);
      }
      .keys th {
        text-align: left;
        padding: 4px 12px;
        color: var(--secondary-text-color);
        font-weight: 500;
        border-bottom: 1px solid var(--divider-color);
      }
      .keys th:last-child { width: 2em; }
      .keys td { padding: 4px 12px; vertical-align: top; overflow-wrap: anywhere; }
      .mono { font-family: monospace; }
      /* Fixed layout: the copy column needs a real width, not a share. */
      .keys .copy-cell { width: 34px; padding: 4px 0 4px 8px; }
      .keys .copy-cell sber-copy-button { margin-right: 0; }
      .key-ok td:last-child { color: var(--success-color, #4caf50); }
      .key-diff td:last-child, .key-diff td:nth-child(3) { color: var(--error-color, #f44336); }
      .key-wait td:last-child { color: var(--secondary-text-color); }
      .row-actions { padding: 6px 12px; background: var(--secondary-background-color); }
      .visually-hidden {
        position: absolute;
        width: 1px;
        height: 1px;
        overflow: hidden;
        clip: rect(0 0 0 0);
      }
      @container commands (max-width: 520px) {
        .command-header {
          grid-template-columns: 16px auto minmax(0, 1fr) auto;
          grid-template-areas:
            "caret badge count time"
            "caret entity entity entity";
          row-gap: 4px;
        }
        .caret { grid-area: caret; }
        .badge { grid-area: badge; justify-self: start; }
        .entity { grid-area: entity; }
        .keys-count { grid-area: count; }
        .time { grid-area: time; }
      }
    `;
  }
}

customElements.define("sber-command-confirm", SberCommandConfirm);
