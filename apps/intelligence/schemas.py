from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class NotStated(str, Enum):
    """Explicit sentinel: the description exists but does not mention this field."""
    NOT_STATED = "not_stated"


class Seniority(str, Enum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    PRINCIPAL = "principal"
    DIRECTOR = "director"
    NOT_STATED = "not_stated"


class RemoteStatus(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on_site"
    NOT_STATED = "not_stated"


class ContractType(str, Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACTOR = "contractor"
    FREELANCE = "freelance"
    NOT_STATED = "not_stated"


class JobExtractionResult(BaseModel):
    """
    Structured output from the LLM skill-extraction step.

    None on any field means the model failed to produce a value (parse error /
    field omitted entirely).  NOT_STATED means the model read the description
    and confirmed the information is not present.
    """

    required_skills: List[str] = Field(
        default_factory=list,
        description="Skills explicitly required by the job description.",
    )
    nice_to_have_skills: List[str] = Field(
        default_factory=list,
        description="Skills listed as preferred or advantageous but not required.",
    )
    seniority: Optional[Seniority] = None
    years_required: Optional[int | NotStated] = None
    remote_status: Optional[RemoteStatus] = None
    contract_type: Optional[ContractType] = None

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("required_skills", "nice_to_have_skills", mode="before")
    @classmethod
    def clean_skill_list(cls, v: list) -> list:
        """
        Protects against: items that are empty strings or pure whitespace
        sneaking through (e.g. ["Python", "", " "]).
        """
        if not isinstance(v, list):
            return v
        cleaned = [s.strip() for s in v if isinstance(s, str) and s.strip()]
        return cleaned

    @field_validator("years_required", mode="before")
    @classmethod
    def cap_years(cls, v):
        """
        Protects against: hallucinated values like 2024 (a year mistaken for
        years of experience) or any absurd number above 30.
        """
        if isinstance(v, int) and v > 30:
            raise ValueError(f"years_required {v} is implausibly large (max 30).")
        return v

    @model_validator(mode="after")
    def warn_empty_skills(self) -> "JobExtractionResult":
        """
        Protects against: the model silently returning an empty required_skills
        list.  This is not a hard failure — non-technical jobs legitimately have
        no skills — but callers can inspect this flag to decide whether to retry.
        """
        self._empty_skills_warning = (
            not self.required_skills and not self.nice_to_have_skills
        )
        return self
