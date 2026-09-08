/**
 * Sber MQTT Bridge — panel localization.
 *
 * The panel reads its strings from the integration's own translation
 * files, so a Russian user sees a Russian panel without us shipping a
 * second copy of every string in JavaScript.
 *
 * ## Why this works (checked against Home Assistant sources)
 *
 * Home Assistant serves translations per *category*, and `config_panel`
 * is one of the categories both sides know about:
 *
 * - backend: `homeassistant/helpers/translation.py` builds its cache from
 *   whatever top-level sections the integration's `translations/<lang>.json`
 *   actually contains, and `frontend/get_translations` will hand any of
 *   them to the client;
 * - frontend: `config_panel` is a member of `TranslationCategory`
 *   (`src/data/translation.ts`) — the very category ZHA's own config panel
 *   loads with `hass.loadBackendTranslation("config_panel", "zha")`;
 * - hassfest: `script/hassfest/translations.py` accepts an optional
 *   `config_panel` section of arbitrarily nested slug keys, so these
 *   strings pass validation like any other section.
 *
 * The catch is that the category is **not** loaded automatically: nothing
 * in the frontend fetches it for a custom panel. {@link ensurePanelTranslations}
 * does it once per language; until it resolves (and on a Home Assistant so
 * old it has no `loadBackendTranslation`) {@link t} falls back to the
 * English text baked into {@link EN_FALLBACK}.
 *
 * Home Assistant itself loads English first and overlays the requested
 * language on top, so a key that exists in `en.json` but not in `ru.json`
 * silently renders in English — no special handling needed here.
 *
 * ## How to add a string
 *
 * 1. Add the key to `strings.json` and `translations/en.json` under
 *    `config_panel.<block>.<key>` (both files, same English text).
 * 2. Add the Russian text to `translations/ru.json` under the same path.
 * 3. Add the same dotted key to {@link EN_FALLBACK} below with the English
 *    text — this is what shows before the fetch completes.
 * 4. Render it as `${t(this.hass, "block.key")}`.
 *
 * Keys must be `[a-z0-9_-]+` per hassfest, values must not contain HTML.
 */

/** Integration domain — first segment of every translation key. */
export const DOMAIN = "sber_mqtt_bridge";

/**
 * Home Assistant translation category carrying the panel's strings.
 *
 * See the module docstring: this is an officially supported section of
 * `strings.json`, not an invention of ours.
 */
export const CATEGORY = "config_panel";

/**
 * English text for every key the panel renders.
 *
 * Used before {@link ensurePanelTranslations} resolves and whenever the
 * backend has nothing for the key.  Keys are the dotted path below
 * `config_panel.` and must mirror `translations/en.json`.
 */
