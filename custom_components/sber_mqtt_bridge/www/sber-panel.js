/**
 * Sber MQTT Bridge — SPA Panel for Home Assistant sidebar.
 *
 * Main coordinator component: manages tabs, data fetching and delegates
 * rendering to child components in ./components/.
 *
 * Uses LitElement (bundled with HA) and HA WebSocket API.
 * No build step required.
 */

// Cache-busting: take our own query string (?v=X.Y.Z) and propagate it to
// every import below, so the browser fetches fresh copies on upgrade.
// lit-base.js forwards the same query to vendor/lit.js.
const _q = new URL(import.meta.url).search;
await Promise.all([
  import(`./components/sber-device-table.js${_q}`),
  import(`./components/sber-status-card.js${_q}`),
  import(`./components/sber-stats-grid.js${_q}`),
  import(`./components/sber-toolbar.js${_q}`),
  import(`./components/sber-wizard.js${_q}`),
  import(`./components/sber-toast.js${_q}`),
  import(`./components/sber-devtools.js${_q}`),
  import(`./components/sber-traces.js${_q}`),
  import(`./components/sber-state-diff.js${_q}`),
  import(`./components/sber-replay.js${_q}`),
  import(`./components/sber-validation.js${_q}`),
  import(`./components/sber-diagnose.js${_q}`),
  import(`./components/sber-settings.js${_q}`),
  import(`./components/sber-link-dialog.js${_q}`),
]);

const { LitElement, html, css } = await import(`./lit-base.js${_q}`);
const { messageBus } = await import(`./message-bus.js${_q}`);
const { t, ensurePanelTranslations } = await import(`./localize.js${_q}`);

/** Tab labels, index-aligned with the ``_tab`` state value. */
/** Tab keys; the visible label comes from `config_panel.tab.<key>`. */
const TABS = ["devices", "status", "devtools", "settings"];

/* Mutating WS commands (add / remove / override / import) return as soon as
 * the config entry is patched; the reload that rebuilds the exposed device
 * set finishes a moment later.  Instead of sleeping a fixed 1.5s — too early
 * on a slow box, needlessly slow on a fast one — the panel re-reads the
 * device list until the expected change shows up. */

