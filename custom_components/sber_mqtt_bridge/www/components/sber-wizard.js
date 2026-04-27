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
      _selectedPrimaries: { type: Array },
      _enabledLinks: { type: Object },
      /* Per-primary Step 3 form values keyed by entity_id.
       * Multi-select case (e.g. power strip with 5 sockets) keeps an
       * independent {name, slug, room} for each selected primary. */
      _perPrimary: { type: Object },
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
    this._selectedPrimaries = [];
    this._enabledLinks = new Set();
    this._perPrimary = {};
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
    if (this._step === 2 && this._selectedDeviceId && this._selectedPrimaries.length > 0) {
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
      this._selectedPrimaries = [];
      this._enabledLinks = new Set();
      this._perPrimary = {};
      this._step = 1;
    }
  }

  _prefillStep3FromSelectedDevice() {
    const device = this._devices.find((d) => d.device_id === this._selectedDeviceId);
    if (!device) return;
    const allPrimaries = [device.primary, ...(device.primary_alternatives || [])];
    const next = { ...this._perPrimary };
    for (const eid of this._selectedPrimaries) {
      if (next[eid]) continue; /* preserve user edits on Back/Next */
      const opt = allPrimaries.find((p) => p.entity_id === eid);
      const friendly = opt?.friendly_name || eid;
      const area = opt?.area || device.area || "";
      next[eid] = {
        name: friendly,
        slug: slugify(friendly),
        room: area,
      };
    }
    this._perPrimary = next;
  }

  async _finish() {
    const device = this._devices.find((d) => d.device_id === this._selectedDeviceId);
    if (!device) return;
    /* Validate all per-primary names before sending anything. */
    for (const eid of this._selectedPrimaries) {
      const form = this._perPrimary[eid];
      if (!form || !isValidSalutName(form.name)) {
        this._error = `Invalid name for ${eid}`;
        return;
      }
    }

    /* Linked sensors only attach to the FIRST primary in the multi-add
     * batch — they describe the parent device once, not N times.  The
     * battery / signal sensor under a 5-socket strip is naturally one
     * shared role and Sber rejects duplicate-linked entries anyway. */
    const linkedEntityIds = Array.from(this._enabledLinks);

    this._loading = true;
    this._error = "";
    const results = [];
    let linkedAttached = false;
    try {
      for (const primaryId of this._selectedPrimaries) {
        const form = this._perPrimary[primaryId];
        const linksForThis = linkedAttached ? [] : linkedEntityIds;
        const res = await this.hass.callWS({
          type: "sber_mqtt_bridge/add_ha_device",
          device_id: device.device_id,
          primary_entity_id: primaryId,
          category: this._selectedCategory,
          linked_entity_ids: linksForThis,
          name: form.name,
          room: form.room,
        });
        results.push(res);
        linkedAttached = true;
      }
      this.dispatchEvent(
        new CustomEvent("wizard-complete", {
          detail: {
            device_id: device.device_id,
            primary_entity_ids: [...this._selectedPrimaries],
            primary_entity_id: this._selectedPrimaries[0],
            category: this._selectedCategory,
            added_count: results.length,
            linked_count: linkedEntityIds.length,
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
    /* Default selection: only the inherent primary checked.  Multi-channel
     * devices (power strips, multi-gang switches) start with one socket
     * pre-selected; the user opts the rest in via checkboxes. */
    this._selectedPrimaries = [device.primary.entity_id];
    this._perPrimary = {};
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
    const idx = this._selectedPrimaries.indexOf(altEntityId);
    if (idx >= 0) {
      /* At least one primary must remain selected. */
      if (this._selectedPrimaries.length === 1) return;
      const next = [...this._selectedPrimaries];
      next.splice(idx, 1);
      this._selectedPrimaries = next;
      const cleaned = { ...this._perPrimary };
      delete cleaned[altEntityId];
      this._perPrimary = cleaned;
    } else {
      this._selectedPrimaries = [...this._selectedPrimaries, altEntityId];
    }
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

  _onPrimaryNameInput(primaryId, value) {
    const current = this._perPrimary[primaryId] || { name: "", slug: "", room: "" };
    this._perPrimary = {
      ...this._perPrimary,
      [primaryId]: { ...current, name: value, slug: slugify(value) },
    };
  }

  _onPrimaryRoomInput(primaryId, value) {
    const current = this._perPrimary[primaryId] || { name: "", slug: "", room: "" };
    this._perPrimary = {
      ...this._perPrimary,
      [primaryId]: { ...current, room: value },
    };
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
    const allPrimaries = [device.primary, ...alternatives];

    return html`
      <div class="device-card-body">
        ${alternatives.length > 0 ? html`
          <div class="expanded-section">
            <div class="expanded-title">
              Primary entities
              <span class="multi-hint">— check every channel you want to expose</span>
            </div>
            <div class="primary-options">
              ${allPrimaries.map((opt) => {
                const checked = this._selectedPrimaries.includes(opt.entity_id);
                return html`
                  <label class="primary-option ${checked ? "selected" : ""}">
                    <input
                      type="checkbox"
                      .checked=${checked}
                      @click=${(e) => { e.stopPropagation(); this._togglePrimaryAlternative(device, opt.entity_id); }}
                    />
                    <span>${opt.friendly_name || opt.entity_id}</span>
                    <span class="entity-id">${opt.entity_id}</span>
                  </label>
                `;
              })}
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

  /* ---------- Step 3: name + room (single or multi-primary) ---------- */
  _renderStep3() {
    const device = this._devices.find((d) => d.device_id === this._selectedDeviceId);
    const linkedCount = this._enabledLinks.size;
    const categoryLabel =
      this._categories.find((c) => c.id === this._selectedCategory)?.label || this._selectedCategory;
    const isMulti = this._selectedPrimaries.length > 1;

    return html`
      <div class="summary-block">
        <div class="summary-line"><b>HA device:</b> ${device?.name || ""}</div>
        <div class="summary-line"><b>Sber category:</b> ${categoryLabel}</div>
        <div class="summary-line">
          <b>Adding:</b> ${this._selectedPrimaries.length} ${this._selectedPrimaries.length === 1 ? "device" : "devices"}
        </div>
        <div class="summary-line"><b>Linked sensors:</b> ${linkedCount}${
          isMulti && linkedCount > 0
            ? html` <span class="hint-inline">(attached to first device only)</span>`
            : ""
        }</div>
      </div>

      ${this._selectedPrimaries.map((primaryId) => this._renderPrimaryForm(primaryId, isMulti))}
    `;
  }

  _renderPrimaryForm(primaryId, isMulti) {
    const form = this._perPrimary[primaryId] || { name: "", slug: "", room: "" };
    const nameValid = form.name.length === 0 || isValidSalutName(form.name);
    return html`
      <div class="primary-form ${isMulti ? "compact" : ""}">
        ${isMulti
          ? html`<div class="primary-form-header"><code>${primaryId}</code></div>`
          : ""}
        <div class="field">
          <label>${isMulti ? "Name" : "Device name (for Salut voice)"}</label>
          <input
            type="text"
            class="${!nameValid ? "invalid" : ""}"
            placeholder="e.g. Лампа кухня"
            .value=${form.name}
            @input=${(e) => this._onPrimaryNameInput(primaryId, e.target.value)}
          />
          ${!nameValid
            ? html`<div class="error-hint">3-33 chars, Cyrillic + digits + spaces only</div>`
            : isMulti ? "" : html`<div class="hint">Will be spoken by Salut assistant</div>`}
        </div>

        <div class="field">
          <label>Device ID</label>
          <input type="text" .value=${form.slug} readonly />
          ${isMulti ? "" : html`<div class="hint">Transliterated slug for the Sber protocol</div>`}
        </div>

        <div class="field">
          <label>Room (optional)</label>
          <input
            type="text"
            placeholder="e.g. Кухня"
            .value=${form.room}
            @input=${(e) => this._onPrimaryRoomInput(primaryId, e.target.value)}
          />
        </div>
      </div>
    `;
  }

  _renderFooter() {
    const canNext =
      (this._step === 1 && this._selectedCategory) ||
      (this._step === 2 && this._selectedDeviceId && this._selectedPrimaries.length > 0);
    const allNamesValid =
      this._selectedPrimaries.length > 0 &&
      this._selectedPrimaries.every((eid) => isValidSalutName(this._perPrimary[eid]?.name || ""));
    const canFinish = this._step === 3 && allNamesValid && !this._loading;
    const finishLabel = this._selectedPrimaries.length > 1
      ? `Add ${this._selectedPrimaries.length} devices`
      : "Add device";

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
                ${this._loading ? "Adding..." : finishLabel}
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

      .multi-hint {
        font-weight: 400; text-transform: none; letter-spacing: 0;
        color: var(--secondary-text-color); margin-left: 6px;
      }
      .hint-inline {
        font-size: 11px; color: var(--secondary-text-color); margin-left: 4px;
      }

      .primary-form {
        background: var(--secondary-background-color, #f5f5f5);
        padding: 12px 14px; border-radius: 8px;
        margin-bottom: 12px;
      }
      .primary-form.compact .field { margin-bottom: 8px; }
      .primary-form.compact .field:last-child { margin-bottom: 0; }
      .primary-form-header {
        margin: 0 0 8px 0;
        font-size: 11px; color: var(--secondary-text-color);
        font-family: monospace;
      }
      .primary-form-header code {
        background: var(--card-background-color, #fff);
        padding: 2px 6px; border-radius: 4px;
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