export const EN_FALLBACK = {
  // --- impulse gate settings (issue #53) ---
  "gate_options.title": "Impulse gate",
  "gate_options.invert_contact": "Inverted contact",
  "gate_options.invert_contact_description":
    'Enable when the linked contact sensor reports "on" while the gate is closed',
  "gate_options.impulse_service": "Impulse service",
  "gate_options.impulse_service_auto": "Automatic (toggle)",
  "gate_options.impulse_service_toggle": "switch.toggle",
  "gate_options.impulse_service_turn_on": "switch.turn_on",
  "gate_options.travel_time": "Leaf travel time (seconds)",
  "gate_options.travel_time_description":
    "Time the gate needs to travel end to end. 0 disables it: the position then changes only when the contact sensor reports. With a value set, the gate reports \"opening\" / \"closing\" right after the impulse — and for that whole time the Sber app blocks its control button in both directions, so a movement cannot be interrupted from the app until the timer runs out.",
  "gate_options.auto_close_time": "Auto-close delay (seconds)",
  "gate_options.auto_close_time_description":
    "Enter the same delay your gate board uses to close the leaf after it was opened — the bridge cannot read that setting itself. 0 disables it. The countdown starts when the contact sensor reports the gate open, no matter who opened it: the app, a remote or a GSM call. When it runs out the gate reports \"closing\" until the sensor says otherwise, and the Sber app blocks its control button while that lasts. Set the leaf travel time as well: without it that \"closing\" is assumed to last 30 seconds, and a slower leaf is reported as open — with an active button — while it is still moving.",
  "gate_options.contact_stale":
    "The contact sensor is unavailable — the last known position is shown",
  "gate_options.missing_required_link_warning":
    'This gate has no position sensor linked, so it reports "closed" whatever the leaf does. Link a binary sensor in the "open_state" role.',
  "gate_options.save": "Save gate options",
  "gate_options.missing_required_role":
    "Link the gate position sensor (a binary sensor with device class garage door, door or opening) before adding this device",

  // --- kettle operation modes ---
  "kettle_options.title": "Kettle operation modes",
  "kettle_options.off_mode": '"Off" mode',
  "kettle_options.boil_mode": '"Boil" mode',
  "kettle_options.heat_mode": '"Heat to setpoint" mode',
  "kettle_options.mode_auto": "Detect automatically",
  "kettle_options.resolved": "In use: {mode}",
  "kettle_options.unresolved":
    "Not detected — the bridge falls back to turning the kettle on and off",
  "kettle_options.no_modes":
    "This kettle reports no operation modes, so the bridge switches it on and off directly.",
  "kettle_options.save": "Save kettle options",

  // --- stats ---
  "stats.uptime": "Uptime",
  "stats.messages_received": "Messages received",
  "stats.messages_sent": "Messages sent",
  "stats.commands": "Commands",
  "stats.config_requests": "Config requests",
  "stats.status_requests": "Status requests",
  "stats.sber_errors": "Sber errors",
  "stats.publish_errors": "Publish errors",
  "stats.reconnects": "Reconnects",
  "stats.entities_exposed": "Entities exposed",
  "stats.loading": "Loading status…",
  "stats.never_confirmed": "Never confirmed",
  "stats.never_confirmed_title": "Never confirmed by Sber",
  "stats.never_confirmed_hint": "Devices the Sber cloud has never once asked about. Survives restarts, so a device listed here is genuinely not getting through.",
  "stats.last_error": "Last error from Sber",
  "stats.last_error_superseded":
    "Sber has talked to the bridge since — the bridge may already be working again",

  // --- Sber error codes (c2c/error, c2c/common-error) ---
  // Wording follows Sber's own, one line per documented code; a code the
  // reference does not list falls back to `sber_error.unknown`.
  "sber_error.400": "request validation error",
  "sber_error.401": "authorization error",
  "sber_error.403": "token verification error",
  "sber_error.500": "internal system error",
  "sber_error.503": "server unavailable",
  "sber_error.unknown": "error code not described in the Sber documentation",

  // --- json ---
  "json.copy": "Copy JSON",
  "json.copied": "Copied",
  "json.copy_failed": "Copy failed",
  "json.collapse": "Collapse",
  "json.expand": "Show all {lines} lines",

  // --- row ---
  "row.online": "Online",
  "row.offline": "Offline",
  "row.loading": "Loading…",
  "row.select": "Select {entity}",
  "row.details": "Show details for {entity}",
  "row.override": "Sber category override for {entity}",
  // --- tab ---
  "tab.devices": "Devices",
  "tab.status": "Status",
  "tab.devtools": "DevTools",
  "tab.settings": "Settings",

  // --- panel ---
  "panel.connection": "Connection",
  "panel.statistics": "Statistics",
  "panel.unconfirmed": "{action} was accepted but the bridge did not confirm it — press Refresh.",
  "panel.action_removal": "Removal",
  "panel.action_clear_all": "Clear all",
  "panel.no_new_links": "No new links found — all devices already linked or no siblings",
  "panel.auto_link_failed": "Auto-link failed: {reason}",
  "panel.exported": "Config exported",
  "panel.export_failed": "Export failed: {reason}",
  "panel.import_failed": "Import failed: {reason}",
  "panel.links_updated": "Entity links updated",
  "panel.synced": "Synced: {entity}",
  "panel.sync_failed": "Sync failed: {reason}",
  "panel.refresh_failed": "Refresh after add failed: {reason}",
  "panel.link_failed": "Link failed: {reason}",

  // --- diff ---
  "diff.title": "State Diffs",
  // --- table ---
  "table.total_exposed": "Total exposed:",
  "table.known_to_sber": "Known to Sber:",
  "table.confirmed_session": "Confirmed this session:",
  "table.never_confirmed": "Never confirmed:",
  "table.known_hint": "Devices the Sber cloud is known to hold. Remembered across restarts.",
  "table.session_hint": "Confirmed since this bridge started. Empty right after a Home Assistant restart — the cloud has no reason to speak up until the app asks for state.",
  "table.never_hint": "The cloud has never once asked about these. Unlike the counter above, this does not fill up after a restart — a device staying here is the signature of a silent rejection.",
  "table.never_confirmed_list": "Never confirmed by Sber: {entities}",
  "table.search": "Search devices",
  "table.search_placeholder": "Search devices…",
  "table.select_all": "Select all devices",
  "table.col_entity": "Entity ID",
  "table.col_name": "Name",
  "table.col_category": "Category",
  "table.col_room": "Room",
  "table.col_state": "State",
  "table.col_online": "Online",
  "table.col_features": "Features",
  "table.col_actions": "Actions",
  "table.sort_by": "Sort by {column}",

  // --- link ---
  "link.title": "Link Entities",
  "link.load_failed": "Failed to load candidates",
  "link.link_entity": "Link {entity}",
  "link.saving": "Saving…",
  "link.save": "Save",
  "link.save_count": "Save ({count})",
  // --- settings ---
  "settings.group.connection": "Connection",
  "settings.group.performance": "Performance",
  "settings.group.device_sync": "Device sync",
  "settings.group.commands": "Commands",
  "settings.group.debug": "Debug",
  "settings.group.loop_detection": "Loop detection",
  "settings.group.diagnostics": "Diagnostics",
  "settings.note.connection": "Changes take effect on next reconnect",
  "settings.note.performance": "Applied immediately",
  "settings.note.device_sync": "Sber reads every config publish as the COMPLETE device list, so one that omits a device makes the cloud drop it and re-register it later in the hub's room. The bridge therefore waits for devices to load before publishing. Raise the settle delay if you have battery-powered Zigbee sensors that wake up slowly.",
  "settings.note.commands": "Applied immediately",
  "settings.note.debug": "Applied immediately",
  "settings.note.loop_detection": "Adds a per-HA marker to partner_meta.ha_serial_number on every published device. Sister integrations that mirror Sber devices back into HA use it to detect import loops. Disabled by default.",
  "settings.note.diagnostics": "Surfaces post-publish silent-rejection audits as HA repair tiles. Off by default — Sber may legitimately not call status_request for hours after accepting a device, producing false positives. Audit data stays visible in the panel and WARN log either way.",
  "settings.field.reconnect_interval_min": "Min reconnect interval (s)",
  "settings.field.reconnect_interval_max": "Max reconnect interval (s)",
  "settings.field.sber_verify_ssl": "Verify SSL certificate",
  "settings.field.debounce_delay": "State publish debounce (s)",
  "settings.field.max_mqtt_payload_size": "Max MQTT payload (bytes)",
  "settings.field.config_settle_delay": "Config settle delay (s)",
  "settings.field.config_max_wait": "Max wait for devices (s)",
  "settings.field.confirm_delay": "Delayed state confirmation (s)",
  "settings.field.ack_audit_delay": "Silent-rejection audit delay (s)",
  "settings.field.message_log_size": "MQTT message log buffer",
  "settings.field.ha_serial_number_enabled": "Emit ha_serial_number marker",
  "settings.field.silent_rejection_alerts": "Show silent-rejection repair tile",
  "settings.load_failed": "Failed to load settings: {reason}",
  "settings.saved": "Settings saved",
  "settings.save_failed": "Save failed: {reason}",
  "settings.saving": "Saving…",
  "settings.save": "Save",
  "settings.hub_title": "Hub Device",
  "settings.hub_name": "Name",
  "settings.hub_home": "Home",
  "settings.hub_room": "Room",
  "settings.hub_version": "Version",
  "settings.hub_online": "Online",
  "settings.hub_children": "Children",
  "settings.hub_auto_parent": "Auto-assign parent_id",

  // --- wizard ---
  "wizard.title": "Add Device",
  "wizard.categories_failed": "Failed to load categories: {reason}",
  "wizard.devices_failed": "Failed to load devices: {reason}",
  "wizard.empty_name": "Empty name — Sber may reject the device",
  "wizard.search": "Search devices",
  "wizard.search_placeholder": "Search by name, manufacturer, model, area…",
  "wizard.adding": "Adding:",
  "wizard.device_count": "{count} device(s)",
  "wizard.name": "Name",
  "wizard.name_voice": "Device name (for Salut voice)",
  "wizard.name_example": "e.g. Лампа кухня",
  "wizard.name_hint": "Will be spoken by Salut assistant",
  "wizard.device_id": "Device ID",
  "wizard.room": "Room (optional)",
  "wizard.room_short": "Room",
  "wizard.room_example": "e.g. Кухня",
  "wizard.finish": "Add device",
  "wizard.adding_progress": "Adding…",
  "wizard.back": "Back",
  // --- devtools ---
  "devtools.config_sent": "Config sent to Sber",
  "devtools.states_sent": "States sent to Sber",
  "devtools.copied": "Copied to clipboard",
  "devtools.copy_failed": "Copy failed",
  "devtools.raw_config": "Raw Config Payload",
  "devtools.raw_states": "Raw State Payload",
  "devtools.loading": "Loading…",
  "devtools.load_config": "Load Config",
  "devtools.load_states": "Load States",
  "devtools.load_hint": "Click the button above to load data…",
  "devtools.edit_hint": "Edit JSON and click Send to publish to Sber…",
  "devtools.sending": "Sending…",
  "devtools.send_config": "Send Config to Sber",
  "devtools.message_log": "MQTT Message Log",
  "devtools.refresh": "Refresh",
  "devtools.clear_log": "Clear Log",
  "devtools.col_time": "Time",
  "devtools.col_dir": "Dir",
  "devtools.col_topic": "Topic",
  "devtools.col_payload": "Payload",

  // --- validation ---
  "validation.title": "Schema Validation",
  "validation.clear": "Clear",
  "validation.no_issues": "No issues",

  // --- traces ---
  "traces.title": "Correlation Timeline",
  "traces.clear": "Clear Traces",
  "traces.no_ack": "Sber did not acknowledge",

  // --- replay ---
  "replay.title": "Replay & Inject",
  "replay.manual": "Manual inject",
  "replay.topic": "Topic suffix",
  "replay.payload_hint": "Sber JSON payload…",
  "replay.busy": "Working…",
  "replay.inject": "Inject",
  "replay.injecting": "Injecting…",
  "replay.replaying": "Replaying…",
  "replay.from_log": "Replay from log",
  "replay.col_time": "Time",
  "replay.col_topic": "Topic",
  "replay.col_payload": "Payload",

  // --- diagnose ---
  "diagnose.title": "Why isn't it working?",
  "diagnose.enter_entity": "Enter an entity_id to diagnose.",
  "diagnose.copy_failed": "Copy failed — clipboard unavailable",
  "diagnose.entity_label": "Entity ID to diagnose",
  "diagnose.entity_placeholder": "entity_id (e.g. light.kitchen)",
  "diagnose.running": "Running…",
  "diagnose.run": "Diagnose",
  "diagnose.toggle_raw": "Toggle raw summary",
  "diagnose.raw_summary": "Raw summary",
  // --- validation ---
  "validation.views": "Validation views",
  "validation.none_yet": "No publishes validated yet.",
  "validation.no_issues_yet": "No issues yet.",
  "validation.col_entity": "Entity",
  "validation.col_issue": "Issue",
  "validation.col_feature": "Feature",
  "validation.col_desc": "Description",
  "validation.col_time": "Time",

  // --- validation issue sentences (schema_validator.VALIDATION_MESSAGES) ---
  // Rendered through `t()` with a dynamic key, so the parity tests that
  // scan for literal `t(this.hass, "…")` calls cannot see them; they are
  // covered instead by tests/hacs/test_validation_messages_are_localized.py,
  // which walks the validator's own catalogue key by key.
  "validation_issue.allowed_values_bad_type":
    "Feature “{key}”: allowed_values declares type “{declared}”, but Sber only lets a model override {permitted}. The limit will not be applied.",
  "validation_issue.allowed_values_inert":
    "Feature “{key}”: an allowed_values entry of type “{declared}” restricts nothing — Sber only overrides {permitted}. It does not affect the device and can be removed.",
  "validation_issue.allowed_values_narrowing_unconfirmed":
    "Feature “{key}”: the model shortens its allowed values, and this function's page does not state that shortening is permitted. Sber does not forbid it in writing either — check the model against the documentation.",
  "validation_issue.allowed_values_type_mismatch":
    "Feature “{key}”: allowed_values declares type “{declared}” while Sber types the feature itself as “{expected}”.",
  "validation_issue.allowed_values_unknown_enum":
    "Feature “{key}”: allowed_values offers {sent}, which is missing from Sber's vocabulary for this feature ({allowed}). The app will draw a button that does nothing.",
  "validation_issue.allowed_values_widened":
    "Feature “{key}”: the model declares the range {declared_min}…{declared_max} while Sber documents {min}…{max}. A range may only be narrowed, never widened. Limit the entity in Home Assistant or in the bridge's redefinitions.",
  "validation_issue.allowed_values_wrong_block":
    "Feature “{key}”: the entry declares type “{declared}” but carries its limits in {present} instead of “{expected_block}”. Sber cannot read such an entry.",
  "validation_issue.colour_component_out_of_range":
    "Feature “{key}”: colour component {component} = {sent} is outside the documented range {min}…{max}. Sber will show a different colour or drop the value.",
  "validation_issue.conditional_group_missing":
    "Category “{category}” requires at least one of: {group}. The device declares none of them, so Sber will drop it.",
  "validation_issue.declared_not_published":
    "Feature “{key}” is advertised in the device model but carries no value in this publish. Sber's answer to a state query must list every advertised feature, so the app is left with a control that never updates. Either publish a value for it or drop the feature.",
  "validation_issue.device_missing_field":
    "The device descriptor has no obligatory field “{field}”. Sber drops such a device whole — it will not appear in the app.",
  "validation_issue.device_missing_model":
    "The device declares no model: it needs either the “model_id” of an already registered model, or an inline “model” description.",
  "validation_issue.feature_unknown_for_category_model":
    "Feature “{key}” is advertised in the device model but is not in Sber's reference set for category “{category}”. Remove it, or move the device to a category that has it.",
  "validation_issue.feature_unknown_for_category_state":
    "Feature “{key}” is not in Sber's reference set for category “{category}”.",
  "validation_issue.model_missing_field":
    "The device model has no obligatory field “{field}”. Sber drops the model, and with it every device built on it.",
  "validation_issue.obligatory_not_declared":
    "Feature “{key}” is obligatory for category “{category}” but is missing from the device model. Sber drops such a device silently.",
  "validation_issue.obligatory_not_published":
    "Feature “{key}” is obligatory for category “{category}” but carries no value in this publish. Sber drops such a device silently.",
  "validation_issue.partner_meta_too_long":
    "partner_meta takes {size} JSON characters against a limit of {max}. It is the only numeric limit in the whole Sber reference, and a device above it is not accepted.",
  "validation_issue.state_not_declared":
    "Feature “{key}” is published but not advertised in the device's config features list. Sber requires every supported feature to be described in the model, or the value is discarded.",
  "validation_issue.state_unknown_enum":
    "Feature “{key}” sent value “{sent}”, which is not one of the values Sber documents for it. The cloud cannot route a value it does not know.",
  "validation_issue.type_mismatch": "Feature “{key}” sent as {actual}, spec requires {expected}.",
  "validation_issue.value_foreign_fields":
    "Feature “{key}”: the {declared} value carries foreign fields {foreign} next to the expected “{own_field}”. Extra fields are a known cause of silent rejection.",
  "validation_issue.value_integer_must_be_string":
    "Feature “{key}”: field “integer_value” is sent as a JSON {actual}, but Sber requires the integer as a string (“42”, not 42). Such a state reaches the cloud and is silently lost.",
  "validation_issue.value_missing_type":
    "Feature “{key}”: the value has no “type” field, so Sber cannot tell how to read it and drops the state.",
  "validation_issue.value_not_an_object":
    "Feature “{key}”: the value is not an object but a JSON {json_type}, so Sber cannot read it.",
  "validation_issue.value_out_of_range":
    "Feature “{key}” sent {sent}, outside the documented range {min}…{max}. Sber may clip or drop it.",
  "validation_issue.value_unknown_type":
    "Feature “{key}”: value type “{declared}” is unknown to Sber. Only {allowed} are defined.",
  "validation_issue.value_wrong_json_type":
    "Feature “{key}”: field “{field}” is sent as a JSON {actual}, but Sber documents it as {expected}. Such a state reaches the cloud and is silently lost.",

  // --- traces ---
  "traces.col_event": "Event",
  "traces.col_entity": "Entity",
  "traces.col_detail": "Detail",

  // --- row ---
  "row.link": "Link entities",
  "row.link_entity": "Link entities for {entity}",
  "row.sync": "Sync to Sber",
  "row.sync_entity": "Sync {entity} to Sber",
  "row.remove": "Remove entity",
  "row.remove_entity": "Remove {entity}",

  // --- json ---
  "json.no_data": "No data",

  // --- diagnose ---
  "diagnose.copy_report": "Copy report",
  "diagnose.action": "Action:",

  // --- table ---
  "table.empty": "No exposed devices found",

  // --- link ---
  "link.loading": "Loading…",
  "link.none": "No compatible entities found.",
  "link.same_device": "Same device",
  "link.close": "Close dialog",
  "link.roles_unfilled":
    "Nothing to link for: {roles} — no matching entity was found in Home Assistant.",

  // --- settings ---
  "settings.loading": "Loading settings…",

  // --- wizard ---
  "wizard.close": "Close wizard",
  "wizard.loading_categories": "Loading categories…",
  "wizard.no_categories": "No categories available",
  "wizard.loading_devices": "Loading devices…",

  // --- panel ---
  "panel.sections": "Sber MQTT Bridge sections",
  // --- wizard ---
  "wizard.no_devices": "No HA devices match this category",
  "wizard.native_sensors": "Native sensors",
  "wizard.other_sensors": "Compatible sensors from other devices",
  "wizard.not_usable": "Not usable",
  "wizard.summary_category": "Sber category:",
  "wizard.summary_linked": "Linked sensors:",
  "wizard.slug_hint": "Transliterated slug for the Sber protocol",
  "wizard.energy_sensors": "Energy monitoring",
  "wizard.energy_hint":
    "Sber shows power, voltage and current for this device. The ticked readings will be sent — untick one to leave it out.",
  "wizard.energy_unlinked":
    "These readings were found, but none is ticked: tick the ones Sber should show.",
  "wizard.energy_none":
    "No power, voltage or current sensor was found next to this device, so Sber will show no energy readings. Link one later from the device row.",
  "wizard.energy_none_orphan":
    "This entity has no Home Assistant device, so there is nowhere to look for a power, voltage or current sensor — Sber will show no energy readings.",
  "wizard.energy_missing": "Not found: {roles}. Sber will show no such reading.",
  "wizard.summary_energy": "Energy monitoring:",
  "wizard.summary_energy_none": "none selected",

  // --- link roles (devices/base_entity.py::LinkableRole) ---
  "link_role.battery": "Battery",
  "link_role.battery_low": "Low battery",
  "link_role.signal_strength": "Signal strength",
  "link_role.temperature": "Temperature",
  "link_role.humidity": "Humidity",
  "link_role.co2": "CO2",
  "link_role.pm1": "PM1",
  "link_role.pm25": "PM2.5",
  "link_role.pm10": "PM10",
  "link_role.tvoc": "TVOC",
  "link_role.hcho": "Formaldehyde",
  "link_role.open_state": "Open state",
  "link_role.power": "Power",
  "link_role.voltage": "Voltage",
  "link_role.current": "Current",

  // --- detail_dialog ---
  "detail_dialog.entity_id": "Entity ID",
  "detail_dialog.category": "Sber Category",
  "detail_dialog.status": "Status",
  "detail_dialog.features": "Features",
  "detail_dialog.no_states": "No state data",
  "detail_dialog.col_key": "Key",
  "detail_dialog.col_type": "Type",
  "detail_dialog.col_value": "Value",
  "detail_dialog.col_attribute": "Attribute",
  "detail_dialog.model_id": "Model ID",
  "detail_dialog.manufacturer": "Manufacturer",
  "detail_dialog.model": "Model",
  "detail_dialog.allowed_values": "Allowed Values",
  "detail_dialog.dependencies": "Dependencies",
  "detail_dialog.device_name": "Device Name",
  // --- detail_dialog ---
  "detail_dialog.edit_name": "Name",
  "detail_dialog.edit_room": "Room",
  "detail_dialog.edit_home": "Home",
  "detail_dialog.room_placeholder": "Room name",
  "detail_dialog.home_placeholder": "Home name",
  "detail_dialog.save_republish": "Save & Re-publish",
  // --- toolbar ---
  "toolbar.clear_all_title": "Remove ALL exposed entities?",
  "toolbar.clear_all_warning": "Every device disappears from Sber. This cannot be undone.",
  "toolbar.cancel": "Cancel",
  "toolbar.clear_all": "Clear all",
  "toolbar.import_invalid_json": "Import failed: file is not valid JSON",
  "toolbar.add_device": "Add device",
  "toolbar.maintenance": "Maintenance",
  "toolbar.auto_link": "Auto-link sensors",
  "toolbar.publishing": "Publishing…",
  "toolbar.republish": "Re-publish",
  "toolbar.refresh": "Refresh",
  "toolbar.export": "Export",
  "toolbar.import": "Import",
  "toolbar.device_counter": "{total} devices ({known} known to Sber)",

  // --- connection phases (status card + toolbar) ---
  "phase.starting.label": "Starting…",
  "phase.starting.desc": "Waiting for Home Assistant to finish loading",
  "phase.connecting.label": "Connecting…",
  "phase.connecting.desc": "Establishing MQTT connection to Sber cloud",
  "phase.awaiting_ack.label": "Awaiting Sber…",
  "phase.awaiting_ack.desc": "Connected, config published — waiting for Sber to acknowledge",
  "phase.ready.label": "Ready",
  "phase.ready.desc": "Fully operational — accepting commands from Sber",
  "phase.disconnected.label": "Disconnected",
  "phase.disconnected.desc": "Not connected to Sber MQTT broker",

  // --- device detail dialog ---
  "detail_dialog.loading": "Loading…",
  "detail_dialog.close": "Close details",
  "detail_dialog.override": "Sber Override",
  "detail_dialog.overview": "Overview",
  "detail_dialog.sber_states": "Sber States (current)",
  "detail_dialog.linked_entities": "Linked Entities",
  "detail_dialog.model_config": "Sber Model Config",
  "detail_dialog.ha_attributes": "HA Attributes",
  "detail_dialog.device_registry": "HA Device Registry",
  "detail_dialog.saved": "Saved",
  "detail_dialog.error": "Error",
};