/** Delay between two confirmation re-reads. */
const POLL_INTERVAL_MS = 200;
/** Give up waiting for the backend after this long and show what we have. */
const POLL_TIMEOUT_MS = 8000;

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
    this._hassReady = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this._autoRefresh = setInterval(() => this._fetchAll(), 15000);
    this._visibilityHandler = () => {
      if (document.visibilityState === "visible") this._fetchAll();
    };
    document.addEventListener("visibilitychange", this._visibilityHandler);
    /* Re-fetch immediately when element is re-attached (e.g. HA navigation) */
    if (this._hassReady) this._fetchAll();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._autoRefresh) {
      clearInterval(this._autoRefresh);
      this._autoRefresh = null;
    }
    if (this._visibilityHandler) {
      document.removeEventListener("visibilitychange", this._visibilityHandler);
      this._visibilityHandler = null;
    }
  }

  updated(changedProps) {
    if (changedProps.has("hass") && this.hass) {
      /* Panel strings live in the integration's `config_panel` translation
       * category, which nothing in the frontend fetches on its own — see
       * ./localize.js.  Cheap and idempotent: one fetch per language. */
      ensurePanelTranslations(this.hass, this);
      if (!this._hassReady) {
        this._hassReady = true;
        this._fetchAll();
      } else if (this._error) {
        /* hass object refreshed after WS reconnect — retry if in error state */
        this._fetchAll();
      }
    }
  }

  /* ---------- data ---------- */

  async _fetchAll() {
    if (!this.hass) return;
    try {
      const [devResult, statusResult] = await Promise.all([
        this.hass.callWS({ type: "sber_mqtt_bridge/devices" }),
        this.hass.callWS({ type: "sber_mqtt_bridge/status" }),
      ]);
      /* Everything the backend sends *except* the device list, forwarded
       * verbatim.  This used to hand-copy four named keys, so every counter
       * the backend added later silently read 0 in the panel: that is the
       * whole of issue #57 — "known to Sber: 0" on a bridge whose registry
       * was fully populated, because `cloud_known_count`,
       * `never_confirmed_count` and `never_confirmed` were dropped here and
       * the consumers fell back to `?? 0`.  Spreading keeps the two sides in
       * step by construction. */
      const { devices: devList, ...extra } = devResult;
      this._devices = devList || [];
      this._devicesExtra = extra;
      this._status = statusResult;
      this._error = "";
    } catch (e) {
      this._error = e.message || String(e);
    }
  }

  /**
   * Re-read the device list until ``predicate`` accepts it.
   *
   * Callers must use the return value: a false means the change was never
   * observed, so reporting unconditional success would be a lie.
   *
   * @param {Function} predicate - Called with the fresh device array;
   *     return true once the mutation is visible.
   * @param {object} [options] - ``{timeout, interval}`` overrides in ms.
   * @returns {Promise<boolean>} False if the fetch failed, the element
   *     detached or the timeout expired first.
   */
  async _refreshUntil(predicate, { timeout = POLL_TIMEOUT_MS, interval = POLL_INTERVAL_MS } = {}) {
    const deadline = Date.now() + timeout;
    for (;;) {
      await this._fetchAll();
      if (this._error) {
        /* ``_fetchAll`` swallows its failure into ``_error``, so without
         * this check a broken backend is indistinguishable from "the
         * mutation has not landed yet" and we would hammer it for the
         * whole timeout window. */
        return false;
      }
      let satisfied = false;
      try {
        satisfied = Boolean(predicate(this._devices, this._devicesExtra));
      } catch {
        /* A malformed predicate must not strand the panel in a poll loop. */
        return false;
      }
      if (satisfied) return true;
      if (Date.now() >= deadline || !this.isConnected) return false;
      await new Promise((r) => setTimeout(r, interval));
    }
  }

  /**
   * Banner shown when a mutation was accepted but never became visible.
   *
   * @param {string} what - Human-readable name of the mutation.
   */
  _reportUnconfirmed(what) {
    if (!this._error) {
      this._error = t(this.hass, "panel.unconfirmed", { action: what });
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

  async _removeEntities(entityIds) {
    this._loading = true;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/remove_entities",
        entity_ids: entityIds,
      });
      const removed = new Set(entityIds);
      const ok = await this._refreshUntil((devices) => devices.every((d) => !removed.has(d.entity_id)));
      if (!ok) this._reportUnconfirmed(t(this.hass, "panel.action_removal"));
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  async _setOverride(entityId, category) {
    this._loading = true;
    const previousCategory = this._devices.find((d) => d.entity_id === entityId)?.sber_category;
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/set_override",
        entity_id: entityId,
        category: category,
      });
      if (category === "auto") {
        /* Dropping the override hands the choice back to the mapper, which
         * may well land on the same category — there is nothing specific to
         * wait for, so poll briefly and take whatever the backend reports.
         * The boolean is deliberately ignored: "unchanged" is a legitimate
         * outcome here, not a failure to confirm. */
        await this._refreshUntil((devices) => {
          const device = devices.find((d) => d.entity_id === entityId);
          return device !== undefined && device.sber_category !== previousCategory;
        }, { timeout: 2000 });
      } else {
        const ok = await this._refreshUntil(
          (devices) => devices.find((d) => d.entity_id === entityId)?.sber_category === category
        );
        if (!ok) this._reportUnconfirmed(`Category ${category}`);
      }
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
      const ok = await this._refreshUntil(
        (devices, extra) => devices.length === 0 && (extra.total ?? 0) === 0
      );
      if (!ok) this._reportUnconfirmed(t(this.hass, "panel.action_clear_all"));
    } catch (e) {
      this._error = e.message || String(e);
    } finally {
      this._loading = false;
    }
  }

  /**
   * Total number of role→entity links across all devices.
   *
   * @param {Array} devices - Device list from ``sber_mqtt_bridge/devices``.
   * @returns {number} Link count.
   */
  _countLinks(devices) {
    return (devices || []).reduce(
      (sum, d) => sum + Object.keys(d.linked_entities || {}).length,
      0
    );
  }

  /* ---------- event handlers ---------- */

  _onToolbarRefresh() {
    this._fetchAll();
  }

  _onToolbarRepublish() {
    this._republish();
  }

  _onToolbarAdd() {
    /* v1.26.0: "Add Devices" toolbar button now opens the same
     * device-centric wizard as the primary "Wizard" button. */
    this._onToolbarWizard();
  }

  _onToolbarClearAll() {
    this._clearAll();
  }

  async _onToolbarAutoLink() {
    this._loading = true;
    const linksBefore = this._countLinks(this._devices);
    try {
      const result = await this.hass.callWS({ type: "sber_mqtt_bridge/auto_link_all" });
      if (result.linked_count === 0) {
        await this._fetchAll();
        this._showToast(t(this.hass, "panel.no_new_links"), "info");
        return;
      }
      const ok = await this._refreshUntil((devices) => this._countLinks(devices) !== linksBefore);
      this._showToast(
        ok
          ? `Auto-linked ${result.linked_count} sensor(s) to ${result.devices_affected} device(s)`
          : `Auto-linked ${result.linked_count} sensor(s), but the bridge did not confirm it — press Refresh`,
        ok ? "success" : "info"
      );
    } catch (e) {
      this._showToast(t(this.hass, "panel.auto_link_failed", { reason: e.message || e }), "error");
    } finally {
      this._loading = false;
    }
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
      this._showToast(t(this.hass, "panel.exported"), "success");
    } catch (e) {
      this._showToast(t(this.hass, "panel.export_failed", { reason: e.message || e }), "error");
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
      const expected = config?.exposed_entities;
      let confirmed = true;
      if (Array.isArray(expected)) {
        /* ``total`` counts the enabled ids, so it matches the imported list
         * even for entities the bridge could not load. */
        confirmed = await this._refreshUntil((_devices, extra) => extra.total === expected.length);
      } else {
        await this._fetchAll();
      }
      this._showToast(
        confirmed
          ? "Config imported successfully"
          : "Config imported, but the bridge did not report the new devices — press Refresh",
        confirmed ? "success" : "info"
      );
    } catch (e) {
      this._showToast(t(this.hass, "panel.import_failed", { reason: e.message || e }), "error");
    } finally {
      this._loading = false;
    }
  }

  _onLinkEntity(e) {
    const dialog = this.shadowRoot.querySelector("sber-link-dialog");
    if (dialog) dialog.show(e.detail.entityId);
  }

  async _onLinksSaved(e) {
    const { entity_id: entityId, links } = e.detail || {};
    let confirmed = true;
    if (entityId && links) {
      /* Compare the whole role→entity map: a plain count would accept the
       * stale pre-save list whenever a link is swapped rather than added. */
      confirmed = await this._refreshUntil((devices) => {
        const device = devices.find((d) => d.entity_id === entityId);
        if (!device) return false;
        const current = device.linked_entities || {};
        const roles = Object.keys(links);
        return (
          Object.keys(current).length === roles.length &&
          roles.every((role) => current[role] === links[role])
        );
      });
    } else {
      await this._fetchAll();
    }
    this._showToast(
      confirmed
        ? t(this.hass, "panel.links_updated")
        : "Links saved, but the bridge still reports the old ones — press Refresh",
      confirmed ? "success" : "info"
    );
  }

  async _onSyncEntity(e) {
    try {
      await this.hass.callWS({
        type: "sber_mqtt_bridge/publish_one_status",
        entity_id: e.detail.entityId,
      });
      this._showToast(t(this.hass, "panel.synced", { entity: e.detail.entityId }), "success");
    } catch (err) {
      this._showToast(t(this.hass, "panel.sync_failed", { reason: err.message || err }), "error");
    }
  }

  /**
   * Report the outcome of an (possibly partial) wizard batch.
   *
   * The wizard sends one ``add_ha_device`` call per selected primary, so a
   * batch can land partially.  ``detail.added_entity_ids`` lists what the
   * backend accepted and ``detail.failed`` what it rejected and why — both
   * are surfaced, and the table is polled until the accepted ones appear.
   */
  async _onWizardComplete(e) {
    const d = e.detail || {};
    const added = d.added_entity_ids || [];
    const failed = d.failed || [];
    this._loading = true;
    try {
      let confirmed = true;
      if (added.length > 0) {
        const wanted = new Set(added);
        confirmed = await this._refreshUntil(
          (devices) => devices.filter((x) => wanted.has(x.entity_id)).length === wanted.size,
          { timeout: 5000 }
        );
      } else {
        await this._fetchAll();
      }
      const linkedSuffix = d.linked_count > 0 ? ` with ${d.linked_count} linked sensor(s)` : "";
      if (failed.length > 0) {
        const names = failed.map((f) => `${f.entity_id} (${f.message})`).join("; ");
        this._showToast(
          added.length > 0
            ? `Added ${added.length}, failed ${failed.length}: ${names}`
            : `Add failed: ${names}`,
          "error"
        );
      } else if (!confirmed) {
        this._showToast(
          `Added ${added.length}, but the bridge has not listed them yet — press Refresh`,
          "info"
        );
      } else {
        this._showToast(
          added.length > 1
            ? `Added ${added.length} devices${linkedSuffix}`
            : `Device added${linkedSuffix}`,
          "success"
        );
      }
    } catch (err) {
      this._showToast(t(this.hass, "panel.refresh_failed", { reason: err.message || err }), "error");
    } finally {
      this._loading = false;
    }
  }

  /* ---------- tabs (a11y) ---------- */

  /** Select a tab and move DOM focus onto it (roving tabindex). */
  _selectTab(index) {
    this._tab = index;
    this.updateComplete.then(() => {
      const tab = this.shadowRoot.querySelector(`#sber-tab-${index}`);
      if (tab) tab.focus();
    });
  }

  /**
   * WAI-ARIA tablist keyboard support: arrows move between tabs,
   * Home/End jump to the edges, Enter/Space activate.
   */
  _onTabKeydown(e, index) {
    const last = TABS.length - 1;
    let next = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = index === last ? 0 : index + 1;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = index === 0 ? last : index - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = last;
    else if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") next = index;
    else return;
    e.preventDefault();
    this._selectTab(next);
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

      .tab:focus-visible {
        outline: 2px solid var(--primary-color);
        outline-offset: -2px;
        border-radius: 4px;
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

      /* ── Mobile ── */
      @media (max-width: 768px) {
        :host {
          padding: 8px;
        }
        .header h1 {
          font-size: 20px;
        }
        .tabs {
          overflow-x: auto;
          -webkit-overflow-scrolling: touch;
          scrollbar-width: none;
        }
        .tabs::-webkit-scrollbar {
          display: none;
        }
        .tab {
          padding: 10px 14px;
          font-size: 12px;
          white-space: nowrap;
          flex-shrink: 0;
        }
        .card {
          padding: 12px;
          border-radius: 8px;
        }
      }
    `;
  }

  /* ---------- render ---------- */

  render() {
    const connected = this._status?.connected ?? false;

    return html`
      <div class="header">
        <h1>Sber MQTT Bridge ${this._status?.version ? html`<span style="font-size:13px;font-weight:400;color:var(--secondary-text-color);margin-left:8px">v${this._status.version}</span>` : ""}</h1>
      </div>

      ${this._error ? html`<div class="error-banner">${this._error}</div>` : ""}

      <div class="toolbar-wrapper">
        <sber-toolbar
          .hass=${this.hass}
          .connected=${connected}
          .phase=${this._status?.phase || "disconnected"}
          .totalDevices=${this._devicesExtra.total ?? 0}
          .acknowledgedCount=${this._devicesExtra.acknowledged_count ?? 0}
          .cloudKnownCount=${this._devicesExtra.cloud_known_count ?? 0}
          .loading=${this._loading}
          .healthScore=${this._status?.health?.score || "healthy"}
          .healthIssues=${this._status?.health?.issues || []}
          @toolbar-refresh=${this._onToolbarRefresh}
          @toolbar-republish=${this._onToolbarRepublish}
          @toolbar-add=${this._onToolbarAdd}
          @toolbar-wizard=${this._onToolbarWizard}
          @toolbar-export=${this._onToolbarExport}
          @toolbar-import=${this._onToolbarImport}
          @toolbar-clear-all=${this._onToolbarClearAll}
          @toolbar-auto-link=${this._onToolbarAutoLink}
          @toolbar-toast=${(e) => this._showToast(e.detail.message, e.detail.type)}
        ></sber-toolbar>
      </div>

      <div class="tabs" role="tablist" aria-label="${t(this.hass, 'panel.sections')}">
        ${TABS.map(
          (label, i) => html`
            <div
              class="tab ${this._tab === i ? "active" : ""}"
              role="tab"
              id="sber-tab-${i}"
              aria-controls="sber-tabpanel"
              aria-selected=${this._tab === i ? "true" : "false"}
              tabindex=${this._tab === i ? "0" : "-1"}
              @click=${() => this._selectTab(i)}
              @keydown=${(e) => this._onTabKeydown(e, i)}
            >
              ${t(this.hass, `tab.${label}`)}
            </div>
          `
        )}
      </div>

      <div
        id="sber-tabpanel"
        role="tabpanel"
        aria-labelledby="sber-tab-${this._tab}"
      >
        ${this._tab === 0 ? this._renderDevices()
          : this._tab === 1 ? this._renderStatus()
          : this._tab === 2 ? this._renderDevtools()
          : this._renderSettings()}
      </div>

      <sber-wizard
        .hass=${this.hass}
        @wizard-complete=${this._onWizardComplete}
      ></sber-wizard>

      <sber-link-dialog
        .hass=${this.hass}
        @links-saved=${this._onLinksSaved}
        @links-error=${(e) => this._showToast(t(this.hass, "panel.link_failed", { reason: e.detail.message }), "error")}
      ></sber-link-dialog>

      <sber-toast .hass=${this.hass}></sber-toast>
    `;
  }

  /* ---------- tab: devices ---------- */

  _renderDevices() {
    return html`
      <sber-device-table
        .hass=${this.hass}
        .devices=${this._devices}
        .devicesExtra=${this._devicesExtra}
        @remove-entities=${this._onRemoveEntities}
        @set-override=${this._onSetOverride}
        @sync-entity=${this._onSyncEntity}
        @link-entity=${this._onLinkEntity}
      ></sber-device-table>
    `;
  }

  /* ---------- tab: status ---------- */

  _renderStatus() {
    const s = this._status;
    const connected = s?.connected ?? false;

    return html`
      <div class="card">
        <h2>${t(this.hass, "panel.connection")}</h2>
        <sber-status-card .hass=${this.hass} .connected=${connected} .phase=${s?.phase || "disconnected"}></sber-status-card>
      </div>

      <div class="card">
        <h2>${t(this.hass, "panel.statistics")}</h2>
        <sber-stats-grid .hass=${this.hass} .status=${s}></sber-stats-grid>
      </div>
    `;
  }

  /* ---------- tab: devtools ---------- */

  _renderDevtools() {
    return html`
      <sber-devtools
        .hass=${this.hass}
        .bus=${messageBus}
        @devtools-toast=${(e) => this._showToast(e.detail.message, e.detail.type)}
      ></sber-devtools>
      <sber-traces .hass=${this.hass}></sber-traces>
      <sber-state-diff .hass=${this.hass}></sber-state-diff>
      <sber-replay .hass=${this.hass} .bus=${messageBus}></sber-replay>
      <sber-validation .hass=${this.hass}></sber-validation>
      <sber-diagnose .hass=${this.hass}></sber-diagnose>
    `;
  }

  /* ---------- tab: settings ---------- */

  _renderSettings() {
    return html`
      <sber-settings
        .hass=${this.hass}
        @settings-toast=${(e) => this._showToast(e.detail.message, e.detail.type)}
      ></sber-settings>
    `;
  }
}

customElements.define("sber-mqtt-panel", SberMqttPanel);
