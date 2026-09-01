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
const { t, ensurePanelTranslations } = await import(`../localize.js${_q}`);

/**
 * Upper bound the backend accepts for the gate travel time, in seconds.
 *
 * Mirrors ``MAX_TRAVEL_TIME_SECONDS`` in ``devices/gate.py``: the input
 * refuses out-of-range values here instead of letting the save fail with
 * a raw voluptuous message.
 */
const MAX_TRAVEL_TIME_SECONDS = 600;

/**
 * Upper bound the backend accepts for the gate auto-close delay, in seconds.
 *
 * Mirrors ``MAX_AUTO_CLOSE_TIME_SECONDS`` in ``devices/gate.py``.
 */
const MAX_AUTO_CLOSE_TIME_SECONDS = 3600;

/** Kettle mode options, in the order the form renders them. */
const KETTLE_MODE_KEYS = ["off_mode", "boil_mode", "heat_mode"];

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
      _gateStatus: { type: String },
      _gateError: { type: String },
      _kettleStatus: { type: String },
      _kettleError: { type: String },
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
        /* Wide enough for a translated label: Russian runs ~1.5x longer
         * than English and 80px turned "Leaf travel time (seconds)" into
         * a four-line column. */
        grid-template-columns: minmax(80px, 140px) 1fr;
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

      .field-hint {
        margin-top: 4px;
        font-size: 12px;
        line-height: 1.4;
        color: var(--secondary-text-color);
      }
      .warning-banner {
        margin-bottom: 8px;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 13px;
        line-height: 1.4;
        color: var(--primary-text-color);
        background: var(--warning-color, #ff9800);
      }

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
    this._gateStatus = "";
    this._gateError = "";
    this._kettleStatus = "";
    this._kettleError = "";
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
    /* The dialog can be the first thing rendered after a reload (deep link
     * into the device table), so it cannot rely on the panel root having
     * already fetched the `config_panel` strings — see ../localize.js. */
    ensurePanelTranslations(this.hass, this);
    this._returnFocusTo = deepActiveElement();
    this.open = true;
    this._loading = true;
    this._error = "";
    this._saveStatus = "";
    this._saveError = "";
    this._gateStatus = "";
    this._gateError = "";
    this._kettleStatus = "";
    this._kettleError = "";
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
          ? html`<div class="loading">${t(this.hass, "detail_dialog.loading")}</div>`
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
        <button class="close-btn" aria-label=${t(this.hass, "detail_dialog.close")} @click=${() => this.hide()}>\u2715</button>
      </div>
      <div class="body">
        ${this._renderEditForm(d)}
        ${d.gate_options ? this._renderGateOptions(d) : ""}
        ${d.kettle_options ? this._renderKettleOptions(d) : ""}
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
        <div class="section-title">${t(this.hass, "detail_dialog.overview")}</div>
        <div class="grid">
          <span class="label">${t(this.hass, "detail_dialog.entity_id")}</span>
          <span class="value"><code>${d.entity_id}</code></span>
          <span class="label">${t(this.hass, "detail_dialog.category")}</span>
          <span class="value"><code>${d.sber_category}</code></span>
          <span class="label">HA State</span>
          <span class="value">${d.ha_state ?? "\u2014"}</span>
          <span class="label">${t(this.hass, "detail_dialog.status")}</span>
          <span class="value"><span class="badge ${statusClass}">${statusText}</span></span>
          <span class="label">Room</span>
          <span class="value">${d.room || "\u2014"}</span>
          <span class="label">${t(this.hass, "detail_dialog.features")}</span>
          <span class="value">${(d.features || []).map((f) => html`<span class="feature-tag">${f}</span>`)}</span>
        </div>
      </div>
    `;
  }

  _renderSberStates(d) {
    const states = d.sber_states || [];
    if (!states.length) return html`<div class="section"><div class="section-title">${t(this.hass, "detail_dialog.sber_states")}</div><span style="color:var(--secondary-text-color);font-size:13px">${t(this.hass, "detail_dialog.no_states")}</span></div>`;
    return html`
      <div class="section">
        <div class="section-title">${t(this.hass, "detail_dialog.sber_states")}</div>
        <table class="state-table">
          <tr><th>${t(this.hass, "detail_dialog.col_key")}</th><th>${t(this.hass, "detail_dialog.col_type")}</th><th>${t(this.hass, "detail_dialog.col_value")}</th></tr>
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
        <div class="section-title">${t(this.hass, "detail_dialog.linked_entities")}</div>
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
        <div class="section-title">${t(this.hass, "detail_dialog.model_config")}</div>
        <div class="grid">
          <span class="label">${t(this.hass, "detail_dialog.model_id")}</span>
          <span class="value"><code>${model.id || "\u2014"}</code></span>
          <span class="label">${t(this.hass, "detail_dialog.manufacturer")}</span>
          <span class="value">${model.manufacturer || "\u2014"}</span>
          <span class="label">${t(this.hass, "detail_dialog.model")}</span>
          <span class="value">${model.model || "\u2014"}</span>
        </div>
        ${Object.keys(av).length ? html`
          <div style="margin-top:8px">
            <div class="section-title" style="margin-bottom:4px">${t(this.hass, "detail_dialog.allowed_values")}</div>
            <sber-json-block .hass=${this.hass} label="Allowed Values" .value=${av}></sber-json-block>
          </div>
        ` : ""}
        ${Object.keys(deps).length ? html`
          <div style="margin-top:8px">
            <div class="section-title" style="margin-bottom:4px">${t(this.hass, "detail_dialog.dependencies")}</div>
            <sber-json-block .hass=${this.hass} label="Dependencies" .value=${deps}></sber-json-block>
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
        <div class="section-title">${t(this.hass, "detail_dialog.ha_attributes")}</div>
        <table class="state-table">
          <tr><th>${t(this.hass, "detail_dialog.col_attribute")}</th><th>${t(this.hass, "detail_dialog.col_value")}</th></tr>
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
        <div class="section-title">${t(this.hass, "detail_dialog.device_registry")}</div>
        <div class="grid">
          <span class="label">${t(this.hass, "detail_dialog.device_name")}</span>
          <span class="value">${di.name || "\u2014"}</span>
          <span class="label">${t(this.hass, "detail_dialog.manufacturer")}</span>
          <span class="value">${di.manufacturer || "\u2014"}</span>
          <span class="label">${t(this.hass, "detail_dialog.model")}</span>
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
        <div class="section-title">${t(this.hass, "detail_dialog.override")}</div>
        <div class="edit-form">
          <label class="edit-label" for="edit-name">${t(this.hass, "detail_dialog.edit_name")}</label>
          <input class="edit-input" type="text" id="edit-name"
            .value=${r.name || d.name || ""}
            placeholder=${d.name || d.entity_id} />
          <label class="edit-label" for="edit-room">${t(this.hass, "detail_dialog.edit_room")}</label>
          <input class="edit-input" type="text" id="edit-room"
            .value=${r.room || d.room || ""}
            placeholder=${d.room || t(this.hass, "detail_dialog.room_placeholder")} />
          <label class="edit-label" for="edit-home">${t(this.hass, "detail_dialog.edit_home")}</label>
          <input class="edit-input" type="text" id="edit-home"
            .value=${r.home || ""}
            placeholder=${t(this.hass, "detail_dialog.home_placeholder")} />
          <div class="edit-actions">
            <button class="edit-save" @click=${this._onSave}>
              \u{1F4BE} ${t(this.hass, "detail_dialog.save_republish")}
            </button>
            ${this._saveStatus ? html`<span class="save-status ${this._saveStatus}" title=${this._saveError || ""}>${this._saveStatus === "ok" ? `\u2713 ${t(this.hass, "detail_dialog.saved")}` : `\u2717 ${this._saveError || t(this.hass, "detail_dialog.error")}`}</span>` : ""}
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Render the impulse-gate settings (issue #53).
   *
   * Only shown when the backend reports ``gate_options``, i.e. for a
   * gate built from an impulse relay + a contact sensor.  A cover-based
   * gate has no such options and renders nothing.
   *
   * All labels come from the ``config_panel.gate_options`` translation
   * block (see ``../localize.js``); nothing here is hardcoded English.
   *
   * @param {object} d - Detail payload.
   * @returns {import("lit").TemplateResult} Section template.
   */
  _renderGateOptions(d) {
    const g = d.gate_options || {};
    /* The travel-time control is rendered only when the backend actually
     * reports the option.  Showing it against an older backend would send
     * a 0 on the next save and silently wipe whatever was configured. */
    const hasTravelTime = g.travel_time !== undefined && g.travel_time !== null;
    const hasAutoClose = g.auto_close_time !== undefined && g.auto_close_time !== null;
    const missingLinks = d.missing_required_links || [];
    return html`
      <div class="section">
        <div class="section-title">${t(this.hass, "gate_options.title")}</div>
        ${missingLinks.length
          ? html`<div class="warning-banner" role="alert">
              ⚠ ${t(this.hass, "gate_options.missing_required_link_warning")}
            </div>`
          : ""}
        <div class="edit-form">
          <label class="edit-label" for="gate-invert">${t(this.hass, "gate_options.invert_contact")}</label>
          <label>
            <input type="checkbox" id="gate-invert" .checked=${!!g.invert_contact} />
            ${t(this.hass, "gate_options.invert_contact_description")}
          </label>
          <label class="edit-label" for="gate-service">${t(this.hass, "gate_options.impulse_service")}</label>
          <select class="edit-input" id="gate-service" .value=${g.impulse_service || "auto"}>
            <option value="auto">${t(this.hass, "gate_options.impulse_service_auto")}</option>
            <option value="toggle">${t(this.hass, "gate_options.impulse_service_toggle")}</option>
            <option value="turn_on">${t(this.hass, "gate_options.impulse_service_turn_on")}</option>
          </select>
          ${hasTravelTime
            ? html`
                <label class="edit-label" for="gate-travel">${t(this.hass, "gate_options.travel_time")}</label>
                <div>
                  <input class="edit-input" type="number" id="gate-travel"
                    min="0" max=${MAX_TRAVEL_TIME_SECONDS} step="0.5"
                    .value=${String(g.travel_time)} />
                  <div class="field-hint">${t(this.hass, "gate_options.travel_time_description")}</div>
                </div>
              `
            : ""}
          ${hasAutoClose
            ? html`
                <label class="edit-label" for="gate-auto-close">${t(this.hass, "gate_options.auto_close_time")}</label>
                <div>
                  <input class="edit-input" type="number" id="gate-auto-close"
                    min="0" max=${MAX_AUTO_CLOSE_TIME_SECONDS} step="1"
                    .value=${String(g.auto_close_time)} />
                  <div class="field-hint">${t(this.hass, "gate_options.auto_close_time_description")}</div>
                </div>
              `
            : ""}
          <div class="edit-actions">
            <button class="edit-save" @click=${this._onSaveGateOptions}>
              \u{1F6AA} ${t(this.hass, "gate_options.save")}
            </button>
            ${g.contact_stale
              ? html`<span class="save-status error">⚠ ${t(this.hass, "gate_options.contact_stale")}</span>`
              : ""}
            ${this._gateStatus
              ? html`<span class="save-status ${this._gateStatus}" title=${this._gateError || ""}>${this._gateStatus === "ok" ? `✓ ${t(this.hass, "detail_dialog.saved")}` : `✗ ${this._gateError || t(this.hass, "detail_dialog.error")}`}</span>`
              : ""}
          </div>
        </div>
      </div>
    `;
  }

  /**
   * Render the kettle operation-mode settings.
   *
   * Only shown when the backend reports ``kettle_options``.  The three
   * dropdowns are filled from the entity's own ``operation_list`` — a
   * free-text field here would let the user save a mode the kettle does
   * not have, which the backend then refuses.  A kettle that reports no
   * modes at all (a plain switch, or a ``water_heater`` without an
   * ``operation_list``) gets an explanatory note instead of dead
   * controls: it is driven by ``turn_on`` / ``turn_off``.
   *
   * @param {object} d - Detail payload.
   * @returns {import("lit").TemplateResult} Section template.
   */
  _renderKettleOptions(d) {
    const k = d.kettle_options || {};
    const modes = k.operation_list || [];
    /* Literal keys, not `kettle_options.${key}`: the translation
     * consistency test finds `t()` calls by source text, and a computed
     * key would silently escape it. */
    const labels = {
      off_mode: t(this.hass, "kettle_options.off_mode"),
      boil_mode: t(this.hass, "kettle_options.boil_mode"),
      heat_mode: t(this.hass, "kettle_options.heat_mode"),
    };
    return html`
      <div class="section">
        <div class="section-title">${t(this.hass, "kettle_options.title")}</div>
        ${modes.length
          ? html`
              <div class="edit-form">
                ${KETTLE_MODE_KEYS.map((key) => {
                  const chosen = k[key] || "";
                  const resolved = k[`resolved_${key}`] || "";
                  return html`
                    <label class="edit-label" for="kettle-${key}">${labels[key]}</label>
                    <div>
                      <select class="edit-input" id="kettle-${key}">
                        <option value="" ?selected=${!chosen}>${t(this.hass, "kettle_options.mode_auto")}</option>
                        ${modes.map(
                          (mode) => html`<option value=${mode} ?selected=${chosen === mode}>${mode}</option>`
                        )}
                      </select>
                      <div class="field-hint">
                        ${resolved
                          ? t(this.hass, "kettle_options.resolved", { mode: resolved })
                          : t(this.hass, "kettle_options.unresolved")}
                      </div>
                    </div>
                  `;
                })}
                <div class="edit-actions">
                  <button class="edit-save" @click=${this._onSaveKettleOptions}>
                    \u{2615} ${t(this.hass, "kettle_options.save")}
                  </button>
                  ${this._kettleStatus
                    ? html`<span class="save-status ${this._kettleStatus}" title=${this._kettleError || ""}>${this._kettleStatus === "ok" ? `✓ ${t(this.hass, "detail_dialog.saved")}` : `✗ ${this._kettleError || t(this.hass, "detail_dialog.error")}`}</span>`
                    : ""}
                </div>
              </div>
            `
          : html`<div class="field-hint">${t(this.hass, "kettle_options.no_modes")}</div>`}
      </div>
    `;
  }

  async _onSaveKettleOptions() {
    if (!this.hass || !this._data) return;
    const options = {};
    for (const key of KETTLE_MODE_KEYS) {
      const field = this.shadowRoot.getElementById(`kettle-${key}`);
      /* An empty selection is meaningful here (unlike the gate timers):
       * it restores auto-detection, so it is submitted as "". */
      if (field) options[key] = field.value;
    }
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/update_entity_options",
        entity_id: this._data.entity_id,
        options,
      });
      this._kettleStatus = "ok";
      this._kettleError = "";
      await this._fetchDetail(this._data.entity_id);
    } catch (e) {
      this._kettleStatus = "error";
      this._kettleError = e.message || String(e);
    }
    this.requestUpdate();
  }

  async _onSaveGateOptions() {
    if (!this.hass || !this._data) return;
    const invert = !!this.shadowRoot.getElementById("gate-invert")?.checked;
    const service = this.shadowRoot.getElementById("gate-service")?.value || "auto";
    const payload = {
      type: "sber_mqtt_bridge/update_gate_options",
      entity_id: this._data.entity_id,
      invert_contact: invert,
      impulse_service: service,
    };
    /* Only present when the control was rendered — see `_renderGateOptions`.
     * An empty field is left out rather than coerced: `Number("")` is 0,
     * which the backend reads as "travel-time emulation off" — a cleared
     * box would silently disable the feature instead of doing nothing. */
    const travelField = this.shadowRoot.getElementById("gate-travel");
    if (travelField && travelField.value !== "") {
      const travel = Number(travelField.value);
      if (Number.isFinite(travel) && travel >= 0 && travel <= MAX_TRAVEL_TIME_SECONDS) {
        payload.travel_time = travel;
      }
    }
    /* Same rule for the auto-close delay: an empty box means "leave it
     * alone", not "turn the timer off". */
    const autoCloseField = this.shadowRoot.getElementById("gate-auto-close");
    if (autoCloseField && autoCloseField.value !== "") {
      const autoClose = Number(autoCloseField.value);
      if (Number.isFinite(autoClose) && autoClose >= 0 && autoClose <= MAX_AUTO_CLOSE_TIME_SECONDS) {
        payload.auto_close_time = autoClose;
      }
    }
    try {
      await this.hass.callWS(payload);
      this._gateStatus = "ok";
      this._gateError = "";
    } catch (e) {
      this._gateStatus = "error";
      this._gateError = e.message || String(e);
    }
    this.requestUpdate();
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
