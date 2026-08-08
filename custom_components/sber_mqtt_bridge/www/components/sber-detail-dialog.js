/**
 * Sber MQTT Bridge — Device detail dialog component.
 *
 * Shows full device info: Sber state, linked sensors, HA attributes,
 * device registry data, model config with features and allowed values.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
await import(`./sber-json-block.js${_q}`);

const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { deepActiveElement } = await import(`../utils.js${_q}`);

/** Delay between two confirmation re-reads after a save. */
const RELOAD_INTERVAL_MS = 200;
/** Give up waiting for the saved overrides after this long. */
const RELOAD_TIMEOUT_MS = 8000;

class SberDetailDialog extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      open: { type: Boolean, reflect: true },
      _data: { type: Object },
      _loading: { type: Boolean },
      _error: { type: String },
      _saveStatus: { type: String },
      _saveError: { type: String },
    };
  }

  static get styles() {
    return css`
      :host {
        display: none;
      }
      :host([open]) {
        display: block;
        position: fixed;
        inset: 0;
        z-index: 1000;
        background: rgba(0, 0, 0, 0.6);
        backdrop-filter: blur(2px);
      }
      .dialog {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: var(--card-background-color, #1c1c1c);
        border-radius: 12px;
        width: min(720px, 92vw);
        max-height: 85vh;
        overflow-y: auto;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
      }
      .header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        border-bottom: 1px solid var(--divider-color, #333);
        position: sticky;
        top: 0;
        background: var(--card-background-color, #1c1c1c);
        z-index: 1;
      }
      .header h2 {
        margin: 0;
        font-size: 18px;
      }
      .close-btn {
        cursor: pointer;
        font-size: 24px;
        background: none;
        border: none;
        color: var(--primary-text-color);
        padding: 4px 8px;
      }
      .close-btn:focus-visible,
      button:focus-visible,
      input:focus-visible,
      select:focus-visible,
      .dialog:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }
      .body {
        padding: 16px 20px;
      }
      .section {
        margin-bottom: 20px;
      }
      .section-title {
        font-size: 13px;
        font-weight: 600;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        margin-bottom: 8px;
        letter-spacing: 0.5px;
      }
      .grid {
        display: grid;
        grid-template-columns: 140px 1fr;
        gap: 4px 12px;
        font-size: 13px;
      }
      .grid .label {
        color: var(--secondary-text-color);
        white-space: nowrap;
      }
      .grid .value {
        word-break: break-all;
      }
      .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 10px;
        font-size: 11px;
        color: #fff;
      }
      .badge-green { background: var(--success-color, #4caf50); }
      .badge-grey { background: #9e9e9e; }
      .badge-yellow { background: var(--warning-color, #ff9800); }
      .state-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 13px;
      }
      .state-table th {
        text-align: left;
        padding: 4px 8px;
        color: var(--secondary-text-color);
        font-weight: 500;
        border-bottom: 1px solid var(--divider-color, #333);
      }
      .state-table td {
        padding: 4px 8px;
        border-bottom: 1px solid var(--divider-color, #222);
      }
      .state-table code {
        background: var(--code-editor-background-color, #2a2a2a);
        padding: 1px 6px;
        border-radius: 4px;
        font-size: 12px;
      }
      .feature-tag {
        display: inline-block;
        padding: 1px 6px;
        margin: 1px 2px;
        border-radius: 8px;
        font-size: 11px;
        background: var(--accent-color, #448aff);
        color: #fff;
      }
      .linked-card {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        margin: 4px 0;
        border-radius: 8px;
        background: var(--secondary-background-color, #222);
      }
      .linked-role {
        font-size: 11px;
        padding: 2px 8px;
        border-radius: 8px;
        background: var(--info-color, #2196f3);
        color: #fff;
        white-space: nowrap;
      }
      .linked-name { flex: 1; font-size: 13px; }
      .linked-state { font-size: 13px; color: var(--secondary-text-color); }
      .loading {
        text-align: center;
        padding: 40px;
        color: var(--secondary-text-color);
      }
      .error {
        color: var(--error-color, #f44336);
        padding: 16px;
      }

      .edit-form {
        display: grid;
        grid-template-columns: 80px 1fr;
        gap: 8px 12px;
        align-items: center;
      }
      .edit-label {
        font-size: 12px;
        font-weight: 500;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.3px;
      }
      .edit-input {
        padding: 8px 12px;
        border: 1px solid var(--divider-color, #444);
        border-radius: 6px;
        font-size: 13px;
        background: var(--secondary-background-color, #2a2a2a);
        color: var(--primary-text-color);
        outline: none;
      }
      .edit-input:focus {
        border-color: var(--primary-color);
      }
      .edit-actions {
        grid-column: 1 / -1;
        display: flex;
        align-items: center;
        gap: 12px;
        margin-top: 4px;
      }
      .edit-save {
        padding: 8px 20px;
        border: none;
        border-radius: 6px;
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        background: var(--primary-color);
        color: #fff;
        transition: opacity 0.15s;
      }
      .edit-save:hover { opacity: 0.85; }
      .save-status {
        font-size: 12px;
        font-weight: 500;
      }
      .save-status.ok { color: var(--success-color, #4caf50); }
      .save-status.error { color: var(--error-color, #f44336); }

      /* ── Mobile ── */
      @media (max-width: 768px) {
        .dialog {
          width: 100vw;
          max-height: 100vh;
          border-radius: 0;
          top: 0;
          left: 0;
          transform: none;
        }
        .header {
          padding: 12px 16px;
        }
        .header h2 {
          font-size: 16px;
        }
        .body {
          padding: 12px 16px;
        }
        .grid {
          grid-template-columns: 1fr;
          gap: 2px;
        }
        .edit-form {
          grid-template-columns: 1fr;
        }
        .edit-label {
          margin-top: 4px;
        }
        .grid .label {
          font-size: 11px;
          margin-top: 6px;
        }
        .state-table {
          font-size: 12px;
        }
        .state-table th,
        .state-table td {
          padding: 3px 6px;
        }
      }
    `;
  }

  constructor() {
    super();
    this.open = false;
    this._data = null;
    this._loading = false;
    this._error = "";
    this._saveStatus = "";
    this._saveError = "";
  }

  /**
   * Re-read the detail payload until the saved overrides come back.
   *
   * ``update_redefinitions`` returns before the entry reload has rebuilt
   * the device, so a single re-fetch races it.  Polling replaces a fixed
   * sleep: it is neither too early on a slow install nor needlessly slow
   * on a fast one, and it stops the moment the user closes the dialog.
   *
   * @param {string} entityId - Entity being edited.
   * @param {object} expected - ``{name, room, home}`` that were submitted.
   * @returns {Promise<boolean>} False if the timeout expired first.
   */
  async _reloadUntilSaved(entityId, expected) {
    const deadline = Date.now() + RELOAD_TIMEOUT_MS;
    for (;;) {
      await this._fetchDetail(entityId);
      /* Identity first: a payload describing some *other* entity says
       * nothing about this save, even when its redefinitions happen to
       * carry the same name/room. */
      if (this._data?.entity_id !== entityId) return false;
      /* ``_fetchDetail`` swallows its failure into ``_error`` and leaves the
       * previous payload in place — retrying a broken backend for the whole
       * window would only stall the dialog. */
      if (this._error) return false;
      const saved = this._data?.redefinitions || {};
      const applied = ["name", "room", "home"].every(
        (key) => (saved[key] || "") === (expected[key] || "")
      );
      if (applied) return true;
      /* The dialog was closed — stop polling. */
      if (!this.open || !this.isConnected) return false;
      if (Date.now() >= deadline) return false;
      await new Promise((r) => setTimeout(r, RELOAD_INTERVAL_MS));
    }
  }

  /**
   * Fetch the detail payload for ``entityId`` into ``_data``.
   *
   * @param {string} entityId - Entity to describe.
   */
  async _fetchDetail(entityId) {
    this._loading = true;
    this._error = "";
    try {
      this._data = await this.hass.callWS({
        type: "sber_mqtt_bridge/device_detail",
        entity_id: entityId,
      });
    } catch (e) {
      this._error = e.message || "Failed to load device details";
    } finally {
      this._loading = false;
    }
  }

  async show(entityId) {
    if (!this.hass) return;
    this._returnFocusTo = deepActiveElement();
    this.open = true;
    this._loading = true;
    this._error = "";
    this._saveStatus = "";
    this._saveError = "";
    this._data = null;
    await this._fetchDetail(entityId);
  }

  hide() {
    this.open = false;
    /* Return focus to the device-name link that opened us (WCAG 2.4.3). */
    const target = this._returnFocusTo;
    this._returnFocusTo = null;
    if (target && typeof target.focus === "function") target.focus();
  }

  connectedCallback() {
    super.connectedCallback();
    /* Modal keyboard contract: Escape closes. */
    this._escHandler = (e) => {
      if (this.open && e.key === "Escape") {
        e.stopPropagation();
        this.hide();
      }
    };
    document.addEventListener("keydown", this._escHandler);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._escHandler) {
      document.removeEventListener("keydown", this._escHandler);
      this._escHandler = null;
    }
  }

  render() {
    if (!this.open) return html``;
    return html`
      <div
        class="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-dialog-title"
        tabindex="-1"
        @click=${(e) => e.stopPropagation()}
      >
        ${this._loading
          ? html`<div class="loading">Loading...</div>`
          : this._error
            ? html`<div class="error">${this._error}</div>`
            : this._renderContent()}
      </div>
    `;
  }

  updated(changed) {
    if (changed.has("open") && this.open) {
      // Close on backdrop click
      this.addEventListener("click", this._onBackdropClick);
      const dialog = this.shadowRoot.querySelector(".dialog");
      if (dialog) dialog.focus();
    }
  }

  _onBackdropClick = () => { this.hide(); };

  _renderContent() {
    const d = this._data;
    if (!d) return html``;

    return html`
      <div class="header">
        <h2 id="detail-dialog-title">${d.name || d.entity_id}</h2>
        <button class="close-btn" aria-label="Close details" @click=${() => this.hide()}>\u2715</button>
      </div>
      <div class="body">
        ${this._renderEditForm(d)}
        ${this._renderOverview(d)}
        ${this._renderSberStates(d)}
        ${d.linked_entities?.length ? this._renderLinkedEntities(d) : ""}
        ${this._renderModel(d)}
        ${this._renderHAAttributes(d)}
        ${d.device_info ? this._renderDeviceInfo(d) : ""}
      </div>
    `;
  }

  _renderOverview(d) {
    const statusClass = d.is_online ? "badge-green" : d.is_filled ? "badge-grey" : "badge-yellow";
    const statusText = d.is_online ? "Online" : d.is_filled ? "Offline" : "Loading\u2026";
    return html`
      <div class="section">
        <div class="section-title">Overview</div>
        <div class="grid">
          <span class="label">Entity ID</span>
          <span class="value"><code>${d.entity_id}</code></span>
          <span class="label">Sber Category</span>
          <span class="value"><code>${d.sber_category}</code></span>
          <span class="label">HA State</span>
          <span class="value">${d.ha_state ?? "\u2014"}</span>
          <span class="label">Status</span>
          <span class="value"><span class="badge ${statusClass}">${statusText}</span></span>
          <span class="label">Room</span>
          <span class="value">${d.room || "\u2014"}</span>
          <span class="label">Features</span>
          <span class="value">${(d.features || []).map((f) => html`<span class="feature-tag">${f}</span>`)}</span>
        </div>
      </div>
    `;
  }

  _renderSberStates(d) {
    const states = d.sber_states || [];
    if (!states.length) return html`<div class="section"><div class="section-title">Sber States</div><span style="color:var(--secondary-text-color);font-size:13px">No state data</span></div>`;
    return html`
      <div class="section">
        <div class="section-title">Sber States (current)</div>
        <table class="state-table">
          <tr><th>Key</th><th>Type</th><th>Value</th></tr>
          ${states.map((s) => {
            const v = s.value || {};
            const displayVal = v.bool_value !== undefined ? String(v.bool_value)
              : v.integer_value !== undefined ? v.integer_value
              : v.enum_value !== undefined ? v.enum_value
              : v.colour_value ? `H:${v.colour_value.h} S:${v.colour_value.s} V:${v.colour_value.v}`
              : JSON.stringify(v);
            return html`<tr>
              <td><code>${s.key}</code></td>
              <td><code>${v.type || "?"}</code></td>
              <td>${displayVal}</td>
            </tr>`;
          })}
        </table>
      </div>
    `;
  }

  _renderLinkedEntities(d) {
    return html`
      <div class="section">
        <div class="section-title">Linked Entities</div>
        ${d.linked_entities.map((le) => html`
          <div class="linked-card">
            <span class="linked-role">${le.role}</span>
            <span class="linked-name">${le.friendly_name}<br><code style="font-size:11px;color:var(--secondary-text-color)">${le.entity_id}</code></span>
            <span class="linked-state">${le.state ?? "\u2014"}</span>
          </div>
        `)}
      </div>
    `;
  }

  _renderModel(d) {
    const model = d.sber_model || {};
    if (!model.category) return "";
    const av = model.allowed_values || {};
    const deps = model.dependencies || {};
    return html`
      <div class="section">
        <div class="section-title">Sber Model Config</div>
        <div class="grid">
          <span class="label">Model ID</span>
          <span class="value"><code>${model.id || "\u2014"}</code></span>
          <span class="label">Manufacturer</span>
          <span class="value">${model.manufacturer || "\u2014"}</span>
          <span class="label">Model</span>
          <span class="value">${model.model || "\u2014"}</span>
        </div>
        ${Object.keys(av).length ? html`
          <div style="margin-top:8px">
            <div class="section-title" style="margin-bottom:4px">Allowed Values</div>
            <sber-json-block label="Allowed Values" .value=${av}></sber-json-block>
          </div>
        ` : ""}
        ${Object.keys(deps).length ? html`
          <div style="margin-top:8px">
            <div class="section-title" style="margin-bottom:4px">Dependencies</div>
            <sber-json-block label="Dependencies" .value=${deps}></sber-json-block>
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderHAAttributes(d) {
    const attrs = d.ha_attributes || {};
    const keys = Object.keys(attrs);
    if (!keys.length) return "";
    return html`
      <div class="section">
        <div class="section-title">HA Attributes</div>
        <table class="state-table">
          <tr><th>Attribute</th><th>Value</th></tr>
          ${keys.map((k) => {
            const v = attrs[k];
            const display = typeof v === "object" ? JSON.stringify(v) : String(v);
            return html`<tr><td><code>${k}</code></td><td>${display}</td></tr>`;
          })}
        </table>
      </div>
    `;
  }

  _renderDeviceInfo(d) {
    const di = d.device_info;
    return html`
      <div class="section">
        <div class="section-title">HA Device Registry</div>
        <div class="grid">
          <span class="label">Device Name</span>
          <span class="value">${di.name || "\u2014"}</span>
          <span class="label">Manufacturer</span>
          <span class="value">${di.manufacturer || "\u2014"}</span>
          <span class="label">Model</span>
          <span class="value">${di.model || "\u2014"}</span>
          <span class="label">SW Version</span>
          <span class="value">${di.sw_version || "\u2014"}</span>
          <span class="label">HW Version</span>
          <span class="value">${di.hw_version || "\u2014"}</span>
          <span class="label">Area</span>
          <span class="value">${di.area_id || "\u2014"}</span>
        </div>
      </div>
    `;
  }

  _renderEditForm(d) {
    const r = d.redefinitions || {};
    return html`
      <div class="section">
        <div class="section-title">Sber Override</div>
        <div class="edit-form">
          <label class="edit-label" for="edit-name">Name</label>
          <input class="edit-input" type="text" id="edit-name"
            .value=${r.name || d.name || ""}
            placeholder=${d.name || d.entity_id} />
          <label class="edit-label" for="edit-room">Room</label>
          <input class="edit-input" type="text" id="edit-room"
            .value=${r.room || d.room || ""}
            placeholder=${d.room || "Room name"} />
          <label class="edit-label" for="edit-home">Home</label>
          <input class="edit-input" type="text" id="edit-home"
            .value=${r.home || ""}
            placeholder="Home name" />
          <div class="edit-actions">
            <button class="edit-save" @click=${this._onSave}>
              \u{1F4BE} Save & Re-publish
            </button>
            ${this._saveStatus ? html`<span class="save-status ${this._saveStatus}" title=${this._saveError || ""}>${this._saveStatus === "ok" ? "\u2713 Saved" : `\u2717 ${this._saveError || "Error"}`}</span>` : ""}
          </div>
        </div>
      </div>
    `;
  }

  async _onSave() {
    if (!this.hass || !this._data) return;
    const name = this.shadowRoot.getElementById("edit-name")?.value?.trim() || "";
    const room = this.shadowRoot.getElementById("edit-room")?.value?.trim() || "";
    const home = this.shadowRoot.getElementById("edit-home")?.value?.trim() || "";
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/update_redefinitions",
        entity_id: this._data.entity_id,
        name,
        room,
        home,
      });
      this._saveStatus = "ok";
      this.requestUpdate();
      await this._reloadUntilSaved(this._data.entity_id, { name, room, home });
    } catch (e) {
      this._saveStatus = "error";
      this._saveError = e.message || String(e);
      this.requestUpdate();
    }
  }
}

customElements.define("sber-detail-dialog", SberDetailDialog);
