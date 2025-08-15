# devices/base.py
class Device:
    def __init__(self, device_id):
        self.id = device_id
        self.online = True  # Стандартное состояние

    @abstractmethod
    def process_cmd(self, source, cmd_data):
        """
        Обрабатывает команду от Sber или HA
        Возвращает True, если состояние было изменено
        """
        raise NotImplementedError("Метод process_cmd должен быть переопределен")
