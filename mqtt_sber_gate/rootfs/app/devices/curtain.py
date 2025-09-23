from enum import Enum
import logging
import json

from devices.base_entity import BaseEntity

CURTAIN_ENTITY_CATEGORY = "curtain"
logger = logging.getLogger(__name__)

class CurtainEntity(BaseEntity):
    """Класс для управления шторами с поддержкой батареи и статуса открытия"""
    current_position : int = 0  # Текущая позиция (0-100%)
    min_position: int = 0   # Минимальная позиция (0-100%)
    max_position: int = 100  # Максимальная позиция (0-100%)
    battery_level: int = 0  # Уровень заряда (0-100%)
    # _supported_features = []

    def __init__(self, entity_data: dict):
        super().__init__(CURTAIN_ENTITY_CATEGORY, entity_data)
        """
        Инициализация устройства
        
        Args:
            entity_data (dict): Данные из Home Assistant
        """
        self.current_position = 0  # Текущая позиция (0-100%)
        self._battery_level = 100  # Уровень заряда (0-100%)

        # self._supported_features = entity_data.get("supported_features", 0)

    def fill_by_ha_state(self, ha_state):
        """
        Обновление состояния из данных Home Assistant
        
        Args:
            ha_state (dict): Состояние из Home Assistant
        """
        super().fill_by_ha_state(ha_state)
        
        # state_value = ha_state.get("state", "closed")

        # Обновление позиции
        position = ha_state["attributes"].get("current_position")
        if position is not None:
            self.current_position = position
        else:
            self.current_position = 100 if self.state == "opened" else 0

        # # Обновление уровня батареи
        # battery = ha_state["attributes"].get("battery_level")
        # if battery is not None:
        #     self._battery_level = battery
        # logger.debug(f"Обновлено состояние {self.entity_id}: "
        #             f"открыто={self._is_open}, позиция={self._position}%, "
        #             f"батарея={self._battery_level}%")

    def _convert_position(self, ha_position):
        """Конвертация позиции из Home Assistant (0-100) в Sber (0-100)"""
        return int(ha_position)

    def process_cmd(self, cmd_data):
        """
        Обработка команд от Sber
        
        Args:
            cmd_data (dict): Команды в формате Sber
            
        Returns:
            list: Список команд для отправки в Home Assistant
        """
        processing_result = []
        
        for data_item in cmd_data.get("states", []):
            key = data_item.get("key")
            value = data_item.get("value", {})
            
            if key is None:
                continue

            if key == "open_percentage":
                if value.get("type") == "INTEGER":
                    ha_position = int(value.get("integer_value", 0))
                    ha_position = max(0, min(100, ha_position))
                    processing_result.append({
                        "url": {
                            "type": "call_service",
                            "domain": "cover",
                            "service": "set_cover_position",
                            "service_data": {"position": ha_position},
                            "target": {"entity_id": self.entity_id}
                        }
                    })
                    # self.current_position = ha_position

            if key == "cover_position":
                # Команда на установку позиции
                sber_position = value.get("integer_value", 0)
                ha_position = sber_position # 0-100 → 0-100
                
                # Ограничение диапазона
                ha_position = max(0, min(100, ha_position))
                
                # Формирование команды
                processing_result.append({
                    "url": {
                        "type": "call_service",
                        "domain": "cover",
                        "service": "set_cover_position",
                        "service_data": {"position": ha_position},
                        "target": {"entity_id": self.entity_id}
                    }
                })
                # self.current_position = ha_position
                
            elif key == "open_set":
                # Команда открытия/закрытия
                action = value.get("enum_value", None)
                if action is None:
                    continue
                
                if action == "open":
                    processing_result.append({
                        "url": {
                            "type": "call_service",
                            "domain": "cover",
                            "service": "open_cover",
                            "target": {"entity_id": self.entity_id}
                        }
                    })
                    
                elif action == "close":
                    processing_result.append({
                        "url": {
                            "type": "call_service",
                            "domain": "cover",
                            "service": "close_cover",
                            "target": {"entity_id": self.entity_id}
                        }
                    })
                
                elif action == "stop":
                    processing_result.append({
                        "url": {
                            "type": "call_service",
                            "domain": "cover",
                            "service": "stop_cover",
                            "target": {"entity_id": self.entity_id}
                        }
                    })
                    
        return processing_result

    def create_features_list(self):
        """Формирует список возможных функций"""
        features = super().create_features_list() # Когда вызывается 'тот метод?'
        features += [
            "open_percentage"
            , "open_set"
            , "open_state"
            # , "battary_percentage"
            ]
        return features


    def to_sber_state(self):
        return super().to_sber_state()

    def to_sber_current_state(self):
        """Формирование текущего состояния для отправки в Sber"""
        states = []
        if self.state == "unavailable":
            states.append(
                {
                    "key": "online",
                    "value": {
                        "type": "BOOL",
                        "bool_value": False
                    } 
                }
            )
            return
        else:
            states.append(
                {
                    "key": "online",
                    "value": {
                        "type": "BOOL",
                        "bool_value": True
                    }
                }
            )
        
        # # Добавление позиции
        states.append({
            "key": "open_percentage",
            "value": {"type": "INTEGER", "integer_value": self._convert_position(self.current_position)}
        })

        states.append({
            "key": "open_state",
            "value": {
                "type": "ENUM",
                "enum_value": "open" if self.current_position > 0 else "close"
            }
        })
        
        return {self.entity_id: {"states": states}}

    def process_state_change(self, old_state, new_state):
        self.fill_by_ha_state(new_state)

