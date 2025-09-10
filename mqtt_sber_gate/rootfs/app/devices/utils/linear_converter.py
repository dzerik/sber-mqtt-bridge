class LinearConverter:
    sber_side_min: int = 0
    sber_side_max: int = 1000
    ha_side_min: int = 0
    ha_side_max: int = 255

    is_reversed: bool = False # Нужна ли инверсия интервала sber относительно интервала ha

    @classmethod
    def create(cls):
        return LinearConverter()

    def set_reversed(self, is_reversed):
        self.is_reversed = is_reversed
   
    def set_sber_limits(self, sber_side_min, sber_side_max):
        if sber_side_min < sber_side_max:
            self.sber_side_min = sber_side_min
            self.sber_side_max = sber_side_max
        else:
            raise ValueError("sber_side_min must be less than sber_side_max")
        
    def set_ha_limits(self, ha_side_min, ha_side_max):
        if ha_side_min < ha_side_max:
            self.ha_side_min = ha_side_min
            self.ha_side_max = ha_side_max
        else:
            raise ValueError("ha_side_min must be less than ha_side_max")
    
    def sber_to_ha(self, sber_value):
        if sber_value < self.sber_side_min:
            return self.ha_side_min
        elif sber_value > self.sber_side_max:
            return self.ha_side_max
        else:
            sber_delta = (sber_value - self.sber_side_min) if not self.is_reversed else (self.sber_side_max - sber_value)
            return round(sber_delta * (self.ha_side_max - self.ha_side_min) / (self.sber_side_max - self.sber_side_min) + self.ha_side_min)
        
    def ha_to_sber(self, ha_value):
        if ha_value < self.ha_side_min:
            return self.sber_side_min
        elif ha_value > self.ha_side_max:
            return self.sber_side_max
        else:
            ha_delta = (ha_value - self.ha_side_min) if not self.is_reversed else (self.ha_side_max - ha_value)
            return round(ha_delta * (self.sber_side_max - self.sber_side_min) / (self.ha_side_max - self.ha_side_min) + self.sber_side_min)
