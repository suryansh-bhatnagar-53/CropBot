"""The farm context (schema "Answering a question"): built at question time, never stored in the graph."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from kg.schema.vocab import Rating


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Soil(Model):
    N: Rating | None = None
    P: Rating | None = None
    K: Rating | None = None
    Zn: Rating | None = None              # schema v1.3: soil_Zn_rating ("zinc deficient soils" = low)
    pH: float | None = None


class Forecast(Model):
    rain_mm_24h: float | None = None
    rain_days_3d: float | None = None
    tmax_c: float | None = None


class FarmContext(Model):
    """Every field may be missing; a missing value is UNKNOWN, never a default."""
    crop: str
    state: str | None = None
    district: str | None = None
    zones: list[str] = []                 # the farmer's zones in their own state's scheme
    month: int | None = None
    season: str | None = None
    local_seasons: list[str] = []
    variety: str | None = None
    duration_group: Literal["short", "medium", "long"] | None = None
    sowing_date: date | None = None
    das: float | None = None
    stage: str | None = None
    systems: list[str] = []
    soil_types: list[str] = []
    soil: Soil = Soil()
    forecast: Forecast = Forecast()
    purpose: str | None = None            # purpose:grain | purpose:seed | ...
    storage_months: float | None = None
    observations: dict[str, float] = {}   # pest_count, spider_count_per_hill, grain_moisture_pct
    pest: str | None = None               # the pest a threshold question is about
    # schema v1.4 endemic_area: the farmer's answer per pest or disease ("disease:tungro": True); a concept
    # missing here is UNKNOWN, never assumed either way
    endemic: dict[str, bool] = {}
    # schema v1.5 quality_check: what is sold, its grade, the measured value of each quality parameter
    # ({"moisture": 18}; moisture falls back to observations["grain_moisture_pct"]) and whether each
    # substance a specification requires to be absent was found ({"weevils": False})
    commodity_form: Literal["paddy", "raw_rice", "parboiled_rice"] | None = None
    grade: Literal["grade_a", "common"] | None = None
    quality: dict[str, float] = {}
    present: dict[str, bool] = {}

    def quality_value(self, parameter: str):
        if parameter == "moisture" and "moisture" not in self.quality:
            return self.observations.get("grain_moisture_pct")
        return self.quality.get(parameter)

    def region_ids(self) -> list[str]:
        """District + own-state zones + state + country: the regions a fact may be scoped to."""
        return [r for r in [self.district, *self.zones, self.state] if r] + ["country:in"]

    def value(self, variable: str):
        """A condition variable's value, or None when the farmer has not given it."""
        if variable.startswith("forecast_"):
            return getattr(self.forecast, variable.removeprefix("forecast_"), None)
        if variable == "tmax_c":
            return self.forecast.tmax_c
        if variable.startswith("soil_") and variable.endswith("_rating"):
            r = getattr(self.soil, variable.split("_")[1], None)
            return r.value if r is not None else None
        if variable == "soil_pH":
            return self.soil.pH
        if variable == "purpose":
            return self.purpose.split(":", 1)[1] if self.purpose else None
        if variable in ("sowing_date", "das", "variety", "storage_months"):
            return getattr(self, variable)
        return self.observations.get(variable)
