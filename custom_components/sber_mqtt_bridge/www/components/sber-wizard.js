/**
 * Sber MQTT Bridge -- Add Device Wizard (3-step).
 *
 * Step 1: Choose Sber device type (card grid with icons).
 * Step 2: Pick HA entity + auto-discover related sensors.
 * Step 3: Set name (Salut-validated), auto-slugified ID, optional room.
 *
 * Fires "wizard-complete" with full payload for the parent panel.
 */

import { slugify, isValidSalutName } from "../utils.js";

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

/* ---------- device type catalogue ---------- */

const DEVICE_GROUPS = [
  {
    label: "Control",
    types: [
      { id: "relay", icon: "\uD83D\uDD0C", label: "Relay", domains: ["switch", "script", "button"] },
      { id: "socket", icon: "\uD83D\uDD0B", label: "Socket", domains: ["switch"] },
      { id: "light", icon: "\uD83D\uDCA1", label: "Light", domains: ["light"] },
      { id: "hvac_ac", icon: "\u2744\uFE0F", label: "Air conditioner", domains: ["climate"] },
      { id: "hvac_humidifier", icon: "\uD83D\uDCA7", label: "Humidifier", domains: ["humidifier"] },
      { id: "kettle", icon: "\u2615", label: "Kettle", domains: ["water_heater", "switch"] },
      { id: "vacuum_cleaner", icon: "\uD83E\uDD16", label: "Vacuum", domains: ["vacuum"] },
      { id: "valve", icon: "\uD83D\uDEB0", label: "Valve", domains: ["valve"] },
      { id: "curtain", icon: "\uD83D\uDFE8", label: "Curtain", domains: ["cover"] },
      { id: "hvac_fan", icon: "\uD83C\uDF00", label: "Fan", domains: ["fan"] },
      { id: "hvac_radiator", icon: "\uD83D\uDD25", label: "Radiator", domains: ["climate"] },
      { id: "tv", icon: "\uD83D\uDCFA", label: "TV", domains: ["media_player"] },
    ],
  },
  {
    label: "Sensors",
    types: [
      { id: "sensor_temp", icon: "\uD83C\uDF21\uFE0F", label: "Temperature / Humidity", domains: ["sensor"] },
      { id: "sensor_water_leak", icon: "\uD83C\uDF0A", label: "Water leak", domains: ["binary_sensor"] },
      { id: "sensor_smoke", icon: "\uD83D\uDD25", label: "Smoke", domains: ["binary_sensor"] },
      { id: "sensor_gas", icon: "\u26A0\uFE0F", label: "Gas", domains: ["binary_sensor"] },
      { id: "sensor_pir", icon: "\uD83D\uDC64", label: "Motion", domains: ["binary_sensor"] },
      { id: "sensor_door", icon: "\uD83D\uDEAA", label: "Door / Window", domains: ["binary_sensor"] },
    ],
  },
  {
    label: "Automations",
    types: [
      { id: "scenario_button", icon: "\uD83D\uDD14", label: "Scenario button", domains: ["input_boolean"] },
    ],
  },
];

/* Flat index for lookup */
const TYPE_BY_ID = {};
for (const g of DEVICE_GROUPS) {
  for (const t of g.types) {
    TYPE_BY_ID[t.id] = t;
  }
}

