"""Modelo no destructivo para combinar planchas A4 en una producción continua."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.planchas.model import A4_HEIGHT_CM, A4_WIDTH_CM


CONTINUOUS_WIDTH_CM = A4_WIDTH_CM
MAX_CONTINUOUS_LENGTH_CM = round(A4_HEIGHT_CM * 4, 1)
PRODUCTION_PROFILES: dict[str, float] = {
    "Hoja": A4_HEIGHT_CM,
    "Doble": round(A4_HEIGHT_CM * 2, 1),
    "Triple": round(A4_HEIGHT_CM * 3, 1),
    "Cuádruple": MAX_CONTINUOUS_LENGTH_CM,
}


@dataclass
class ContinuousSection:
    """Una referencia a una plancha final. Nunca copia los PNG originales."""

    plancha_id: int
    name: str
    final_png_path: str
    project_path: str = ""
    order_id: int | None = None
    client: str = ""
    material: str = ""
    stickers: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ContinuousSection":
        return cls(**data)


@dataclass
class ContinuousProduction:
    """Tira vertical compuesta de secciones A4 físicas de 21 x 29,7 cm."""

    name: str = "Producción continua"
    mode: str = "Hoja"
    width_cm: float = CONTINUOUS_WIDTH_CM
    length_cm: float = A4_HEIGHT_CM
    sections: list[ContinuousSection] = field(default_factory=list)
    production_id: int | None = None

    @classmethod
    def new(cls, mode: str = "Hoja") -> "ContinuousProduction":
        production = cls()
        production.set_profile(mode)
        return production

    @classmethod
    def from_dict(cls, data: dict, production_id: int | None = None) -> "ContinuousProduction":
        sections = [ContinuousSection.from_dict(item) for item in data.get("sections", [])]
        return cls(
            name=str(data.get("name") or "Producción continua"),
            mode=str(data.get("mode") or "Hoja"),
            width_cm=float(data.get("width_cm") or CONTINUOUS_WIDTH_CM),
            length_cm=float(data.get("length_cm") or A4_HEIGHT_CM),
            sections=sections,
            production_id=production_id,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mode": self.mode,
            "width_cm": self.width_cm,
            "length_cm": self.length_cm,
            "sections": [section.to_dict() for section in self.sections],
        }

    @property
    def section_capacity(self) -> int:
        """Cantidad de A4 completas que entran sin alterar la escala física."""
        return max(1, int((self.length_cm + 0.001) // A4_HEIGHT_CM))

    @property
    def total_section_length_cm(self) -> float:
        return round(len(self.sections) * A4_HEIGHT_CM, 1)

    @property
    def remaining_length_cm(self) -> float:
        return round(max(0.0, self.length_cm - self.total_section_length_cm), 1)

    @property
    def total_stickers(self) -> int:
        return sum(max(0, int(section.stickers or 0)) for section in self.sections)

    @property
    def materials(self) -> list[str]:
        return sorted({section.material.strip() for section in self.sections if section.material.strip()}, key=str.casefold)

    @property
    def material_label(self) -> str:
        if not self.materials:
            return "Sin material definido"
        if len(self.materials) == 1:
            return self.materials[0]
        return "Materiales distintos (revisar antes de imprimir)"

    def set_profile(self, mode: str, custom_length_cm: float | None = None) -> None:
        if mode == "Personalizado":
            if custom_length_cm is None:
                raise ValueError("Indicá el largo personalizado.")
            length = float(custom_length_cm)
            if length < A4_HEIGHT_CM or length > MAX_CONTINUOUS_LENGTH_CM:
                raise ValueError(f"El largo debe estar entre {A4_HEIGHT_CM:g} y {MAX_CONTINUOUS_LENGTH_CM:g} cm.")
            self.mode = "Personalizado"
            self.length_cm = round(length, 1)
            return
        if mode not in PRODUCTION_PROFILES:
            raise ValueError("El perfil de producción no es válido.")
        self.mode = mode
        self.length_cm = PRODUCTION_PROFILES[mode]

    def add_section(self, section: ContinuousSection) -> None:
        if len(self.sections) >= self.section_capacity:
            raise ValueError(
                f"El modo {self.mode} admite hasta {self.section_capacity} sección(es) A4 de 29,7 cm."
            )
        if any(item.plancha_id == section.plancha_id for item in self.sections):
            raise ValueError("Esa plancha ya está incluida en la producción.")
        self.sections.append(section)

    def remove_section(self, index: int) -> None:
        if 0 <= index < len(self.sections):
            self.sections.pop(index)

    def move_section(self, index: int, direction: int) -> None:
        target = index + direction
        if 0 <= index < len(self.sections) and 0 <= target < len(self.sections):
            self.sections[index], self.sections[target] = self.sections[target], self.sections[index]

    def validation_errors(self) -> list[str]:
        errors: list[str] = []
        if abs(self.width_cm - CONTINUOUS_WIDTH_CM) > 0.01:
            errors.append("El ancho debe ser de 21 cm.")
        if self.length_cm < A4_HEIGHT_CM or self.length_cm > MAX_CONTINUOUS_LENGTH_CM:
            errors.append(f"El largo debe estar entre {A4_HEIGHT_CM:g} y {MAX_CONTINUOUS_LENGTH_CM:g} cm.")
        if len(self.sections) > self.section_capacity:
            errors.append("Hay más secciones de las que permite el largo seleccionado.")
        if self.total_section_length_cm > self.length_cm + 0.001:
            errors.append("Las secciones superan el largo disponible.")
        return errors
