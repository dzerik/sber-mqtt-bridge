/**
 * Sber MQTT Bridge -- Device-centric Add Device Wizard (v1.26.0, 3 steps).
 *
 * Step 1: Pick a Sber device type from a category grid.
 * Step 2: Pick an HA device whose primary entity can be promoted into
 *         the chosen category.  Each card is expanded in place with
 *         native linked sensors (preselected) and cross-device
 *         compatible sensors (opt-in).
 * Step 3: Enter name + room, submit atomically via ``add_ha_device``.
 *
 * Fires ``wizard-complete`` with the primary entity id for the parent panel.
 */

const _v = new URL(import.meta.url).searchParams.get("v") || "";
const { slugify, isValidSalutName } = await import(`../utils.js${_v ? `?v=${_v}` : ""}`);

import { LitElement, html, css } from "../lit-base.js";


class SberWizard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      open: { type: Boolean, reflect: true },
      _step: { type: Number },
      _categories: { type: Array },
      _categoryGroups: { type: Array },
      _selectedCategory: { type: String },
      _devices: { type: Array },
      _deviceFilter: { type: String },
      _selectedDeviceId: { type: String },
      _selectedPrimary: { type: String },
      _enabledLinks: { type: Object },
      _name: { type: String },
      _slugId: { type: String },
      _room: { type: String },
      _loading: { type: Boolean },
      _error: { type: String },
    };
  }

  constructor() {
    super();
    this.open = false;
    this._reset();
  }

  _reset() {
    this._step = 1;
    this._categories = [];
    this._categoryGroups = [];
    this._selectedCategory = "";
    this._devices = [];
    this._deviceFilter = "";
    this._selectedDeviceId = "";
    this._selectedPrimary = "";
    this._enabledLinks = new Set();
    this._name = "";
    this._slugId = "";
    this._room = "";
    this._loading = false;
    this._error = "";
  }

  async show() {
    this._reset();
    this.open = true;
    await this._loadCategories();
  }

  hide() {
    this.open = false;
  }

  /* ---------- data helpers ---------- */

  async _loadCategories() {
    if (!this.hass) return;
    this._loading = true;
    this._error = "";
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/list_categories",
      });
      this._categories = result.categories || [];
      this._categoryGroups = result.groups || [];
    } catch (err) {
      this._error = "Failed to load categories: " + (err.message || err);
      this._categories = [];
      this._categoryGroups = [];
    } finally {
      this._loading = false;
    }
  }

  async _loadDevicesForCategory() {
    if (!this.hass || !this._selectedCategory) return;
    this._loading = true;
    this._error = "";
    this._devices = [];
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/list_devices_for_category",
        category: this._selectedCategory,
      });
      this._devices = result.devices || [];
    } catch (err) {
      this._error = "Failed to load devices: " + (err.message || err);
    } finally {
      this._loading = false;
    }
  }

  /* ---------- navigation ---------- */

  async _goNext() {
    if (this._step === 1 && this._selectedCategory) {
      this._step = 2;
      await this._loadDevicesForCategory();
      return;
    }
    if (this._step === 2 && this._selectedDeviceId) {
      this._prefillStep3FromSelectedDevice();
      this._step = 3;
    }
  }

  _goBack() {
    if (this._step === 3) {
      this._step = 2;
      return;
    }
    if (this._step === 2) {
      this._selectedDeviceId = "";
      this._selectedPrimary = "";
      this._enabledLinks = new Set();
      this._step = 1;
    }
  }

  _prefillStep3FromSelectedDevice() {
    const device = this._devices.find((d) => d.device_id === this._selectedDeviceId);
    if (!device) return;
    const primaryFn = device.primary?.friendly_name || device.name || "";
    if (primaryFn && !this._name) {
      this._name = primaryFn;
      this._slugId = slugify(primaryFn);
    }
    const area = device.primary?.area || device.area || "";
    if (area && !this._room) {
      this._room = area;
    }
  }

  async _finish() {
    if (!isValidSalutName(this._name)) return;
    const device = this._devices.find((d) => d.device_id === this._selectedDeviceId);
    if (!device) return;
    const primaryId = this._selectedPrimary || device.primary.entity_id;

    const linkedEntityIds = Array.from(this._enabledLinks);
    this._loading = true;
    this._error = "";
    try {
      const result = await this.hass.callWS({
        type: "sber_mqtt_bridge/add_ha_device",
        device_id: device.device_id,
        primary_entity_id: primaryId,
        category: this._selectedCategory,
        linked_entity_ids: linkedEntityIds,
        name: this._name,
        room: this._room,
      });
      this.dispatchEvent(
        new CustomEvent("wizard-complete", {
          detail: {
            device_id: device.device_id,
            primary_entity_id: primaryId,
            category: this._selectedCategory,
            linked_count: result?.linked_count ?? linkedEntityIds.length,
          },
          bubbles: true,
          composed: true,
        })
      );
      this.hide();
    } catch (err) {
      this._error = "Add failed: " + (err.message || err);
    } finally {
      this._loading = false;
    }
  }

  /* ---------- Step 2 interaction ---------- */

  _selectDevice(device) {
    if (device.already_exposed) return;
    this._selectedDeviceId = device.device_id;
    this._selectedPrimary = device.primary.entity_id;
    /* Build initial enabled-links set from native preselected sensors */
    const enabled = new Set();
    for (const linked of device.linked_native || []) {
      if (linked.preselected) enabled.add(linked.entity_id);
    }
    this._enabledLinks = enabled;
    this.requestUpdate();
  }

  _togglePrimaryAlternative(device, altEntityId) {
    if (device.device_id !== this._selectedDeviceId) return;
    this._selectedPrimary = altEntityId;
    this.requestUpdate();
  }

  _toggleLink(device, link) {
    if (device.device_id !== this._selectedDeviceId) return;
    const next = new Set(this._enabledLinks);
    if (next.has(link.entity_id)) {
      next.delete(link.entity_id);
    } else {
      /* Role conflict guard: unselect any other link with the same role */
      if (link.link_role) {
        const allLinks = [...(device.linked_native || []), ...(device.linked_compatible || [])];
        for (const other of allLinks) {
          if (
            other.entity_id !== link.entity_id &&
            other.link_role === link.link_role &&
            next.has(other.entity_id)
          ) {
            next.delete(other.entity_id);
          }
        }
      }
      next.add(link.entity_id);
    }
    this._enabledLinks = next;
    this.requestUpdate();
  }

  _onNameInput(e) {
    this._name = e.target.value;
    this._slugId = slugify(this._name);
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
            ${this._error
              ? html`<div class="error-banner">${this._error}</div>`
              : ""}
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

  /* ---------- Step 1: category grid ---------- */
  _renderStep1() {
    if (this._loading) {
      return html`<div class="empty-state">Loading categories...</div>`;
    }
    if (!this._categories.length) {
      return html`<div class="empty-state">No categories available</div>`;
    }
    const byGroup = new Map();
    for (const group of this._categoryGroups) {
      byGroup.set(group.id, { label: group.label, items: [] });
    }
    for (const cat of this._categories) {
      const bucket = byGroup.get(cat.group);
      if (bucket) bucket.items.push(cat);
      else byGroup.set(cat.group, { label: cat.group, items: [cat] });
    }
    return html`
      ${[...byGroup.values()].map((group) => group.items.length === 0 ? "" : html`
        <div class="group-label">${group.label}</div>
        <div class="type-grid">
          ${group.items.map((cat) => html`
            <div
              class="type-card ${this._selectedCategory === cat.id ? "selected" : ""}"
              @click=${() => { this._selectedCategory = cat.id; }}
            >
              <span class="type-icon">${cat.icon}</span>
              <span class="type-label">${cat.label}</span>
            </div>
          `)}
        </div>
      `)}
    `;
  }

  /* ---------- Step 2: HA device list with inline sensors ---------- */
  _renderStep2() {
    if (this._loading) {
      return html`<div class="empty-state">Loading devices...</div>`;
    }
    const filter = this._deviceFilter.trim().toLowerCase();
    const filtered = !filter
      ? this._devices
      : this._devices.filter((d) => {
          const haystack = [
            d.name,
            d.manufacturer,
            d.model,
            d.area,
            d.primary?.entity_id,
            d.primary?.friendly_name,
          ].filter(Boolean).map((s) => String(s).toLowerCase()).join(" ");
          return haystack.includes(filter);
        });

    const categoryLabel =
      this._categories.find((c) => c.id === this._selectedCategory)?.label ||
      this._selectedCategory;

    return html`
      <div class="step2-header">
        <div class="step2-category">
          <span class="step2-category-icon">${
            this._categories.find((c) => c.id === this._selectedCategory)?.icon || ""
          }</span>
          <span>${categoryLabel}</span>
        </div>
        <input
          class="filter-input"
          type="text"
          placeholder="Search by name, manufacturer, model, area..."
          .value=${this._deviceFilter}
          @input=${(e) => { this._deviceFilter = e.target.value; }}
        />
      </div>

      ${filtered.length === 0
        ? html`<div class="empty-state">No HA devices match this category</div>`
        : html`
            <div class="device-list">
              ${filtered.map((device) => this._renderDeviceCard(device))}
            </div>
          `}
    `;
  }

  _renderDeviceCard(device) {
    const isSelected = this._selectedDeviceId === device.device_id;
    const isDisabled = device.already_exposed;
    const subtitle = [device.manufacturer, device.model].filter(Boolean).join(" · ");
    return html`
      <div
        class="device-card ${isSelected ? "selected" : ""} ${isDisabled ? "disabled" : ""}"
        @click=${() => this._selectDevice(device)}
      >
        <div class="device-card-header">
          <div class="device-title">
            <div class="device-name">${device.name}</div>
            ${subtitle ? html`<div class="device-subtitle">${subtitle}</div>` : ""}
            <div class="device-meta">
              ${device.area ? html`<span class="meta-chip">📍 ${device.area}</span>` : ""}
              <span class="meta-chip">→ ${device.primary.entity_id}</span>
              ${isDisabled ? html`<span class="meta-chip meta-chip-used">✓ Added</span>` : ""}
            </div>
          </div>
        </div>

        ${isSelected && !isDisabled ? this._renderDeviceCardExpanded(device) : ""}
      </div>
    `;
  }

  _renderDeviceCardExpanded(device) {
    const alternatives = device.primary_alternatives || [];
    const nativeLinks = device.linked_native || [];
    const compatibleLinks = device.linked_compatible || [];
    const unsupported = device.unsupported || [];

    return html`
      <div class="device-card-body">
        ${alternatives.length > 0 ? html`
          <div class="expanded-section">
            <div class="expanded-title">Primary entity</div>
            <div class="primary-options">
              ${[device.primary, ...alternatives].map((opt) => html`
                <label class="primary-option ${this._selectedPrimary === opt.entity_id ? "selected" : ""}">
                  <input
                    type="radio"
                    name="primary-${device.device_id}"
                    .checked=${this._selectedPrimary === opt.entity_id}
                    @click=${(e) => { e.stopPropagation(); this._togglePrimaryAlternative(device, opt.entity_id); }}
                  />
                  <span>${opt.friendly_name || opt.entity_id}</span>
                  <span class="entity-id">${opt.entity_id}</span>
                </label>
              `)}
            </div>
          </div>
        ` : ""}

        ${nativeLinks.length > 0 ? html`
          <div class="expanded-section">
            <div class="expanded-title">Native sensors</div>
            ${nativeLinks.map((link) => this._renderLinkRow(device, link, false))}
          </div>
        ` : ""}

        ${compatibleLinks.length > 0 ? html`
          <div class="expanded-section">
            <div class="expanded-title">Compatible sensors from other devices</div>
            ${compatibleLinks.map((link) => this._renderLinkRow(device, link, true))}
          </div>
        ` : ""}

        ${unsupported.length > 0 ? html`
          <div class="expanded-section unsupported-section">
            <div class="expanded-title">Not usable</div>
            ${unsupported.map((e) => html`
              <div class="link-row disabled">
                <span class="link-name">🚫 ${e.friendly_name || e.entity_id}</span>
                <span class="entity-id">${e.entity_id}</span>
              </div>
            `)}
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderLinkRow(device, link, showOrigin) {
    const enabled = this._enabledLinks.has(link.entity_id);
    return html`
      <label class="link-row">
        <input
          type="checkbox"
          .checked=${enabled}
          @click=${(e) => { e.stopPropagation(); this._toggleLink(device, link); }}
        />
        <span class="link-role">${link.link_role || link.device_class || "?"}</span>
        <span class="link-name">${link.friendly_name || link.entity_id}</span>
        <span class="entity-id">${link.entity_id}</span>
        ${showOrigin && link.origin_device_name
          ? html`<span class="origin-chip">from: ${link.origin_device_name}</span>`
          : ""}
      </label>
    `;
  }

  /* ---------- Step 3: name + room ---------- */
  _renderStep3() {
    const nameValid = this._name.length === 0 || isValidSalutName(this._name);
    const device = this._devices.find((d) => d.device_id === this._selectedDeviceId);
    const primaryId = this._selectedPrimary || device?.primary?.entity_id || "";
    const linkedCount = this._enabledLinks.size;

    return html`
      <div class="summary-block">
        <div class="summary-line"><b>HA device:</b> ${device?.name || ""}</div>
        <div class="summary-line"><b>Primary entity:</b> <code>${primaryId}</code></div>
        <div class="summary-line"><b>Sber category:</b> ${
          this._categories.find((c) => c.id === this._selectedCategory)?.label || this._selectedCategory
        }</div>
        <div class="summary-line"><b>Linked sensors:</b> ${linkedCount}</div>
      </div>

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

  _renderFooter() {
    const canNext =
      (this._step === 1 && this._selectedCategory) ||
      (this._step === 2 && this._selectedDeviceId);
    const canFinish = this._step === 3 && isValidSalutName(this._name) && !this._loading;

    return html`
      <div class="dialog-footer">
        <div>
          ${this._step > 1
            ? html`<button class="btn btn-secondary" @click=${this._goBack}>Back</button>`
            : html`<span></span>`}
        </div>
        <div>
          ${this._step < 3
            ? html`<button class="btn btn-primary" ?disabled=${!canNext || this._loading} @click=${this._goNext}>
                Next
              </button>`
            : html`<button class="btn btn-success" ?disabled=${!canFinish} @click=${this._finish}>
                ${this._loading ? "Adding..." : "Add device"}
              </button>`}
        </div>
      </div>
    `;
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
        width: 94%; max-width: 820px; max-height: 88vh;
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

      .error-banner {
        padding: 10px 14px; margin-bottom: 12px;
        border-radius: 8px;
        background: color-mix(in srgb, var(--error-color, #f44336) 12%, transparent);
        color: var(--error-color, #f44336);
        font-size: 13px;
      }

      /* Step 1: category grid */
      .group-label {
        font-size: 13px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.5px; color: var(--secondary-text-color);
        margin: 12px 0 8px;
      }
      .type-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
        gap: 8px;
      }
      .type-card {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        padding: 14px 8px; border-radius: 8px; cursor: pointer;
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

      /* Step 2: device list */
      .step2-header {
        display: flex; flex-direction: column; gap: 10px; margin-bottom: 12px;
      }
      .step2-category {
        display: flex; align-items: center; gap: 8px;
        font-size: 14px; font-weight: 500;
        color: var(--primary-text-color);
      }
      .step2-category-icon { font-size: 22px; }

      .filter-input {
        width: 100%; padding: 8px 12px;
        border: 1px solid var(--divider-color, #ccc); border-radius: 8px;
        font-size: 13px; background: var(--card-background-color, #fff);
        color: var(--primary-text-color); outline: none; box-sizing: border-box;
      }
      .filter-input:focus { border-color: var(--primary-color); }

      .device-list { display: flex; flex-direction: column; gap: 10px; }

      .device-card {
        border: 2px solid var(--divider-color, #e0e0e0);
        border-radius: 10px;
        background: var(--card-background-color, #fff);
        cursor: pointer;
        transition: border-color 0.15s, background 0.15s;
        overflow: hidden;
      }
      .device-card:hover { border-color: var(--primary-color); }
      .device-card.selected {
        border-color: var(--primary-color);
        background: color-mix(in srgb, var(--primary-color) 6%, transparent);
      }
      .device-card.disabled {
        opacity: 0.55;
        cursor: not-allowed;
      }

      .device-card-header {
        padding: 12px 14px;
      }
      .device-title { display: flex; flex-direction: column; gap: 2px; }
      .device-name { font-size: 14px; font-weight: 500; color: var(--primary-text-color); }
      .device-subtitle { font-size: 12px; color: var(--secondary-text-color); }
      .device-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
      .meta-chip {
        display: inline-flex; align-items: center; gap: 4px;
        padding: 2px 8px; border-radius: 4px;
        font-size: 11px;
        background: var(--secondary-background-color, #eee);
        color: var(--secondary-text-color);
      }
      .meta-chip-used {
        background: var(--success-color, #4caf50);
        color: #fff;
      }

      .device-card-body {
        padding: 0 14px 12px 14px;
        border-top: 1px dashed var(--divider-color, #e0e0e0);
        margin-top: 2px;
      }

      .expanded-section { margin-top: 10px; }
      .expanded-section.unsupported-section { opacity: 0.6; }
      .expanded-title {
        font-size: 11px; font-weight: 600; text-transform: uppercase;
        letter-spacing: 0.5px; color: var(--secondary-text-color);
        margin-bottom: 6px;
      }

      .primary-options { display: flex; flex-direction: column; gap: 4px; }
      .primary-option {
        display: flex; align-items: center; gap: 8px;
        padding: 4px 6px; font-size: 13px;
        border-radius: 4px; cursor: pointer;
      }
      .primary-option.selected {
        background: color-mix(in srgb, var(--primary-color) 10%, transparent);
      }
      .primary-option input { cursor: pointer; }

      .link-row {
        display: flex; align-items: center; gap: 8px;
        padding: 4px 6px; font-size: 13px;
        cursor: pointer;
      }
      .link-row.disabled { cursor: default; color: var(--secondary-text-color); }
      .link-row input[type="checkbox"] { cursor: pointer; }
      .link-role {
        display: inline-block; padding: 1px 6px; border-radius: 4px;
        font-size: 11px; font-weight: 500;
        background: color-mix(in srgb, var(--primary-color) 15%, transparent);
        color: var(--primary-color);
        min-width: 60px; text-align: center;
      }
      .link-name { flex: 1; min-width: 0; color: var(--primary-text-color); }
      .entity-id {
        font-family: monospace; font-size: 11px;
        color: var(--secondary-text-color);
      }
      .origin-chip {
        font-size: 10px; padding: 1px 6px; border-radius: 4px;
        background: var(--secondary-background-color, #eee);
        color: var(--secondary-text-color);
      }

      /* Step 3 */
      .summary-block {
        padding: 12px 14px; margin-bottom: 16px;
        border-radius: 8px;
        background: var(--secondary-background-color, #f5f5f5);
        font-size: 13px;
      }
      .summary-line { margin: 2px 0; color: var(--primary-text-color); }
      .summary-line code {
        font-family: monospace; font-size: 12px;
        background: var(--card-background-color, #fff);
        padding: 1px 4px; border-radius: 3px;
      }

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
      .btn-success:disabled { opacity: 0.5; cursor: not-allowed; }

      .empty-state { text-align: center; padding: 32px; color: var(--secondary-text-color); font-size: 14px; }
    `;
  }
}

customElements.define("sber-wizard", SberWizard);
