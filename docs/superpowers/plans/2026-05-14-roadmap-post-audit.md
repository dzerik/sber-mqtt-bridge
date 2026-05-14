# Post-Audit Roadmap (Rounds 2–7)

Master TOC for all refactoring rounds derived from the 2026-05-14 architecture audit. Each round is shippable as a standalone version. Round 1 = v1.38.2 (P0 security/correctness, already merged).

## Rounds

| Round | Scope | Version | Plan file | Status |
|---|---|---|---|---|
| 1 | P0 hardening (security + LSP + race + DevTools follow-up) | v1.38.2 | `2026-05-14-v1.38.2-p0-hardening.md` | ✅ shipped |
| 2 | `SberPublisher` extraction (publish_*/devtools collectors → new module) | v1.38.3 | `2026-05-14-v1.38.3-publisher-extraction.md` | ✅ shipped |
| 3a | `RedefinitionsStore` extraction (debounced persist) | v1.38.4 | `2026-05-14-v1.38.4-redefinitions-store.md` | ✅ shipped |
| 3b | `DevToolsHub` extraction (collector aggregate) | v1.38.5 | `2026-05-14-v1.38.5-devtools-hub.md` | ✅ shipped |
| 4 | `BridgeCommandContext` narrowed to expose concrete collaborators | v1.38.6 | inline (no separate plan file) | ✅ shipped |
| 5 | CC reduction: `handle_command`, `ws_add_ha_device`, `ws_device_detail`, `climate.to_sber_current_state`, `tv.process_cmd` | v1.39.0 | inline (no separate plan file) | ✅ shipped |
| 6 | `devices/` mixins: `TamperAlarmMuteMixin`, `BatteryAndSignalLinkMixin`, `FanSpeedMixin` (process_cmd dispatch deferred — only TV was D-rated, done in Round 5) | v1.39.1 | inline (no separate plan file) | ✅ shipped |
| 7 | Minor leftovers (vulture findings, `vol.Invalid` in catch tuple, silent `json.JSONDecodeError` swallows, `@requires_bridge` decorator) | v1.39.2 | inline (no separate plan file) | ✅ shipped (`@requires_bridge` deferred — scope too large for final round) |
| 8 | `process_cmd` dispatch lifted into `BaseEntity` (closes the deferred unification from Round 6) | v1.39.3 | inline (no separate plan file) | ✅ shipped |
| 9 | Final `process_cmd` unification cleanup (drop 7 redundant overrides, 15/15 classes now use the canonical pattern) | v1.39.4 | inline | ✅ shipped |

## Dependencies

- Round 2 must precede Round 3 (DevToolsHub extracts collectors that move to Publisher first).
- Round 4 should follow Rounds 2+3 — the Protocol split is cleanest once concrete classes exist.
- Round 5 is independent of 2-4 — can run in parallel session if desired.
- Round 6 is independent of all others.
- Round 7 is independent.

## Conventions

- **One round = one patch/minor version bump.**
- **Each round = standalone plan file** in `docs/superpowers/plans/`.
- **Each round = subagent-driven execution** with two-stage review per task.
- **Lint cleanup** (ruff format drift, import sorting): separate commit per round, not bundled with version bump.
- **No external API changes** in Rounds 2-7 — purely internal refactors and quality-of-life.

## Tracking

Update this file's status column after each round ships.

## Skipped/Deferred

- **Adding new device categories**: out of scope, see `CLAUDE.md` for that workflow.
- **WebSocket panel UX redesign**: not in audit scope; tracked separately if/when needed.
- **HA integration migration to Quality Scale Silver**: separate effort, see `docs/HACS_SILVER_REQUIREMENTS.md`.
