from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel as PydanticBaseModel, ConfigDict, Field, PositiveFloat, field_validator, model_validator


class BaseModel(PydanticBaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    @field_validator("*", check_fields=False)
    @classmethod
    def timezone_required(cls, value):
        if isinstance(value, datetime) and value.utcoffset() is None:
            raise ValueError("Timestamps must include a timezone")
        return value


class EventType(str, Enum):
    FX_MOVE = "fx_move"
    INTEREST_RATE_CHANGE = "interest_rate_change"
    OIL_MOVE = "oil_move"


class Confidence(str, Enum):
    OBSERVED = "observed"
    SCENARIO = "scenario"
    MIXED = "mixed"


class ImpactDirection(str, Enum):
    COST_INCREASE = "cost_increase"
    COST_DECREASE = "cost_decrease"
    NEUTRAL = "neutral"
    UNQUANTIFIED = "unquantified"


class Provenance(BaseModel):
    provider: str
    source_type: str = "official_or_structured"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    series_id: str | None = None
    source_url: str | None = None
    notes: list[str] = Field(default_factory=list)


class MacroEvent(BaseModel):
    event_id: str
    event_type: EventType
    title: str
    source: str
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    old_value: float
    new_value: float
    unit: str
    change_pct: float | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    affected_currencies: list[str] = Field(default_factory=list)
    jurisdiction: str | None = None
    evidence_url: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    confidence: Confidence = Confidence.OBSERVED
    provenance: Provenance | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_numeric_event(self):
        if self.event_type == EventType.FX_MOVE:
            if not self.base_currency or not self.quote_currency or self.base_currency == self.quote_currency:
                raise ValueError("FX events require two distinct currencies")
        if self.event_type in (EventType.FX_MOVE, EventType.OIL_MOVE):
            if self.old_value <= 0 or self.new_value <= 0:
                raise ValueError("FX rates and oil prices must be positive")
            derived = (self.new_value / self.old_value - 1) * 100
            if self.change_pct is not None and abs(self.change_pct - derived) > 0.0001:
                raise ValueError("change_pct must agree with the structured old/new values")
            self.change_pct = derived
        if self.event_type == EventType.INTEREST_RATE_CHANGE and self.unit != "percent":
            raise ValueError("Policy rates must be expressed in percent, not basis points")
        if self.window_start and self.window_end and self.window_start > self.window_end:
            raise ValueError("Observation window start must not be after its end")
        return self

    @field_validator("base_currency", "quote_currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("affected_currencies")
    @classmethod
    def uppercase_currencies(cls, value: list[str]) -> list[str]:
        return [item.upper() for item in value]

    @field_validator("jurisdiction")
    @classmethod
    def uppercase_jurisdiction(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class MacroHeadline(BaseModel):
    headline_id: str
    title: str
    publisher: str
    published_at: datetime | None = None
    url: str
    jurisdiction: str | None = None
    event_type_hint: EventType | None = None
    tags: list[str] = Field(default_factory=list)
    requires_quantification: bool = True
    source_type: str = "official_rss"


class LifeUnit(BaseModel):
    name: str
    price: PositiveFloat
    currency: str

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class MortgageProfile(BaseModel):
    principal: PositiveFloat
    remaining_years: PositiveFloat
    current_annual_rate_pct: float = Field(ge=0, le=100)
    currency: str | None = None

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class CommuteProfile(BaseModel):
    monthly_fuel_liters: float = Field(ge=0)
    fuel_price_per_liter: PositiveFloat


class LifeProfile(BaseModel):
    home_currency: str
    home_country: str | None = None
    net_monthly_income: float = Field(gt=0)
    monthly_work_hours: float = Field(gt=0)
    travel_budget_home: float | None = Field(default=None, ge=0)
    travel_target_currency: str | None = None
    mortgage: MortgageProfile | None = None
    savings_balance: float | None = Field(default=None, ge=0)
    commute: CommuteProfile | None = None
    life_units: list[LifeUnit] = Field(default_factory=list)

    @field_validator("home_currency", "travel_target_currency")
    @classmethod
    def uppercase_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @field_validator("home_country")
    @classmethod
    def uppercase_country(cls, value: str | None) -> str | None:
        return value.upper() if value else value

    @property
    def net_hourly_income(self) -> float:
        return self.net_monthly_income / self.monthly_work_hours

    @property
    def mortgage_currency(self) -> str | None:
        if not self.mortgage:
            return None
        return self.mortgage.currency or self.home_currency


class ImpactAssumptions(BaseModel):
    interest_rate_pass_through: float = Field(default=0.5, ge=0, le=1)
    oil_to_fuel_pass_through: float = Field(default=0.25, ge=0, le=1)


class TranslateRequest(BaseModel):
    event: MacroEvent
    profile: LifeProfile
    assumptions: ImpactAssumptions = Field(default_factory=ImpactAssumptions)


class LifeUnitConversion(BaseModel):
    unit: str
    quantity: float
    currency: str
    unit_price: float


class CalculationStep(BaseModel):
    label: str
    formula: str
    inputs: dict[str, float | str | None] = Field(default_factory=dict)
    result: float | str | None = None


class ImpactResult(BaseModel):
    event_provenance: Provenance | None = None
    event_observed_at: datetime | None = None
    event_id: str
    headline: str
    direct_effect_home: float | None = None
    home_currency: str
    direction: ImpactDirection = ImpactDirection.UNQUANTIFIED
    impact_horizon: str | None = None
    work_hours_equivalent: float | None = None
    life_units: list[LifeUnitConversion] = Field(default_factory=list)
    explanation: str
    confidence: Confidence
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    calculation_trace: list[CalculationStep] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class ConvertRequest(BaseModel):
    amount: float
    currency: str
    profile: LifeProfile

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class ScenarioInput(BaseModel):
    label: str
    multiplier: float = Field(gt=0)


class ScenarioRequest(BaseModel):
    event: MacroEvent
    profile: LifeProfile
    scenarios: list[ScenarioInput]
    assumptions: ImpactAssumptions = Field(default_factory=ImpactAssumptions)


class EventScore(BaseModel):
    event: MacroEvent
    market_significance: float = Field(ge=0, le=100)
    user_relevance: float = Field(ge=0, le=100)
    priority_score: float = Field(ge=0, le=100)
    significance_method: str
    relevance_reasons: list[str] = Field(default_factory=list)


class RadarRequest(BaseModel):
    events: list[MacroEvent]
    profile: LifeProfile
