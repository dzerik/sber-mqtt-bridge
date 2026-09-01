/**
 * Sber MQTT Bridge — replay / inject Sber messages (DevTools #3).
 *
 * Two modes, one component:
 *
 *  1. Manual inject — textarea for the full payload + topic suffix
 *     selector (commands / status_request / config_request / ...).
 *  2. Replay from log — reads the shared message feed (``message-bus.js``,
 *     one subscription for the whole panel), shows the last
 *     N incoming messages with a "Replay" button on each.  Click it
 *     and the bridge feeds that exact payload back into its own
 *     dispatcher as if Sber had re-sent it — no network round-trip,
 *     works offline.
 *
 * Synthetic traffic is tagged with ``direction="replay"`` in the
 * message log (see :meth:`async_inject_sber_message`) so replays
 * never feed themselves in a loop.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);
const { messageBus } = await import(`../message-bus.js${_q}`);

const TOPIC_SUFFIXES = [
  "commands",
  "status_request",
  "config_request",
  "errors",
  "change_group",
  "rename_device",
];

const DEFAULT_PAYLOAD = JSON.stringify(
  {
    devices: {
      "switch.example": {
        states: [
          { key: "on_off", value: { type: "BOOL", bool_value: true } },
        ],
      },
    },
  },
  null,
  2
);

class SberReplay extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      bus: { type: Object },
      _messages: { type: Array },
      _topic: { type: String },
      _payload: { type: String },
      _busy: { type: Boolean },
      _status: { type: String },
      _statusKind: { type: String },
    };
  }

  constructor() {
    super();
    this._messages = [];
    this._topic = "commands";
    this._payload = DEFAULT_PAYLOAD;
    this._busy = false;
    this._status = "";
    this._statusKind = "";
    this._unsub = null;
    /** Shared live feed — one WS subscription for the whole panel. */
    this.bus = messageBus;
  }

  connectedCallback() {
    super.connectedCallback();
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

  _subscribe() {
    if (this._unsub || !this.bus || !this.hass) return;
    this._unsub = this.bus.subscribe(
      this.hass,
      (messages) => {
        this._messages = messages;
      },
      (e) => this._setStatus(`Subscribe failed: ${e.message || e}`, "error")
    );
  }

  _unsubscribe() {
    if (this._unsub) {
      this._unsub();
      this._unsub = null;
    }
  }

  _setStatus(text, kind = "info") {
    this._status = text;
    this._statusKind = kind;
  }

  async _inject() {
    if (this._busy) return;
    this._busy = true;
    this._setStatus(t(this.hass, "replay.injecting"), "info");
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/inject_sber_message",
        topic: this._topic,
        payload: this._payload,
        mark_replay: true,
      });
      this._setStatus(
        result.handled
          ? `Injected → ${result.suffix}`
          : `Unknown topic suffix: ${result.suffix}`,
        result.handled ? "success" : "warning"
      );
    } catch (e) {
      this._setStatus(`Inject failed: ${e.message || e}`, "error");
    } finally {
      this._busy = false;
    }
  }

  async _replayOne(topic, payload) {
    if (this._busy) return;
    this._busy = true;
    this._setStatus(t(this.hass, "replay.replaying"), "info");
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/replay_message",
        topic,
        payload,
      });
      this._setStatus(
        result.handled
          ? `Replayed → ${result.suffix}`
          : `Unknown topic: ${result.suffix}`,
        result.handled ? "success" : "warning"
      );
    } catch (e) {
      this._setStatus(`Replay failed: ${e.message || e}`, "error");
    } finally {
      this._busy = false;
    }
  }

  _formatTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString("ru-RU", { hour12: false });
  }

  _truncate(s, n = 80) {
    if (typeof s !== "string") s = String(s ?? "");
    return s.length > n ? s.slice(0, n) + "…" : s;
  }

  connectedCallback() {
    super.connectedCallback();
    ensurePanelTranslations(this.hass, this);
  }

  render() {
    // Only incoming real traffic is replayable — replays themselves
    // should not appear in the list or users would chain replays.
    const replayable = this._messages
      .filter((m) => m.direction === "in")
      .slice(-15)
      .reverse();

    return html`
      <div class="section">
        <div class="section-header">
          <h2>${t(this.hass, "replay.title")}</h2>
        </div>
        <div class="hint">
          Feed a Sber-shaped MQTT message into the bridge without touching the broker.  Works offline; the same dispatcher, correlation trace and state diff see it.
        </div>
        ${this._status ? html`<div class="status status-${this._statusKind}">${this._status}</div>` : ""}

        <div class="subsection">
          <h3>${t(this.hass, "replay.manual")}</h3>
          <div class="form-row">
            <label>${t(this.hass, "replay.topic")}</label>
            <select aria-label="${t(this.hass, 'replay.topic')}" .value=${this._topic} @change=${(e) => { this._topic = e.target.value; }}>
              ${TOPIC_SUFFIXES.map((s) => html`<option value="${s}">${s}</option>`)}
            </select>
          </div>
          <textarea class="json-editor"
            .value=${this._payload}
            spellcheck="false"
            @input=${(e) => { this._payload = e.target.value; }}
            placeholder="${t(this.hass, 'replay.payload_hint')}"></textarea>
          <div class="btn-bar">
            <button class="btn-primary"
              ?disabled=${this._busy || !this._payload.trim()}
              @click=${this._inject}>
              ${this._busy ? t(this.hass, "replay.busy") : t(this.hass, "replay.inject")}
            </button>
            <button class="btn-secondary"
              @click=${() => { this._payload = DEFAULT_PAYLOAD; }}>
              Reset template
            </button>
          </div>
        </div>

        <div class="subsection">
          <h3>${t(this.hass, "replay.from_log")}</h3>
          ${replayable.length === 0
            ? html`<div class="empty">No incoming messages yet. Real Sber traffic will appear here.</div>`
            : html`
              <table class="replay-table">
                <thead>
                  <tr>
                    <th>${t(this.hass, "replay.col_time")}</th>
                    <th>${t(this.hass, "replay.col_topic")}</th>
                    <th>${t(this.hass, "replay.col_payload")}</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  ${replayable.map((m) => html`
                    <tr>
                      <td class="t">${this._formatTime(m.time)}</td>
                      <td class="topic" title="${m.topic}">${this._shortTopic(m.topic)}</td>
                      <td class="payload" title="${m.payload}">${this._truncate(m.payload)}</td>
                      <td>
                        <button class="btn-secondary small"
                          ?disabled=${this._busy}
                          @click=${() => this._replayOne(m.topic, m.payload)}>
                          Replay
                        </button>
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

  _shortTopic(topic) {
    if (!topic) return "";
    const idx = topic.indexOf("/down/");
    return idx >= 0 ? topic.slice(idx + 1) : topic;
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
      .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
      h2 { margin: 0; font-size: 1.1em; color: var(--primary-text-color); }
      h3 { margin: 16px 0 8px; font-size: 0.95em; color: var(--primary-text-color); }
      .hint { color: var(--secondary-text-color); font-size: 0.85em; margin-bottom: 12px; }
      .status {
        padding: 6px 10px;
        border-radius: 4px;
        margin-bottom: 12px;
        font-size: 0.9em;
        font-family: monospace;
      }
      .status-info { background: var(--secondary-background-color); color: var(--primary-text-color); }
      .status-success { background: rgba(76, 175, 80, 0.12); color: var(--success-color, #4caf50); }
      .status-warning { background: rgba(255, 152, 0, 0.12); color: var(--warning-color, #ff9800); }
      .status-error { background: rgba(244, 67, 54, 0.12); color: var(--error-color, #f44336); }
      .subsection { border-top: 1px solid var(--divider-color); padding-top: 8px; }
      .form-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
      .form-row label { color: var(--secondary-text-color); font-size: 0.9em; }
      select {
        background: var(--primary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        padding: 6px 8px;
      }
      .json-editor {
        width: 100%;
        min-height: 160px;
        font-family: monospace;
        font-size: 0.85em;
        background: var(--primary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        padding: 8px;
        box-sizing: border-box;
        resize: vertical;
      }
      .btn-bar { display: flex; gap: 8px; margin-top: 8px; }
      .btn-primary {
        background: var(--primary-color, #03a9f4);
        color: white;
        border: none;
        border-radius: 4px;
        padding: 6px 14px;
        cursor: pointer;
      }
      .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
      .btn-secondary {
        background: var(--secondary-background-color);
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        padding: 6px 12px;
        cursor: pointer;
      }
      .btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }
      .btn-secondary.small { padding: 2px 8px; font-size: 0.85em; }
      .empty { color: var(--secondary-text-color); font-style: italic; padding: 12px; text-align: center; }
      .replay-table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
      .replay-table th {
        text-align: left;
        padding: 6px 8px;
        border-bottom: 1px solid var(--divider-color);
        color: var(--secondary-text-color);
        font-weight: 500;
      }
      .replay-table td { padding: 4px 8px; vertical-align: middle; }
      .t { font-family: monospace; color: var(--secondary-text-color); width: 80px; }
      .topic { font-family: monospace; width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .payload { font-family: monospace; color: var(--primary-text-color); }
    `;
  }
}

customElements.define("sber-replay", SberReplay);
