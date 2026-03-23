"""Linear value converter between Home Assistant and Sber numeric ranges."""

from __future__ import annotations


class LinearConverter:
    """Bidirectional linear interpolation converter between HA and Sber value ranges.

    Converts numeric values between two configurable ranges using linear
    interpolation. Supports optional range inversion (reversed mapping).

    Default ranges:
    - Sber side: 0-1000
    - HA side: 0-255

    Attributes:
        sber_side_min: Minimum value on the Sber side.
        sber_side_max: Maximum value on the Sber side.
        ha_side_min: Minimum value on the HA side.
        ha_side_max: Maximum value on the HA side.
        is_reversed: Whether the Sber range is inverted relative to the HA range.
    """

    sber_side_min: int = 0
    sber_side_max: int = 1000
    ha_side_min: int = 0
    ha_side_max: int = 255

    is_reversed: bool = False  # Нужна ли инверсия интервала sber относительно интервала ha

    @classmethod
    def create(cls) -> LinearConverter:
        """Create a new LinearConverter instance with default ranges.

        Returns:
            A new LinearConverter with default Sber (0-1000) and HA (0-255) ranges.
        """
        return LinearConverter()

    def set_reversed(self, is_reversed: bool) -> None:
        """Set whether the conversion should reverse the direction.

        When reversed, the maximum Sber value maps to the minimum HA value
        and vice versa.

        Args:
            is_reversed: True to enable reversed mapping.
        """
        self.is_reversed = is_reversed

    def set_sber_limits(self, sber_side_min: int, sber_side_max: int) -> None:
        """Set the Sber-side value range.

        Args:
            sber_side_min: Minimum Sber value (must be less than max).
            sber_side_max: Maximum Sber value.

        Raises:
            ValueError: If sber_side_min >= sber_side_max.
        """
        if sber_side_min < sber_side_max:
            self.sber_side_min = sber_side_min
            self.sber_side_max = sber_side_max
        else:
            raise ValueError("sber_side_min must be less than sber_side_max")

    def set_ha_limits(self, ha_side_min: int, ha_side_max: int) -> None:
        """Set the HA-side value range.

        Args:
            ha_side_min: Minimum HA value (must be less than max).
            ha_side_max: Maximum HA value.

        Raises:
            ValueError: If ha_side_min >= ha_side_max.
        """
        if ha_side_min < ha_side_max:
            self.ha_side_min = ha_side_min
            self.ha_side_max = ha_side_max
        else:
            raise ValueError("ha_side_min must be less than ha_side_max")

    def sber_to_ha(self, sber_value: int | float) -> int:
        """Convert a Sber-side value to the corresponding HA-side value.

        Values outside the Sber range are clamped to HA min/max.

        Args:
            sber_value: Numeric value in Sber range.

        Returns:
            Rounded integer value in HA range.
        """
        if sber_value < self.sber_side_min:
            return self.ha_side_min
        if sber_value > self.sber_side_max:
            return self.ha_side_max
        sber_delta = (sber_value - self.sber_side_min) if not self.is_reversed else (self.sber_side_max - sber_value)
        return round(
            sber_delta * (self.ha_side_max - self.ha_side_min) / (self.sber_side_max - self.sber_side_min)
            + self.ha_side_min
        )

    def ha_to_sber(self, ha_value: int | float) -> int:
        """Convert an HA-side value to the corresponding Sber-side value.

        Values outside the HA range are clamped to Sber min/max.

        Args:
            ha_value: Numeric value in HA range.

        Returns:
            Rounded integer value in Sber range.
        """
        if ha_value < self.ha_side_min:
            return self.sber_side_min
        if ha_value > self.ha_side_max:
            return self.sber_side_max
        ha_delta = (ha_value - self.ha_side_min) if not self.is_reversed else (self.ha_side_max - ha_value)
        return round(
            ha_delta * (self.sber_side_max - self.sber_side_min) / (self.ha_side_max - self.ha_side_min)
            + self.sber_side_min
        )
