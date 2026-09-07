"""AUTO-GENERATED from tests/hacs/__snapshots__/sber_full_spec.json.

DO NOT EDIT BY HAND.  Regenerate with:

    python tools/codegen.py

Source: https://developers.sber.ru/docs/ru/smarthome/c2c
Spec generated at: 2026-09-07T15:07:37.367121+00:00
"""

from __future__ import annotations

MODEL_REQUIRED_FIELDS: frozenset[str] = frozenset({"category", "features", "id", "manufacturer", "model"})
"""Fields the ``model`` structure marks ✔︎ obligatory.

A model missing one of these is rejected whole, taking every device
that references it along."""


MODEL_FIELDS: frozenset[str] = frozenset(
    {"allowed_values", "category", "description", "features", "hw_version", "id", "manufacturer", "model", "sw_version"}
)
"""Every field the ``model`` structure documents, required or not.

Note what is *not* here: ``dependencies``.  The bridge sends it, no Sber
page mentions it, and our own models are ``extra="forbid"`` — if the
cloud reasons the same way, that field is a silent rejection waiting to
happen."""


DEVICE_REQUIRED_FIELDS: frozenset[str] = frozenset({"default_name", "id", "model", "model_id", "name"})
"""Fields the ``device`` structure marks ✔︎ obligatory.

Read this one with care: the page marks **both** ``model_id`` and
``model`` obligatory while the ``model`` row itself says "указывается,
только если не задан model_id".  Both cannot hold, so this set is not
usable as a plain "all of these must be present" check — the bridge
sends an inline ``model`` and no ``model_id``, matching the examples on
all 29 category pages."""


DEVICE_FIELDS: frozenset[str] = frozenset(
    {
        "default_name",
        "groups",
        "home",
        "hw_version",
        "id",
        "model",
        "model_id",
        "name",
        "parent_id",
        "partner_meta",
        "room",
        "sw_version",
    }
)
"""Every field the ``device`` structure documents.

``nicknames``, which the bridge sends, is absent here — same exposure as
``dependencies`` on the model side."""


STATE_REQUIRED_FIELDS: frozenset[str] = frozenset({"key", "value"})
"""Fields of one ``state`` entry: ``key`` and ``value``, both required."""


ALLOWED_VALUES_CONDITIONAL_FIELDS: frozenset[str] = frozenset({"enum_values", "float_values", "integer_values"})
"""The ✔︎* rows of ``allowed_values``: exactly one of these per entry.

Which one is decided by the entry's ``type`` — ``integer_values`` for
INTEGER, ``float_values`` for FLOAT, ``enum_values`` for ENUM."""


PARTNER_META_MAX_CHARS: int | None = 1024
"""Maximum length of ``partner_meta`` in its JSON form.

The only numeric limit in the entire C2C reference: Sber writes
"Максимально допустимое количество символов в JSON-представлении
объекта partner_meta — 1024".  ``None`` means the sentence stopped
parsing, which is a scraper problem, not permission to send
more."""


SBER_ERROR_CODES: dict[int, str] = {
    400: "ошибка валидации запроса",
    401: "ошибка авторизации",
    403: "ошибка проверки токена",
    500: "внутренняя ошибка системы",
    503: "сервер недоступен",
}
"""Error codes Sber may return, with its own wording.

401 and 403 mean "the credentials are wrong"; 400 means "the
payload is wrong"; 500/503 mean "try later".  The bridge
currently logs the raw error body as one truncated string, so
these three very different situations look identical to the
user."""
