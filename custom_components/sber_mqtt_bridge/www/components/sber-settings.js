/**
 * Sber MQTT Bridge — Settings component for bridge operational parameters.
 *
 * Grouped into three sections: Connection, Performance, Debug.
 * Changes are saved to config_entry.options and applied to the running bridge.
 */

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html;
const css = LitElement?.prototype.css;

/** Setting definitions with metadata for rendering. */
const SETTING_DEFS = [
  {
    group: "Connection",
    note: "Changes take effect on next reconnect",
    fields: [
      { key: "reconnect_interval_min", label: "Min reconnect interval (s)", min: 1, max: 60, step: 1, type: "number" },
      { key: "reconnect_interval_max", label: "Max reconnect interval (s)", min: 30, max: 3600, step: 10, type: "number" },
      { key: "sber_verify_ssl", label: "Verify SSL certificate", type: "toggle" },
    ],
  },
  {
    group: "Performance",
    note: "Applied immediately",
    fields: [
      { key: "debounce_delay", label: "State publish debounce (s)", min: 0.05, max: 5.0, step: 0.05, type: "number" },
      { key: "max_mqtt_payload_size", label: "Max MQTT payload (bytes)", min: 100000, max: 10000000, step: 100000, type: "number" },
    ],
  },
  {
    group: "Debug",
    note: "Applied immediately",
    fields: [
      { key: "message_log_size", label: "MQTT message log buffer", min: 10, max: 500, step: 10, type: "number" },
    ],
  },
];

