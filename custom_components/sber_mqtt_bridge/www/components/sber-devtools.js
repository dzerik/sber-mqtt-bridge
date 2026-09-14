/**
 * Sber MQTT Bridge — DevTools component for MQTT protocol debugging.
 *
 * Three collapsible sections:
 * 1. Raw Config Payload — JSON sent to up/config
 * 2. Raw State Payload — JSON sent to up/status
 * 3. MQTT Message Log — real-time ring buffer, fed by the shared
 *    ``message-bus.js`` subscription (also consumed by sber-replay)
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
await import(`./sber-json-block.js${_q}`);

await import(`./sber-copy-button.js${_q}`);
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations, sberErrorText } = await import(`../localize.js${_q}`);
const { messageBus } = await import(`../message-bus.js${_q}`);
const { copyText, filterMessages, logTopics, topicSuffix } = await import(`../utils.js${_q}`);
const { codeSurfaceStyles } = await import(`../shared-styles.js${_q}`);

/** Row styling per message direction.  ``replay`` marks DevTools injections:
 * they travel inward, but drawing them as ordinary inbound traffic would
 * hide that they never came from Sber. */
const DIRECTION_STYLE = {
  in: { badge: "badge-in", arrow: "\u2190" },
  out: { badge: "badge-out", arrow: "\u2192" },
  replay: { badge: "badge-replay", arrow: "\u21BB" },
};

