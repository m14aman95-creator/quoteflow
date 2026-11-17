"""The contract between the language model and the application.

The model may ONLY return this shape. There is deliberately no price/amount/total/discount field anywhere,
and unknown keys are rejected (extra='forbid'), so a model that tries to add a price fails validation."""
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

Source = Literal["customer", "ai", "unknown"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class FieldValue(_Strict):
    value: Optional[str] = Field(default=None, max_length=300)
    source: Source = "unknown"          # customer = said by the customer, ai = inferred by the AI


class RawItem(_Strict):
    customer_words: str = Field(default="", max_length=200)     # what the customer wrote
    quantity: Optional[float] = Field(default=None, ge=0, le=100000)
    quantity_source: Source = "unknown"
    unit_hint: Optional[str] = Field(default=None, max_length=40)
    matched_service_id: Optional[int] = None                    # must be an id from the supplied catalogue
    description_en: str = Field(default="", max_length=400)     # professional wording, NO prices
    description_ar: str = Field(default="", max_length=400)
    uncertain: bool = False


class RawQuestion(_Strict):
    field: str = Field(default="other", max_length=40)
    question_en: str = Field(max_length=300)
    question_ar: str = Field(default="", max_length=300)


class RawExtraction(_Strict):
    language: Literal["en", "ar", "mixed"] = "en"
    customer_name: FieldValue = FieldValue()
    phone: FieldValue = FieldValue()
    location: FieldValue = FieldValue()
    requested_date: FieldValue = FieldValue()
    service_summary: FieldValue = FieldValue()
    special_requirements: List[FieldValue] = Field(default_factory=list, max_length=10)
    items: List[RawItem] = Field(default_factory=list, max_length=15)
    uncertainty_flags: List[str] = Field(default_factory=list, max_length=15)
    clarification_questions: List[RawQuestion] = Field(default_factory=list, max_length=12)
    injection_suspected: bool = False

    @field_validator("uncertainty_flags")
    @classmethod
    def _flag_len(cls, v):
        return [s[:200] for s in v]