/** Language the in-flight/settled {@link _pending} load was started for. */
let _language = null;

/** Cached load promise, one per language. */
let _pending = null;

/**
 * Substitute `{name}` placeholders into a fallback string.
 *
 * Mirrors what `hass.localize` does for the translated variant, so a
 * string reads the same whether it came from the backend or from
 * {@link EN_FALLBACK}.
 *
 * @param {string} text - Template text.
 * @param {object} [placeholders] - Values keyed by placeholder name.
 * @returns {string} Text with placeholders replaced.
 */
function _fill(text, placeholders) {
  if (!placeholders) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) =>
    placeholders[name] === undefined ? match : String(placeholders[name]),
  );
}

/**
 * Translate a panel string.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {string} key - Dotted key below `config_panel.`, e.g.
 *   `"gate_options.title"`.
 * @param {object} [placeholders] - Values for `{name}` placeholders.
 * @returns {string} Localized text, English fallback, or the key itself
 *   when the key is unknown (loud enough to notice, quiet enough to ship).
 */
export function t(hass, key, placeholders) {
  const translated = hass?.localize?.(
    `component.${DOMAIN}.${CATEGORY}.${key}`,
    placeholders,
  );
  if (translated) return translated;
  const fallback = EN_FALLBACK[key];
  return fallback === undefined ? key : _fill(fallback, placeholders);
}

