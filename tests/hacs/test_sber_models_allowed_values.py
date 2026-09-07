"""Словари ``allowed_values`` сверяются со справочником Sber.

До 1.49.x гейт спрашивал у ``allowed_values`` только одно: «все ли ключи
есть в ``features``».  Сами значения не проверял никто, поэтому телевизор
мог объявить источники ``["HDMI 1", "Станция"]`` вместо канонических
``["hdmi1", "tv"]`` и спокойно уехать в облако.  Цена ошибки высокая:
приложение рисует ровно то, что объявлено, и той же строкой присылает
команду обратно — то есть каждая выдуманная строка это заведомо
неработающая кнопка, а Сбер вправе отвергнуть всё устройство целиком.
Именно этот класс дефектов чинили руками в 1.49.0.
"""

from __future__ import annotations

from custom_components.sber_mqtt_bridge.sber_models import validate_device


def _tv_device(source_values: list[str]) -> dict:
    """Собрать дескриптор телевизора с заданным списком источников."""
    return {
        "id": "media_player.tv",
        "name": "Телевизор",
        "room": "Зал",
        "model": {
            "id": "Mdl_tv_deadbeef",
            "category": "tv",
            "features": ["online", "on_off", "source"],
            "allowed_values": {"source": {"type": "ENUM", "enum_values": {"values": source_values}}},
        },
    }


class TestAllowedEnumValuesVocabulary:
    """Значения ENUM должны быть из словаря самой функции."""

    def test_invented_source_values_are_rejected(self) -> None:
        """Выдуманные источники не должны проходить гейт.

        Если тест упадёт — устройство с нерабочими кнопками снова уедет
        в облако, и пользователь будет искать причину в приложении Сбера,
        а не в списке источников.
        """
        valid, error = validate_device(_tv_device(["HDMI 1", "Станция", "totally_made_up"]))

        assert valid is False
        assert "HDMI 1" in error
        assert "hdmi1" in error, "в тексте ошибки должно быть видно, чего Сбер ждёт"

    def test_canonical_source_values_pass(self) -> None:
        """Канонические значения Sber проходят без замечаний.

        Если тест упадёт — гейт начнёт вырезать из конфига совершенно
        правильные телевизоры, и они просто исчезнут из приложения.
        """
        valid, error = validate_device(_tv_device(["hdmi1", "hdmi2", "tv"]))

        assert (valid, error) == (True, "")

    def test_one_wrong_value_is_enough(self) -> None:
        """Проверяется каждое значение, а не только первое."""
        valid, _ = validate_device(_tv_device(["hdmi1", "tv", "netflix"]))

        assert valid is False

    def test_feature_without_documented_vocabulary_is_left_alone(self) -> None:
        """Нет словаря — нет проверки: «неизвестно» не значит «запрещено».

        ``unlock`` — ENUM без опубликованного перечня значений.  Если тест
        упадёт, мост начнёт браковать функции просто за то, что Сбер их
        не расписал.
        """
        device = {
            "id": "lock.door",
            "name": "Дверь",
            "room": "Прихожая",
            "model": {
                "id": "Mdl_intercom_deadbeef",
                "category": "intercom",
                "features": ["online", "unlock"],
                "allowed_values": {"unlock": {"type": "ENUM", "enum_values": {"values": ["что_угодно"]}}},
            },
        }

        assert validate_device(device) == (True, "")

    def test_numeric_limits_are_not_touched(self) -> None:
        """У INTEGER нет словаря значений — проверка его не касается."""
        device = {
            "id": "light.lamp",
            "name": "Лампа",
            "room": "Зал",
            "model": {
                "id": "Mdl_light_deadbeef",
                "category": "light",
                "features": ["online", "on_off", "light_brightness"],
                "allowed_values": {
                    "light_brightness": {
                        "type": "INTEGER",
                        "integer_values": {"min": "100", "max": "1000", "step": "1"},
                    }
                },
            },
        }

        assert validate_device(device) == (True, "")