class SberSettings extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      _settings: { type: Object },
      _defaults: { type: Object },
      _hub: { type: Object },
      _loading: { type: Boolean },
      _saving: { type: Boolean },
      _dirty: { type: Boolean },
      _hassReady: { type: Boolean },
    };
  }

  constructor() {
    super();
    this._settings = {};
    this._defaults = {};
    this._hub = null;
    this._loading = false;
    this._saving = false;
    this._dirty = false;
    this._hassReady = false;
  }

  updated(changed) {
    if (changed.has("hass") && this.hass && !this._hassReady) {
      this._hassReady = true;
      this._loadSettings();
    }
  }

  async _loadSettings() {
    this._loading = true;
    try {
      const [settingsRes, statusRes] = await Promise.all([
        this.hass.callWS({ type: "sber_mqtt_bridge/get_settings" }),
        this.hass.callWS({ type: "sber_mqtt_bridge/status" }),
      ]);
      this._settings = { ...settingsRes.settings };
      this._defaults = settingsRes.defaults;
      this._hub = statusRes.hub || null;
      this._dirty = false;
    } catch (e) {
      this._toast("Failed to load settings: " + (e.message || e), "error");
    } finally {
      this._loading = false;
    }
  }

  async _saveSettings() {
    this._saving = true;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/update_settings",
        settings: this._settings,
      });
      this._dirty = false;
      this._toast("Settings saved", "success");
    } catch (e) {
      this._toast("Save failed: " + (e.message || e), "error");
    } finally {
      this._saving = false;
    }
  }

  _resetDefaults() {
    this._settings = { ...this._defaults };
    this._dirty = true;
  }

  _onInput(key, value) {
    this._settings = { ...this._settings, [key]: value };
    this._dirty = true;
  }

  _toast(message, type = "info") {
    this.dispatchEvent(new CustomEvent("settings-toast", { detail: { message, type }, bubbles: true, composed: true }));
  }

  static get styles() {
    return css`
      :host { display: block; }
      .card {
        background: var(--ha-card-background, var(--card-background-color, #fff));
        border-radius: 12px;
        padding: 20px 24px;
        margin-bottom: 16px;
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,.1));
      }
      .card h3 {
        margin: 0 0 4px 0;
        font-size: 16px;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .note {
        font-size: 12px;
        color: var(--secondary-text-color);
        margin-bottom: 16px;
        font-style: italic;
      }
      .field {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 0;
        border-bottom: 1px solid var(--divider-color, #e0e0e0);
      }
      .field:last-child { border-bottom: none; }
      .field label {
        font-size: 14px;
        color: var(--primary-text-color);
        flex: 1;
      }
      .field input[type="number"] {
        width: 120px;
        padding: 6px 10px;
        border: 1px solid var(--divider-color, #ccc);
        border-radius: 6px;
        font-size: 14px;
        background: var(--card-background-color, #fff);
        color: var(--primary-text-color);
        text-align: right;
      }
      .field input[type="number"]:focus {
        outline: none;
        border-color: var(--primary-color, #03a9f4);
      }
      .toggle {
        position: relative;
        width: 44px;
        min-width: 44px;
        height: 24px;
        flex-shrink: 0;
      }
      .toggle input {
        opacity: 0;
        width: 0;
        height: 0;
      }
      .toggle .slider {
        position: absolute;
        cursor: pointer;
        top: 0; left: 0; right: 0; bottom: 0;
        background: var(--divider-color, #ccc);
        border-radius: 24px;
        transition: 0.2s;
      }
      .toggle .slider::before {
        content: "";
        position: absolute;
        height: 18px;
        width: 18px;
        left: 3px;
        bottom: 3px;
        background: white;
        border-radius: 50%;
        transition: 0.2s;
      }
      .toggle input:checked + .slider {
        background: var(--primary-color, #03a9f4);
      }
      .toggle input:checked + .slider::before {
        transform: translateX(20px);
      }
      .actions {
        display: flex;
        gap: 12px;
        margin-top: 20px;
        justify-content: flex-end;
      }
      button {
        padding: 8px 20px;
        border: none;
        border-radius: 8px;
        font-size: 14px;
        cursor: pointer;
        font-weight: 500;
        transition: opacity 0.15s;
      }
      button:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .btn-primary {
        background: var(--primary-color, #03a9f4);
        color: #fff;
      }
      .btn-secondary {
        background: var(--secondary-background-color, #f5f5f5);
        color: var(--primary-text-color);
      }
      .ro-value {
        font-size: 14px;
        color: var(--secondary-text-color);
        font-weight: 500;
        text-align: right;
        white-space: nowrap;
      }
      .loading {
        text-align: center;
        padding: 40px;
        color: var(--secondary-text-color);
      }
    `;
  }

  render() {
    if (this._loading) {
      return html`<div class="loading">Loading settings...</div>`;
    }

    return html`
      ${this._hub ? html`
        <div class="card">
          <h3>Hub Device</h3>
          <div class="note">Root device for Sber hierarchy (read-only, from HA config)</div>
          <div class="field">
            <label>Name</label>
            <span class="ro-value">${this._hub.name}</span>
          </div>
          <div class="field">
            <label>Home</label>
            <span class="ro-value">${this._hub.home || "—"}</span>
          </div>
          <div class="field">
            <label>Room</label>
            <span class="ro-value">${this._hub.room || "—"}</span>
          </div>
          <div class="field">
            <label>Version</label>
            <span class="ro-value">${this._hub.version}</span>
          </div>
          <div class="field">
            <label>Online</label>
            <span class="ro-value" style="color: ${this._hub.is_online ? "var(--success-color, #4caf50)" : "var(--error-color, #f44336)"}">
              ${this._hub.is_online ? "Yes" : "No"}
            </span>
          </div>
          <div class="field">
            <label>Children</label>
            <span class="ro-value">${this._hub.children_count} devices</span>
          </div>
          <div class="field">
            <label>Auto-assign parent_id</label>
            <label class="toggle">
              <input type="checkbox" .checked=${!!this._settings.hub_auto_parent_id}
                @change=${(e) => this._onInput("hub_auto_parent_id", e.target.checked)}>
              <span class="slider"></span>
            </label>
          </div>
        </div>
      ` : ""}

      ${SETTING_DEFS.map(group => html`
        <div class="card">
          <h3>${group.group}</h3>
          <div class="note">${group.note}</div>
          ${group.fields.map(f => this._renderField(f))}
        </div>
      `)}

      <div class="actions">
        <button class="btn-secondary" @click=${this._resetDefaults} ?disabled=${this._saving}>
          Reset to Defaults
        </button>
        <button class="btn-secondary" @click=${this._loadSettings} ?disabled=${this._saving}>
          Reload
        </button>
        <button class="btn-primary" @click=${this._saveSettings} ?disabled=${!this._dirty || this._saving}>
          ${this._saving ? "Saving..." : "Save"}
        </button>
      </div>
    `;
  }

  _renderField(f) {
    const value = this._settings[f.key];
    if (f.type === "toggle") {
      return html`
        <div class="field">
          <label>${f.label}</label>
          <label class="toggle">
            <input type="checkbox" .checked=${!!value}
              @change=${(e) => this._onInput(f.key, e.target.checked)}>
            <span class="slider"></span>
          </label>
        </div>
      `;
    }
    return html`
      <div class="field">
        <label>${f.label}</label>
        <input type="number"
          .value=${value ?? ""}
          min=${f.min} max=${f.max} step=${f.step}
          @input=${(e) => this._onInput(f.key, Number(e.target.value))}>
      </div>
    `;
  }
}

customElements.define("sber-settings", SberSettings);