/**
 * Localized meaning of a Sber error code.
 *
 * Sber publishes five error codes and a one-line meaning for each
 * (`c2c/error`, `c2c/common-error`), and those meanings are the only
 * thing that separates "your credentials are wrong" (403) from "come
 * back later" (503).  The panel used to show the bare number.
 *
 * A code outside the documented five is reported as such rather than
 * guessed at: Sber may add one, and a wrong explanation is worse than
 * an honest "not in the documentation".
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {number|string|null|undefined} code - Code from the error
 *   packet.
 * @returns {string} The meaning, or `""` when there is no code at all.
 */
export function sberErrorText(hass, code) {
  if (code === null || code === undefined || code === "") return "";
  const key = `sber_error.${code}`;
  const text = t(hass, key);
  return text === key ? t(hass, "sber_error.unknown") : text;
}

/**
 * Fetch the `config_panel` strings for the current language, once.
 *
 * Home Assistant only refetches categories that were loaded *without* an
 * integration filter when the user switches language, so the language is
 * tracked here and the fetch is repeated when it changes.
 *
 * Loading new resources replaces `hass` (and with it `hass.localize`),
 * which re-renders every component that holds it — so a re-render is only
 * forced for the caller that actually started a fetch, and only to cover
 * the case where the panel is not re-fed a fresh `hass`.
 *
 * Failures are swallowed on purpose: an untranslated panel beats a broken
 * one, and {@link t} already has English for every key.
 *
 * @param {object} hass - Home Assistant object handed to the panel.
 * @param {{requestUpdate?: () => void}} [element] - Component to re-render
 *   once the fetch completes.
 * @returns {Promise<void>} Resolves when the strings are available.
 */
export function ensurePanelTranslations(hass, element) {
  const language = hass?.language || "en";
  if (_pending && _language === language) return _pending;

  _language = language;
  const load = hass?.loadBackendTranslation;
  let fetching;
  try {
    /* `try` covers a synchronous throw as well as a rejection: this runs
     * from `updated()`, where an escaping error kills the render pass. */
    fetching =
      typeof load === "function"
        ? Promise.resolve(load.call(hass, CATEGORY, DOMAIN))
        : Promise.resolve(undefined);
  } catch {
    fetching = Promise.resolve(undefined);
  }
  _pending = fetching.then(
    () => undefined,
    () => undefined,
  );

  if (element?.requestUpdate) {
    _pending.then(() => element.requestUpdate());
  }
  return _pending;
}

/**
 * Drop the cached load state.
 *
 * Only meant for tests — production code has no reason to re-fetch.
 *
 * @returns {void}
 */
export function resetPanelTranslations() {
  _language = null;
  _pending = null;
}