class SberDevtools extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      bus: { type: Object },
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
      _logDirection: { type: String },
      _logTopic: { type: String },
      _logQuery: { type: String },
      _logPaused: { type: Boolean },
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
    this._configOpen = false;
    this._statesOpen = false;
    this._configEditable = "";
    this._statesEditable = "";
    this._sendingConfig = false;
    this._sendingStates = false;
    this._logDirection = "all";
    this._logTopic = "";
    this._logQuery = "";
    this._logPaused = false;
    /** Snapshot shown while paused; the live buffer keeps filling underneath. */
    this._logFrozen = [];
    this._msgUnsub = null;
    /** Shared live feed — one WS subscription for the whole panel. */
    this.bus = messageBus;
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
    /* Re-subscribe on re-attach: HA navigation away from the panel and
     * back reuses the same element instance, and disconnectedCallback
     * has torn the previous subscription down. */
    if (this.hass) this._subscribeMessages();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._unsubscribeMessages();
  }

  updated(changedProps) {
    if (changedProps.has("hass") && this.hass) this._subscribeMessages();
  }

  _subscribeMessages() {
    if (this._msgUnsub || !this.bus || !this.hass) return;
    this._msgUnsub = this.bus.subscribe(
      this.hass,
      (messages) => {
        this._messages = messages;
      },
      (err) => {
        this._logError = err.message || String(err);
      }
    );
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
      /* Publish through the bus so every consumer of the shared feed
       * (Replay) sees the same buffer instead of drifting apart. */
      this.bus.replace(result.messages || []);
      this._logError = "";
    } catch (e) {
      this._logError = e.message || String(e);
    }
  }

  async _clearLog() {
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/clear_message_log" });
      this.bus.clear();
      this._logError = "";
    } catch (e) {
      this._logError = e.message || String(e);
    }
  }

  async _sendConfig() {
    this._sendingConfig = true;
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/send_raw_config", payload: this._configEditable });
      this._toast(t(this.hass, "devtools.config_sent"), "success");
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
      this._toast(t(this.hass, "devtools.states_sent"), "success");
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

  /**
   * Copy text and report the outcome through the panel toast.
   *
   * @param {string} text - Text to copy.
   * @param {string} [label] - Success message.
   */
  async _copy(text, label = null) {
    const ok = await copyText(text);
    this._toast(ok ? label || t(this.hass, "devtools.copied") : t(this.hass, "devtools.copy_failed"), ok ? "success" : "error");
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
    return [codeSurfaceStyles, css`
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
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 12px;
      }

      .section-header h2 {
        margin: 0;
        font-size: 18px;
        font-weight: 500;
      }

      .section-title:focus-visible,
      .btn:focus-visible,
      button:focus-visible,
      textarea:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
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
        flex-wrap: wrap;
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

      /* Composes .code-surface from shared-styles.js; only the editor's own
       * box model lives here.  A textarea keeps a native scrollbar and the
       * caret to prove there is more text, so bounding its height does not
       * mislead the way a cropped read-only dump did (issue #44). */
      .json-editor {
        width: 100%;
        min-height: 120px;
        max-height: 300px;
        border: 1px solid var(--divider-color, #555);
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

      .log-filters {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
        margin-bottom: 8px;
      }

      .log-filters select,
      .log-filters input {
        padding: 4px 8px;
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        background: var(--card-background-color);
        color: var(--primary-text-color);
        font-size: 13px;
      }

      .log-search {
        flex: 1 1 12em;
        min-width: 0;
      }

      .log-count {
        color: var(--secondary-text-color);
        font-size: 12px;
      }

      .log-row-replay {
        color: var(--accent-color, #ab47bc);
      }

      .badge-replay {
        background: rgba(171, 71, 188, 0.15);
        color: var(--accent-color, #ab47bc);
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
      .sber-error-hint {
        display: block;
        white-space: normal;
        font-size: 11px;
        color: var(--error-color, #f44336);
      }

      .empty-log {
        text-align: center;
        padding: 24px;
        color: var(--secondary-text-color);
        font-style: italic;
      }

      .log-container {
        max-height: 400px;
        overflow: auto;
        border-radius: 8px;
      }
    `];
  }

  /* ---------- render ---------- */

  render() {
    return html`
      ${this._renderConfigSection()}
      ${this._renderStatesSection()}
      ${this._renderLogSection()}
    `;
  }

  /** Activate a ``role="button"`` collapse header from the keyboard. */
  _onKeyActivate(e, handler) {
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    e.preventDefault();
    handler();
  }

  _renderConfigSection() {
    return html`
      <div class="section">
        <div class="section-header">
          <div
            class="section-title"
            role="button"
            tabindex="0"
            aria-expanded=${this._configOpen ? "true" : "false"}
            aria-label="${t(this.hass, 'devtools.raw_config')}"
            @click=${() => { this._configOpen = !this._configOpen; }}
            @keydown=${(e) => this._onKeyActivate(e, () => { this._configOpen = !this._configOpen; })}
          >
            <span class="collapse-icon ${this._configOpen ? "open" : ""}">&#9654;</span>
            <h2>${t(this.hass, "devtools.raw_config")}</h2>
          </div>
          <div class="btn-group">
            <button class="btn-primary"
              ?disabled=${this._configLoading}
              @click=${this._loadConfig}>
              ${this._configLoading ? t(this.hass, "devtools.loading") : t(this.hass, "devtools.load_config")}
            </button>
          </div>
        </div>
        ${this._configError ? html`<div class="error-text">${this._configError}</div>` : ""}
        ${this._configOpen ? html`
          <sber-json-block .hass=${this.hass}
            label="${t(this.hass, 'devtools.raw_config')}"
            placeholder="${t(this.hass, 'devtools.load_hint')}"
            .value=${this._configPayload}
          ></sber-json-block>
          <textarea class="json-editor code-surface"
            .value=${this._configEditable}
            @input=${(e) => { this._configEditable = e.target.value; }}
            placeholder="${t(this.hass, 'devtools.edit_hint')}"></textarea>
          <div class="send-bar">
            <button class="btn-danger"
              ?disabled=${this._sendingConfig || !this._configEditable}
              @click=${this._sendConfig}>
              ${this._sendingConfig ? t(this.hass, "devtools.sending") : t(this.hass, "devtools.send_config")}
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
          <div
            class="section-title"
            role="button"
            tabindex="0"
            aria-expanded=${this._statesOpen ? "true" : "false"}
            aria-label="${t(this.hass, 'devtools.raw_states')}"
            @click=${() => { this._statesOpen = !this._statesOpen; }}
            @keydown=${(e) => this._onKeyActivate(e, () => { this._statesOpen = !this._statesOpen; })}
          >
            <span class="collapse-icon ${this._statesOpen ? "open" : ""}">&#9654;</span>
            <h2>${t(this.hass, "devtools.raw_states")}</h2>
          </div>
          <div class="btn-group">
            <button class="btn-primary"
              ?disabled=${this._statesLoading}
              @click=${this._loadStates}>
              ${this._statesLoading ? t(this.hass, "devtools.loading") : t(this.hass, "devtools.load_states")}
            </button>
          </div>
        </div>
        ${this._statesError ? html`<div class="error-text">${this._statesError}</div>` : ""}
        ${this._statesOpen ? html`
          <sber-json-block .hass=${this.hass}
            label="${t(this.hass, 'devtools.raw_states')}"
            placeholder="${t(this.hass, 'devtools.load_hint')}"
            .value=${this._statesPayload}
          ></sber-json-block>
          <textarea class="json-editor code-surface"
            .value=${this._statesEditable}
            @input=${(e) => { this._statesEditable = e.target.value; }}
            placeholder="${t(this.hass, 'devtools.edit_hint')}"></textarea>
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

  /**
   * Spell out the error code of a `down/errors` packet.
   *
   * The raw payload right above says `"code": 403` and nothing else;
   * only Sber's reference says that 403 means the token was rejected —
   * a different problem from 400 (our payload is wrong) and from 503
   * (the cloud is down).  The backend decodes the packet
   * (`message_logger.parse_sber_error`), this renders the meaning.
   *
   * @param {{code: ?number}|undefined} error - Decoded error attached to
   *   the log entry, absent on every other topic.
   * @returns {unknown} Lit template, or "" when the entry is not an error.
   */
  _renderSberError(error) {
    if (!error) return "";
    const meaning = sberErrorText(this.hass, error.code);
    if (!meaning) return "";
    return html`<span class="sber-error-hint">${error.code} \u2014 ${meaning}</span>`;
  }

  _toggleLogPause() {
    this._logFrozen = this._logPaused ? [] : [...this._messages];
    this._logPaused = !this._logPaused;
  }

  /** Log rows after pause and filters, newest first — what the table shows. */
  _visibleLog() {
    const source = this._logPaused ? this._logFrozen : this._messages;
    return filterMessages(source, {
      direction: this._logDirection,
      topic: this._logTopic,
      query: this._logQuery,
    }).reverse();
  }

  _copyVisibleLog() {
    this._copy(JSON.stringify(this._visibleLog(), null, 2));
  }

  _renderLogSection() {
    const source = this._logPaused ? this._logFrozen : this._messages;
    const messages = this._visibleLog();
    const arrivedWhilePaused = this._logPaused ? Math.max(0, this._messages.length - this._logFrozen.length) : 0;

    return html`
      <div class="section">
        <div class="section-header">
          <h2>${t(this.hass, "devtools.message_log")}</h2>
          <div class="btn-group">
            <button class="btn-secondary" @click=${this._toggleLogPause} aria-pressed=${this._logPaused ? "true" : "false"}>
              ${this._logPaused ? t(this.hass, "devtools.log_resume") : t(this.hass, "devtools.log_pause")}
            </button>
            <button class="btn-secondary" ?disabled=${messages.length === 0} @click=${this._copyVisibleLog}>
              ${t(this.hass, "devtools.log_copy_shown")}
            </button>
            <button class="btn-secondary" @click=${this._fetchLog}>
              ${t(this.hass, "devtools.refresh")}
            </button>
            <button class="btn-danger"
              ?disabled=${this._messages.length === 0}
              @click=${this._clearLog}>
              ${t(this.hass, "devtools.clear_log")}
            </button>
          </div>
        </div>
        ${this._logError ? html`<div class="error-text">${this._logError}</div>` : ""}
        <div class="log-filters">
          <select aria-label=${t(this.hass, "devtools.col_dir")} .value=${this._logDirection}
            @change=${(e) => { this._logDirection = e.target.value; }}>
            <option value="all">${t(this.hass, "devtools.log_all_directions")}</option>
            <option value="in">${t(this.hass, "devtools.log_dir_in")}</option>
            <option value="out">${t(this.hass, "devtools.log_dir_out")}</option>
            <option value="replay">${t(this.hass, "devtools.log_dir_replay")}</option>
          </select>
          <select aria-label=${t(this.hass, "devtools.col_topic")} .value=${this._logTopic}
            @change=${(e) => { this._logTopic = e.target.value; }}>
            <option value="">${t(this.hass, "devtools.log_all_topics")}</option>
            ${logTopics(source).map((topic) => html`<option value=${topic}>${topic}</option>`)}
          </select>
          <input type="search" class="log-search"
            aria-label=${t(this.hass, "devtools.log_search")}
            placeholder=${t(this.hass, "devtools.log_search")}
            .value=${this._logQuery}
            @input=${(e) => { this._logQuery = e.target.value; }}>
          <span class="log-count">
            ${t(this.hass, "devtools.log_shown", { shown: messages.length, total: source.length })}
            ${arrivedWhilePaused ? html` · ${t(this.hass, "devtools.log_new_while_paused", { count: arrivedWhilePaused })}` : ""}
          </span>
        </div>
        <div class="log-container">
          ${messages.length === 0
            ? html`<div class="empty-log">${source.length === 0 ? t(this.hass, "devtools.log_empty") : t(this.hass, "devtools.log_nothing_matches")}</div>`
            : html`
              <table class="log-table">
                <thead>
                  <tr>
                    <th>${t(this.hass, "devtools.col_time")}</th>
                    <th>${t(this.hass, "devtools.col_dir")}</th>
                    <th>${t(this.hass, "devtools.col_topic")}</th>
                    <th>${t(this.hass, "devtools.col_payload")}</th>
                  </tr>
                </thead>
                <tbody>
                  ${messages.map(m => html`
                    <tr class="log-row-${DIRECTION_STYLE[m.direction] ? m.direction : "out"}">
                      <td>${this._formatTime(m.time)}</td>
                      <td>
                        <span class="direction-badge ${DIRECTION_STYLE[m.direction]?.badge || "badge-out"}"
                          title=${m.direction}>
                          ${DIRECTION_STYLE[m.direction]?.arrow || "\u2192"}
                        </span>
                      </td>
                      <td class="topic-cell" title="${m.topic}">${topicSuffix(m.topic)}</td>
                      <td class="payload-cell" title="${m.payload}">
                        <sber-copy-button .hass=${this.hass} .value=${m.payload}></sber-copy-button>${this._truncate(m.payload)}
                        ${this._renderSberError(m.sber_error)}
                      </td>
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
