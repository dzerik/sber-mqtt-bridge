/**
 * Sber MQTT Bridge -- Device-centric Add Device Wizard (v1.26.0, 3 steps).
 *
 * Step 1: Pick a Sber device type from a category grid.
 * Step 2: Pick an HA device whose primary entity can be promoted into
 *         the chosen category.  Each card is expanded in place with
 *         native linked sensors (preselected) and cross-device
 *         compatible sensors (opt-in).
 * Step 3: Enter name + room, submit one ``add_ha_device`` call per
 *         selected primary entity.
 *
 * Multi-add is a batch of independent calls, not a transaction: the
 * wizard remembers which primaries the backend already accepted, reports
 * the per-entity outcome and retries only the ones that failed, so a
 * second click can never register the same entity twice.
 *
 * Fires ``wizard-complete`` with ``added``/``failed`` entity id lists.
 */

/* Cache-busting: propagate our own ?v= down the import graph (lit-base.js
 * forwards it to vendor/lit.js).  Static imports would drop the query and
 * pin the browser to a stale copy of lit after an upgrade. */
const _q = new URL(import.meta.url).search;
const { LitElement, html, css } = await import(`../lit-base.js${_q}`);
const { slugify, isValidSalutName, deepActiveElement } = await import(`../utils.js${_q}`);
const { dialogStyles, buttonStyles, filterInputStyles } = await import(`../shared-styles.js${_q}`);

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
      /** Primaries the backend already accepted in this session. */
      _added: { type: Object },
      /** Per-entity failures from the last submit: [{entity_id, message}]. */
      _failed: { type: Array },
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
    this._added = new Set();
    this._failed = [];
    this._linksAttached = false;
    this._loading = false;
    this._error = "";
  }

  connectedCallback() {
    super.connectedCallback();
    /* Modal keyboard contract: Escape closes.  Bound on the element so it
     * survives shadow-DOM boundaries but never leaks past detach. */
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

  async show() {
    this._reset();
    this._returnFocusTo = deepActiveElement();
    this.open = true;
    await this.updateComplete;
    const dialog = this.shadowRoot.querySelector(".dialog");
    if (dialog) dialog.focus();
    await this._loadCategories();
  }

  hide() {
    this.open = false;
    /* Return focus to whatever opened the wizard (WCAG 2.4.3). */
    const target = this._returnFocusTo;
    this._returnFocusTo = null;
    if (target && typeof target.focus === "function") target.focus();
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

  /**
   * Advisory (never blocking) verdict on a device name.
   *
   * Mirrors ``name_utils.warn_if_suspicious_name`` on the backend, which
   * only *logs*: Sber accepts Latin names, and the wizard must not refuse
   * to submit something the bridge would happily publish.
   *
   * @param {string} name - Candidate name.
   * @returns {{level: string, text: string}} ``level`` is "", "info" or "warn".
   */
  _nameAdvice(name) {
    const value = name || "";
    if (!value) {
      return { level: "warn", text: "Empty name — Sber may reject the device" };
    }
    if (value.length > 63) {
      return { level: "warn", text: `${value.length} chars (>63) — Sber may truncate or reject` };
    }
    if (!isValidSalutName(value)) {
      return {
        level: "info",
        text: "Not Salut-friendly (3-33 Cyrillic letters, digits, spaces, hyphens) — the device still works, but voice control by this exact name may not",
      };
    }
    return { level: "", text: "" };
  }

  /** Primaries still waiting to be sent (already-added ones are skipped). */
  get _pendingPrimaries() {
    return this._selectedPrimaries.filter((eid) => !this._added.has(eid));
  }

  /**
   * Submit the batch, one ``add_ha_device`` call per pending primary.
   *
   * Each call is independent, so a mid-batch failure leaves the earlier
   * entities registered.  Those are recorded in ``_added`` and skipped on
   * retry — clicking the button again re-sends only what failed.
   */
  async _finish() {
    const device = this._devices.find((d) => d.device_id === this._selectedDeviceId);
    if (!device) return;
    const pending = this._pendingPrimaries;
    if (pending.length === 0) {
      /* Everything already went through and the submit that accepted it
       * has already emitted ``wizard-complete`` — closing must not fire a
       * second event, or the panel re-polls and toasts the same batch
       * twice.  Nothing left to send, so just close. */
      this.hide();
      return;
    }

    /* Linked sensors only attach to the FIRST accepted primary of the
     * batch — they describe the parent device once, not N times.  The
     * battery / signal sensor under a 5-socket strip is naturally one
     * shared role and Sber rejects duplicate-linked entries anyway. */
    const linkedEntityIds = Array.from(this._enabledLinks);

    this._loading = true;
    this._error = "";
    this._failed = [];
    const added = [];
    const failed = [];
    for (const primaryId of pending) {
      const form = this._perPrimary[primaryId] || { name: "", room: "" };
      try {
        await this.hass.callWS({
          type: "sber_mqtt_bridge/add_ha_device",
          device_id: device.device_id,
          primary_entity_id: primaryId,
          category: this._selectedCategory,
          linked_entity_ids: this._linksAttached ? [] : linkedEntityIds,
          name: form.name,
          room: form.room,
        });
        this._linksAttached = true;
        added.push(primaryId);
      } catch (err) {
        failed.push({ entity_id: primaryId, message: err.message || String(err) });
      }
    }
    /* Reassign instead of mutating: ``_added`` is a reactive property, and
     * Lit compares by reference — an in-place ``.add()`` leaves the badge,
     * the "(N already added)" summary and the retry label frozen. */
    this._added = new Set([...this._added, ...added]);
    this._loading = false;
    this._failed = failed;
    this._emitComplete(device, added, failed);
    if (failed.length === 0) {
      this.hide();
      return;
    }
    this._error =
      added.length > 0
        ? `Added ${added.length} of ${pending.length}. Retry sends only the ${failed.length} that failed.`
        : `Nothing was added — ${failed.length} device(s) failed.`;
  }

  /**
   * Tell the panel what actually happened, including partial batches.
   *
   * @param {object} device - Selected HA device descriptor.
   * @param {string[]} added - Entity ids accepted by this submit.
   * @param {Array} failed - ``[{entity_id, message}]`` for this submit.
   */
  _emitComplete(device, added, failed) {
    this.dispatchEvent(
      new CustomEvent("wizard-complete", {
        detail: {
          device_id: device.device_id,
          category: this._selectedCategory,
          /* Everything registered during this wizard session, not just
           * the last submit — the panel polls until all of it shows up. */
          added_entity_ids: [...this._added],
          added_now: [...added],
          failed: failed.map((f) => ({ ...f })),
          added_count: this._added.size,
          failed_count: failed.length,
          primary_entity_ids: [...this._selectedPrimaries],
          primary_entity_id: [...this._added][0] || this._selectedPrimaries[0],
          linked_count: this._enabledLinks.size,
        },
        bubbles: true,
        composed: true,
      })
    );
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

  /** Activate a ``role="button"`` card from the keyboard (Enter/Space). */
  _onKeyActivate(e, handler) {
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    e.preventDefault();
    handler();
  }

  /* ---------- render ---------- */

  render() {
    if (!this.open) return html``;
    return html`
      <div class="overlay" @click=${(e) => { if (e.target === e.currentTarget) this.hide(); }}>
        <div
          class="dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="wizard-title"
          tabindex="-1"
        >
          <div class="dialog-header">
            <h2 id="wizard-title">Add Device</h2>
            <button class="close-btn" aria-label="Close wizard" @click=${this.hide}>\u2715</button>
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
        <div class="type-grid" role="radiogroup" aria-label="${group.label} categories">
          ${group.items.map((cat) => html`
            <div
              class="type-card ${this._selectedCategory === cat.id ? "selected" : ""}"
              role="radio"
              tabindex="0"
              aria-checked=${this._selectedCategory === cat.id ? "true" : "false"}
              aria-label=${cat.label}
              @click=${() => { this._selectedCategory = cat.id; }}
              @keydown=${(e) => this._onKeyActivate(e, () => { this._selectedCategory = cat.id; })}
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
          type="search"
          aria-label="Search devices"
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
        role="button"
        tabindex=${isDisabled ? "-1" : "0"}
        aria-pressed=${isSelected ? "true" : "false"}
        aria-disabled=${isDisabled ? "true" : "false"}
        aria-label=${device.name}
        @click=${() => this._selectDevice(device)}
        @keydown=${(e) => this._onKeyActivate(e, () => this._selectDevice(device))}
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
          <b>Adding:</b> ${this._pendingPrimaries.length} ${this._pendingPrimaries.length === 1 ? "device" : "devices"}${
            this._added.size > 0 ? html` <span class="hint-inline">(${this._added.size} already added)</span>` : ""
          }
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
    /* Advisory only: the backend merely logs about non-Salut names, so the
     * wizard must not refuse to submit one (see _nameAdvice). */
    const advice = this._nameAdvice(form.name);
    const isAdded = this._added.has(primaryId);
    const failure = (this._failed || []).find((f) => f.entity_id === primaryId);
    return html`
      <div class="primary-form ${isMulti ? "compact" : ""}">
        ${isMulti
          ? html`<div class="primary-form-header"><code>${primaryId}</code></div>`
          : ""}
        ${isAdded
          ? html`<div class="outcome outcome-ok" role="status">✓ Already added — skipped on retry</div>`
          : ""}
        ${failure
          ? html`<div class="outcome outcome-fail" role="status">✗ Failed: ${failure.message}</div>`
          : ""}
        <div class="field">
          <label>${isMulti ? "Name" : "Device name (for Salut voice)"}</label>
          <input
            type="text"
            aria-label="Sber device name"
            aria-describedby="name-advice-${primaryId}"
            class="${advice.level === "warn" ? "warn" : ""}"
            placeholder="e.g. Лампа кухня"
            ?disabled=${isAdded}
            .value=${form.name}
            @input=${(e) => this._onPrimaryNameInput(primaryId, e.target.value)}
          />
          <div class="hint hint-${advice.level}" id="name-advice-${primaryId}">
            ${advice.text || (isMulti ? "" : "Will be spoken by Salut assistant")}
          </div>
        </div>

        <div class="field">
          <label>Device ID</label>
          <input type="text" aria-label="Sber device id" .value=${form.slug} readonly />
          ${isMulti ? "" : html`<div class="hint">Transliterated slug for the Sber protocol</div>`}
        </div>

        <div class="field">
          <label>Room (optional)</label>
          <input
            type="text"
            aria-label="Room"
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
    /* Name quality is advisory (see _nameAdvice) — it never gates Finish,
     * because the backend would publish the device regardless. */
    const canFinish =
      this._step === 3 && this._selectedPrimaries.length > 0 && !this._loading;
    const pending = this._pendingPrimaries.length;
    const finishLabel =
      this._failed.length > 0
        ? `Retry ${pending} failed`
        : pending > 1
          ? `Add ${pending} devices`
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
    return [dialogStyles, buttonStyles, filterInputStyles, css`
      .dialog { width: 94%; max-width: 820px; max-height: 88vh; }

      .type-card:focus-visible,
      .device-card:focus-visible {
        outline: 2px solid var(--primary-color, #03a9f4);
        outline-offset: 2px;
      }

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
      .field input:disabled { opacity: 0.6; cursor: not-allowed; }
      /* Advisory, not an error: the value is still submitted. */
      .field input.warn { border-color: var(--warning-color, #ff9800); }
      .field .hint { font-size: 11px; color: var(--secondary-text-color); margin-top: 2px; }
      .field .hint-info { color: var(--secondary-text-color); }
      .field .hint-warn { color: var(--warning-color, #ff9800); }

      .outcome {
        font-size: 12px; padding: 4px 8px; border-radius: 4px; margin-bottom: 8px;
      }
      .outcome-ok {
        background: color-mix(in srgb, var(--success-color, #4caf50) 12%, transparent);
        color: var(--success-color, #4caf50);
      }
      .outcome-fail {
        background: color-mix(in srgb, var(--error-color, #f44336) 12%, transparent);
        color: var(--error-color, #f44336);
      }

    `];
  }
}

customElements.define("sber-wizard", SberWizard);
