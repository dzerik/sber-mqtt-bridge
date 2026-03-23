/**
 * Sber MQTT Bridge — SPA Panel for Home Assistant sidebar.
 *
 * Main coordinator component: manages tabs, data fetching and delegates
 * rendering to child components in ./components/.
 *
 * Uses LitElement (bundled with HA) and HA WebSocket API.
 * No build step required.
 */

import "./components/sber-device-table.js";
import "./components/sber-status-card.js";
import "./components/sber-stats-grid.js";
import "./components/sber-add-dialog.js";
import "./components/sber-toolbar.js";
import "./components/sber-wizard.js";
import "./components/sber-toast.js";

const LitElement = Object.getPrototypeOf(
  customElements.get("ha-panel-lovelace") ?? customElements.get("hui-view")
);
const html = LitElement?.prototype.html ?? (await import("https://unpkg.com/lit@3/index.js?module")).html;
const css = LitElement?.prototype.css ?? (await import("https://unpkg.com/lit@3/index.js?module")).css;

/* ---------- main panel ---------- */

class SberMqttPanel extends LitElement {

  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      panel: { type: Object },
      _tab: { type: Number },
      _devices: { type: Array },
      _devicesExtra: { type: Object },
      _status: { type: Object },
      _loading: { type: Boolean },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this._tab = 0;
    this._devices = [];
    this._devicesExtra = {};
    this._status = null;
    this._loading = false;
    this._error = "";
    this._autoRefresh = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this._fetchAll();
    this._autoRefresh = setInterval(() => this._fetchAll(), 15000);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._autoRefresh) {
      clearInterval(this._autoRefresh);
      this._autoRefresh = null;
    }
  }

  /* ---------- data ---------- */

  async _fetchAll() {
    try {
      const [devResult, statusResult] = await Promise.all([
        this.hass.callWS({ type: "sber_mqtt_bridge/devices" }),
        this.hass.callWS({ type: "sber_mqtt_bridge/status" }),
      ]);
      this._devices = devResult.devices || [];
      this._devicesExtra = {
        total: devResult.total,
        acknowledged_count: devResult.acknowledged_count,
        unacknowledged_count: devResult.unacknowledged_count,
        unacknowledged: devResult.unacknowledged || [],
      };
      this._status = statusResult;
      this._error = "";
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  async _republish() {
    this._loading = true;
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/republish" });
      await this._fetchAll();
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  async _addEntities(entityIds) {
    this._loading = true;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/add_entities",
        entity_ids: entityIds,
      });
      // Wait a short moment for the reload to settle
      await new Promise((r) => setTimeout(r, 1500));
      await this._fetchAll();
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  async _removeEntities(entityIds) {
    this._loading = true;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/remove_entities",
        entity_ids: entityIds,
      });
      await new Promise((r) => setTimeout(r, 1500));
      await this._fetchAll();
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  async _setOverride(entityId, category) {
    this._loading = true;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/set_override",
        entity_id: entityId,
        category: category,
      });
      await new Promise((r) => setTimeout(r, 1500));
      await this._fetchAll();
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  async _bulkAddAll() {
    this._loading = true;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/bulk_add",
        domains: [],
      });
      await new Promise((r) => setTimeout(r, 1500));
      await this._fetchAll();
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  async _clearAll() {
    this._loading = true;
    try {
      await this.hass.callWS({ type: "sber_mqtt_bridge/clear_all" });
      await new Promise((r) => setTimeout(r, 1500));
      await this._fetchAll();
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  /* ---------- event handlers ---------- */

  _onToolbarRefresh() {
    this._fetchAll();
  }

  _onToolbarRepublish() {
    this._republish();
  }

  _onToolbarAdd() {
    const dialog = this.shadowRoot.querySelector("sber-add-dialog");
    if (dialog) dialog.show();
  }

  _onToolbarBulkAdd() {
    this._bulkAddAll();
  }

  _onToolbarClearAll() {
    this._clearAll();
  }

  _onAddEntities(e) {
    this._addEntities(e.detail.entityIds);
  }

  _onRemoveEntities(e) {
    this._removeEntities(e.detail.entityIds);
  }

  _onSetOverride(e) {
    this._setOverride(e.detail.entityId, e.detail.category);
  }

  _onToolbarWizard() {
    const wizard = this.shadowRoot.querySelector("sber-wizard");
    if (wizard) wizard.show();
  }

  async _onToolbarExport() {
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/export",
      });
      const blob = new Blob([JSON.stringify(result, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "sber_mqtt_bridge_config.json";
      a.click();
      URL.revokeObjectURL(url);
      this._showToast("Config exported", "success");
    } catch (e) {
      this._showToast("Export failed: " + (e.message || e), "error");
    }
  }

  async _onToolbarImport(e) {
    const config = e.detail.config;
    this._loading = true;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/import",
        config,
      });
      await new Promise((r) => setTimeout(r, 1500));
      await this._fetchAll();
      this._showToast("Config imported successfully", "success");
    } catch (e) {
      this._showToast("Import failed: " + (e.message || e), "error");
    } finally {
      this._loading = false;
    }
  }

  async _onSyncEntity(e) {
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/publish_one_status",
        entity_id: e.detail.entityId,
      });
      this._showToast("Synced: " + e.detail.entityId, "success");
    } catch (err) {
      this._showToast("Sync failed: " + (err.message || err), "error");
    }
  }

  async _onWizardComplete(e) {
    const d = e.detail;
    this._loading = true;
    try {
      /* Add the main entity */
      await this.hass.callWS({
        type: "sber_mqtt_bridge/add_entities",
        entity_ids: [d.entity_id],
      });
      /* Set category override */
      await this.hass.callWS({
        type: "sber_mqtt_bridge/set_override",
        entity_id: d.entity_id,
        category: d.category,
      });
      /* Re-publish config */
      await this.hass.callWS({ type: "sber_mqtt_bridge/republish" });
      await new Promise((r) => setTimeout(r, 1500));
      await this._fetchAll();
      this._showToast("Device added via wizard", "success");
    } catch (err) {
      this._showToast("Wizard failed: " + (err.message || err), "error");
    } finally {
      this._loading = false;
    }
  }

  _showToast(message, type) {
    const toast = this.shadowRoot.querySelector("sber-toast");
    if (toast) toast.show(message, type);
  }

  /* ---------- styles ---------- */

  static get styles() {
    return css`
      :host {
        display: block;
        padding: 16px;
        font-family: var(--paper-font-body1_-_font-family, "Roboto", sans-serif);
        color: var(--primary-text-color);
        background: var(--primary-background-color);
      }

      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 16px;
        flex-wrap: wrap;
        gap: 8px;
      }

      .header h1 {
        margin: 0;
        font-size: 24px;
        font-weight: 400;
      }

      .tabs {
        display: flex;
        border-bottom: 2px solid var(--divider-color, #e0e0e0);
        margin-bottom: 16px;
      }

      .tab {
        padding: 12px 24px;
        cursor: pointer;
        font-size: 14px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: var(--secondary-text-color);
        border-bottom: 2px solid transparent;
        margin-bottom: -2px;
        transition: color 0.2s, border-color 0.2s;
        user-select: none;
      }

      .tab:hover {
        color: var(--primary-color);
      }

      .tab.active {
        color: var(--primary-color);
        border-bottom-color: var(--primary-color);
      }

      .toolbar-wrapper {
        margin-bottom: 16px;
      }

      .card {
        background: var(--card-background-color, #fff);
        border-radius: var(--ha-card-border-radius, 12px);
        box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0, 0, 0, 0.1));
        padding: 16px;
        margin-bottom: 16px;
      }

      .card h2 {
        margin: 0 0 12px;
        font-size: 18px;
        font-weight: 500;
      }

      .error-banner {
        background: var(--error-color, #f44336);
        color: #fff;
        padding: 8px 16px;
        border-radius: 8px;
        margin-bottom: 12px;
        font-size: 13px;
      }
    `;
  }

  /* ---------- render ---------- */

  render() {
    const connected = this._status?.connected ?? false;

    return html`
      <div class="header">
        <h1>Sber MQTT Bridge</h1>
      </div>

      ${this._error ? html`<div class="error-banner">${this._error}</div>` : ""}

      <div class="toolbar-wrapper">
        <sber-toolbar
          .connected=${connected}
          .totalDevices=${this._devicesExtra.total ?? 0}
          .acknowledgedCount=${this._devicesExtra.acknowledged_count ?? 0}
          .loading=${this._loading}
          @toolbar-refresh=${this._onToolbarRefresh}
          @toolbar-republish=${this._onToolbarRepublish}
          @toolbar-add=${this._onToolbarAdd}
          @toolbar-wizard=${this._onToolbarWizard}
          @toolbar-export=${this._onToolbarExport}
          @toolbar-import=${this._onToolbarImport}
          @toolbar-bulk-add=${this._onToolbarBulkAdd}
          @toolbar-clear-all=${this._onToolbarClearAll}
        ></sber-toolbar>
      </div>

      <div class="tabs">
        <div class="tab ${this._tab === 0 ? "active" : ""}" @click=${() => this._tab = 0}>
          Devices
        </div>
        <div class="tab ${this._tab === 1 ? "active" : ""}" @click=${() => this._tab = 1}>
          Status
        </div>
      </div>

      ${this._tab === 0 ? this._renderDevices() : this._renderStatus()}

      <sber-add-dialog
        .hass=${this.hass}
        @add-entities=${this._onAddEntities}
      ></sber-add-dialog>

      <sber-wizard
        .hass=${this.hass}
        .exposedIds=${this._devices.map(d => d.entity_id)}
        @wizard-complete=${this._onWizardComplete}
      ></sber-wizard>

      <sber-toast></sber-toast>
    `;
  }

  /* ---------- tab: devices ---------- */

  _renderDevices() {
    return html`
      <sber-device-table
        .devices=${this._devices}
        .devicesExtra=${this._devicesExtra}
        @remove-entities=${this._onRemoveEntities}
        @set-override=${this._onSetOverride}
        @sync-entity=${this._onSyncEntity}
      ></sber-device-table>
    `;
  }

  /* ---------- tab: status ---------- */

  _renderStatus() {
    const s = this._status;
    const connected = s?.connected ?? false;

    return html`
      <div class="card">
        <h2>Connection</h2>
        <sber-status-card .connected=${connected}></sber-status-card>
      </div>

      <div class="card">
        <h2>Statistics</h2>
        <sber-stats-grid .status=${s}></sber-stats-grid>
      </div>
    `;
  }
}

customElements.define("sber-mqtt-panel", SberMqttPanel);