class SberWizard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      open: { type: Boolean, reflect: true },
      _step: { type: Number },
      _selectedType: { type: String },
      _entities: { type: Array },
      _entityFilter: { type: String },
      _selectedEntity: { type: String },
      _relatedSensors: { type: Array },
      _enabledSensors: { type: Object },
      _name: { type: String },
      _slugId: { type: String },
      _room: { type: String },
      _loading: { type: Boolean },
    };
  }

  constructor() {
    super();
    this.open = false;
    this._reset();
  }

  _reset() {
    this._step = 1;
    this._selectedType = "";
    this._entities = [];
    this._entityFilter = "";
    this._selectedEntity = "";
    this._relatedSensors = [];
    this._enabledSensors = new Set();
    this._name = "";
    this._slugId = "";
    this._room = "";
    this._loading = false;
  }

  show() {
    this._reset();
    this.open = true;
  }

  hide() {
    this.open = false;
  }

  /* ---------- data helpers ---------- */

  async _loadEntities() {
    if (!this.hass) return;
    this._loading = true;
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/available_entities",
      });
      const typeDef = TYPE_BY_ID[this._selectedType];
      const domains = typeDef ? new Set(typeDef.domains) : new Set();
      this._entities = (result.entities || []).filter(
        (e) => domains.has(e.domain)
      );
    } catch {
      this._entities = [];
    } finally {
      this._loading = false;
    }
  }

  async _loadRelatedSensors(entityId) {
    if (!this.hass) return;
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/related_sensors",
        entity_id: entityId,
      });
      this._relatedSensors = result.sensors || [];
      this._enabledSensors = new Set(
        this._relatedSensors.map((s) => s.entity_id)
      );
    } catch {
      this._relatedSensors = [];
      this._enabledSensors = new Set();
    }
  }

  /* ---------- navigation ---------- */

  async _goNext() {
    if (this._step === 1 && this._selectedType) {
      this._step = 2;
      await this._loadEntities();
    } else if (this._step === 2 && this._selectedEntity) {
      this._step = 3;
      /* Pre-fill name from friendly_name */
      const ent = this._entities.find(
        (e) => e.entity_id === this._selectedEntity
      );
      if (ent?.friendly_name) {
        this._name = ent.friendly_name;
        this._slugId = slugify(ent.friendly_name);
      }
    }
  }

  _goBack() {
    if (this._step > 1) this._step -= 1;
  }

  _finish() {
    if (!isValidSalutName(this._name)) return;
    const sensors = {};
    for (const s of this._relatedSensors) {
      if (this._enabledSensors.has(s.entity_id)) {
        const dc = s.device_class || "";
        if (dc === "power") sensors.power_entity = s.entity_id;
        else if (dc === "current") sensors.current_entity = s.entity_id;
        else if (dc === "voltage") sensors.voltage_entity = s.entity_id;
        else if (dc === "battery") sensors.battery_entity = s.entity_id;
        else if (dc === "temperature") sensors.temperature_entity = s.entity_id;
      }
    }
    this.dispatchEvent(
      new CustomEvent("wizard-complete", {
        detail: {
          entity_id: this._selectedEntity,
          category: this._selectedType,
          name: this._name,
          slug_id: this._slugId,
          room: this._room,
          sensors,
        },
        bubbles: true,
        composed: true,
      })
    );
    this.hide();
  }

  /* ---------- field handlers ---------- */

  _onNameInput(e) {
    this._name = e.target.value;
    this._slugId = slugify(this._name);
  }

  _toggleSensor(entityId) {
    const s = new Set(this._enabledSensors);
    if (s.has(entityId)) s.delete(entityId);
    else s.add(entityId);
    this._enabledSensors = s;
    this.requestUpdate();
  }

  async _selectEntity(entityId) {
    this._selectedEntity = entityId;
    await this._loadRelatedSensors(entityId);
  }

  /* ---------- styles ---------- */

  static get styles() {
    return css`
      :host { display: none; }
      :host([open]) { display: block; }

      .overlay {
        position: fixed; top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.5); z-index: 999;
        display: flex; align-items: center; justify-content: center;
      }
      .dialog {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: 0 8px 32px rgba(0,0,0,0.25);
        width: 92%; max-width: 780px; max-height: 85vh;
        display: flex; flex-direction: column; overflow: hidden;
      }

      /* Header */
      .dialog-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 16px 20px; border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .dialog-header h2 { margin: 0; font-size: 18px; font-weight: 500; }
      .close-btn {
        background: none; border: none; font-size: 20px; cursor: pointer;
        color: var(--secondary-text-color); padding: 4px 8px; border-radius: 4px;
      }
      .close-btn:hover { background: var(--secondary-background-color, #eee); }

      /* Stepper */
      .stepper {
        display: flex; align-items: center; justify-content: center;
        gap: 0; padding: 16px 20px;
      }
      .step-dot {
        width: 32px; height: 32px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 13px; font-weight: 600;
        border: 2px solid var(--divider-color, #ccc);
        color: var(--secondary-text-color);
        background: transparent;
        transition: all 0.2s;
      }
      .step-dot.active {
        border-color: var(--primary-color);
        color: var(--primary-color);
        background: var(--primary-color);
        color: #fff;
      }
      .step-dot.done {
        border-color: var(--success-color, #4caf50);
        background: var(--success-color, #4caf50);
        color: #fff;
      }
      .step-line {
        width: 48px; height: 2px;
        background: var(--divider-color, #ccc);
        margin: 0 4px;
      }
      .step-line.done { background: var(--success-color, #4caf50); }

      /* Body */
      .body { flex: 1; overflow-y: auto; padding: 16px 20px; }

      /* Step 1: type cards */
      .group-label {
        font-size: 13px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.5px; color: var(--secondary-text-color);
        margin: 12px 0 8px;
      }
      .type-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
        gap: 8px;
      }
      .type-card {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        padding: 12px 8px; border-radius: 8px; cursor: pointer;
        border: 2px solid var(--divider-color, #e0e0e0);
        transition: border-color 0.15s, background 0.15s;
        text-align: center;
        user-select: none;
      }
      .type-card:hover { border-color: var(--primary-color); }
      .type-card.selected {
        border-color: var(--primary-color);
        background: color-mix(in srgb, var(--primary-color) 10%, transparent);
      }
      .type-icon { font-size: 28px; margin-bottom: 4px; }
      .type-label { font-size: 12px; color: var(--primary-text-color); }

      /* Step 2: entity list */
      .filter-input {
        width: 100%; padding: 8px 12px; margin-bottom: 12px;
        border: 1px solid var(--divider-color, #ccc); border-radius: 8px;
        font-size: 13px; background: var(--card-background-color, #fff);
        color: var(--primary-text-color); outline: none; box-sizing: border-box;
      }
      .filter-input:focus { border-color: var(--primary-color); }

      .entity-list { max-height: 260px; overflow-y: auto; }
      .entity-item {
        display: flex; align-items: center; gap: 10px;
        padding: 8px 12px; border-bottom: 1px solid var(--divider-color, #f0f0f0);
        cursor: pointer; font-size: 13px;
      }
      .entity-item:hover { background: var(--secondary-background-color, #f9f9f9); }
      .entity-item.selected { background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
      .entity-item.already-added { opacity: 0.5; }
      .entity-info { flex: 1; min-width: 0; }
      .entity-id { font-family: monospace; font-size: 12px; color: var(--secondary-text-color); }
      .entity-name { font-size: 13px; color: var(--primary-text-color); }

      .sensors-section { margin-top: 16px; }
      .sensors-title { font-size: 13px; font-weight: 600; color: var(--secondary-text-color); margin-bottom: 8px; }
      .sensor-row {
        display: flex; align-items: center; gap: 8px;
        padding: 6px 0; font-size: 13px;
      }
      .sensor-row input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
      .sensor-class {
        display: inline-block; padding: 1px 6px; border-radius: 4px;
        font-size: 11px; background: var(--secondary-background-color, #eee);
        color: var(--secondary-text-color);
      }

      /* Step 3: parameters */
      .field { margin-bottom: 16px; }
      .field label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 4px; color: var(--primary-text-color); }
      .field input {
        width: 100%; padding: 8px 12px; border: 1px solid var(--divider-color, #ccc);
        border-radius: 8px; font-size: 13px; background: var(--card-background-color, #fff);
        color: var(--primary-text-color); outline: none; box-sizing: border-box;
      }
      .field input:focus { border-color: var(--primary-color); }
      .field input.invalid { border-color: var(--error-color, #f44336); }
      .field .hint { font-size: 11px; color: var(--secondary-text-color); margin-top: 2px; }
      .field .error-hint { font-size: 11px; color: var(--error-color, #f44336); margin-top: 2px; }

      /* Footer */
      .dialog-footer {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 20px; border-top: 1px solid var(--divider-color, #e0e0e0);
      }
      .btn {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 8px 16px; border: none; border-radius: 8px;
        font-size: 13px; font-weight: 500; cursor: pointer; transition: background 0.15s;
      }
      .btn-primary { background: var(--primary-color); color: #fff; }
      .btn-primary:hover { opacity: 0.85; }
      .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
      .btn-secondary { background: var(--secondary-background-color, #eee); color: var(--primary-text-color); }
      .btn-secondary:hover { opacity: 0.8; }
      .btn-success { background: var(--success-color, #4caf50); color: #fff; }
      .btn-success:hover { opacity: 0.85; }

      .empty-state { text-align: center; padding: 32px; color: var(--secondary-text-color); font-size: 14px; }
    `;
  }

  /* ---------- render ---------- */

  render() {
    if (!this.open) return html``;

    return html`
      <div class="overlay" @click=${(e) => { if (e.target === e.currentTarget) this.hide(); }}>
        <div class="dialog">
          <div class="dialog-header">
            <h2>Add Device</h2>
            <button class="close-btn" @click=${this.hide}>\u2715</button>
          </div>

          ${this._renderStepper()}

          <div class="body">
            ${this._step === 1 ? this._renderStep1()
              : this._step === 2 ? this._renderStep2()
              : this._renderStep3()}
          </div>

          ${this._renderFooter()}
        </div>
      </div>
    `;
  }

  _renderStepper() {
    const steps = [1, 2, 3];
    return html`
      <div class="stepper">
        ${steps.map((n, i) => html`
          ${i > 0 ? html`<div class="step-line ${this._step > n - 1 ? "done" : ""}"></div>` : ""}
          <div class="step-dot ${this._step === n ? "active" : ""} ${this._step > n ? "done" : ""}">
            ${this._step > n ? "\u2713" : n}
          </div>
        `)}
      </div>
    `;
  }

  /* Step 1 */
  _renderStep1() {
    return html`
      ${DEVICE_GROUPS.map((g) => html`
        <div class="group-label">${g.label}</div>
        <div class="type-grid">
          ${g.types.map((t) => html`
            <div
              class="type-card ${this._selectedType === t.id ? "selected" : ""}"
              @click=${() => { this._selectedType = t.id; }}
            >
              <span class="type-icon">${t.icon}</span>
              <span class="type-label">${t.label}</span>
            </div>
          `)}
        </div>
      `)}
    `;
  }

  /* Step 2 */
  _renderStep2() {
    const q = this._entityFilter.toLowerCase();
    const filtered = q
      ? this._entities.filter(
          (e) =>
            e.entity_id.toLowerCase().includes(q) ||
            (e.friendly_name || "").toLowerCase().includes(q)
        )
      : this._entities;

    return html`
      <input
        class="filter-input"
        type="text"
        placeholder="Search entities..."
        .value=${this._entityFilter}
        @input=${(e) => { this._entityFilter = e.target.value; }}
      />

      ${this._loading
        ? html`<div class="empty-state">Loading...</div>`
        : filtered.length === 0
          ? html`<div class="empty-state">No matching entities found</div>`
          : html`
              <div class="entity-list">
                ${filtered.map((e) => html`
                  <div
                    class="entity-item ${this._selectedEntity === e.entity_id ? "selected" : ""}"
                    @click=${() => this._selectEntity(e.entity_id)}
                  >
                    <div class="entity-info">
                      <div class="entity-name">${e.friendly_name || e.entity_id}</div>
                      <div class="entity-id">${e.entity_id}</div>
                    </div>
                  </div>
                `)}
              </div>
            `}

      ${this._relatedSensors.length > 0 ? html`
        <div class="sensors-section">
          <div class="sensors-title">Related sensors (auto-detected)</div>
          ${this._relatedSensors.map((s) => html`
            <div class="sensor-row">
              <input
                type="checkbox"
                .checked=${this._enabledSensors.has(s.entity_id)}
                @change=${() => this._toggleSensor(s.entity_id)}
              />
              <span>${s.name}</span>
              <span class="sensor-class">${s.device_class || "unknown"}</span>
              <span class="entity-id">${s.entity_id}</span>
            </div>
          `)}
        </div>
      ` : ""}
    `;
  }

  /* Step 3 */
  _renderStep3() {
    const nameValid = this._name.length === 0 || isValidSalutName(this._name);

    return html`
      <div class="field">
        <label>Device name (for Salut voice)</label>
        <input
          type="text"
          class="${!nameValid ? "invalid" : ""}"
          placeholder="e.g. \u041B\u0430\u043C\u043F\u0430 \u043A\u0443\u0445\u043D\u044F"
          .value=${this._name}
          @input=${this._onNameInput}
        />
        ${!nameValid
          ? html`<div class="error-hint">3-33 chars, Cyrillic + digits + spaces only</div>`
          : html`<div class="hint">Will be spoken by Salut assistant</div>`}
      </div>

      <div class="field">
        <label>Device ID (auto-generated)</label>
        <input type="text" .value=${this._slugId} readonly />
        <div class="hint">Transliterated slug for the Sber protocol</div>
      </div>

      <div class="field">
        <label>Room (optional)</label>
        <input
          type="text"
          placeholder="e.g. \u041A\u0443\u0445\u043D\u044F"
          .value=${this._room}
          @input=${(e) => { this._room = e.target.value; }}
        />
      </div>
    `;
  }

  /* Footer */
  _renderFooter() {
    const canNext =
      (this._step === 1 && this._selectedType) ||
      (this._step === 2 && this._selectedEntity);
    const canFinish = this._step === 3 && isValidSalutName(this._name);

    return html`
      <div class="dialog-footer">
        <div>
          ${this._step > 1
            ? html`<button class="btn btn-secondary" @click=${this._goBack}>Back</button>`
            : html`<span></span>`}
        </div>
        <div>
          ${this._step < 3
            ? html`<button class="btn btn-primary" ?disabled=${!canNext} @click=${this._goNext}>
                Next
              </button>`
            : html`<button class="btn btn-success" ?disabled=${!canFinish} @click=${this._finish}>
                Done
              </button>`}
        </div>
      </div>
    `;
  }
}

customElements.define("sber-wizard", SberWizard);
