"""Structured input schemas shared by the external LangChain tools."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=200, description="Disease or health-topic query")


class GeneticsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(
        min_length=1,
        max_length=200,
        description="Gene, genetic condition, inheritance, chromosome, or genetics-topic query",
    )


DrugLabelSection = Literal[
    "indications",
    "dosage",
    "contraindications",
    "warnings",
    "adverse_reactions",
    "drug_interactions",
    "pregnancy",
    "clinical_pharmacology",
    "all",
]


class DrugLabelInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    drug_name: str = Field(min_length=1, max_length=120, description="Generic or brand drug name")
    section: DrugLabelSection = Field(
        default="all", description="The official label section to retrieve"
    )


class DrugSafetyInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    drug_name: str = Field(min_length=1, max_length=120, description="Generic or brand drug name")
    limit: int = Field(default=10, ge=1, le=25, description="Maximum reaction aggregates")
