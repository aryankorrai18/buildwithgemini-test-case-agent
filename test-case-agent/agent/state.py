"""Data models and state definitions for Test Case Generator Agent."""

from typing import List, Dict, Any, Literal, Optional
from typing_extensions import TypedDict
from pydantic import BaseModel, Field, field_validator


class TestCase(BaseModel):
    """Structured test case definition."""

    id: str = Field(description="Unique identifier, e.g. TC-001")
    title: str = Field(description="Short descriptive title of the test scenario")
    preconditions: str = Field(
        default="None",
        description="Prerequisites or state needed before running test steps",
    )
    steps: List[str] = Field(
        min_length=1,
        description="Ordered list of steps to execute the test",
    )
    expected_result: str = Field(
        description="Expected behavior or verification outcome"
    )
    type: Literal["positive", "negative", "edge"] = Field(
        description="Test case category"
    )
    requirement_ref: str = Field(
        description="Requirement point or acceptance criterion identifier this covers"
    )

    @field_validator("id")
    @classmethod
    def validate_id_not_empty(cls, v: str) -> str:
        v_str = str(v).strip()
        if not v_str:
            raise ValueError("Test case id cannot be empty")
        return v_str

    @field_validator("title", "expected_result", "requirement_ref")
    @classmethod
    def validate_text_not_empty(cls, v: str) -> str:
        v_str = str(v).strip()
        if not v_str:
            raise ValueError("Field cannot be empty")
        return v_str


class ParsedPointsOutput(BaseModel):
    """Structured output for the requirement parsing stage."""

    requirement_points: List[str] = Field(
        default_factory=list,
        description="Numbered list of distinct requirement rules and acceptance criteria",
    )


class ReviewOutput(BaseModel):
    """Structured output for the test case self-review stage."""

    gaps_found: bool = Field(
        description="Whether there are gaps, missing edge/negative cases, or uncovered points"
    )
    uncovered_points: List[str] = Field(
        default_factory=list,
        description="Requirement points or criteria lacking sufficient test coverage",
    )
    review_notes: str = Field(
        default="",
        description="Constructive notes outlining gaps, duplicate IDs, or missing negative/edge scenarios",
    )
    deduplicated_cases: Optional[List[TestCase]] = Field(
        default=None,
        description="Optional cleaned test cases with duplicates removed",
    )


class AgentState(TypedDict, total=False):
    """State schema for LangGraph agent workflow."""

    requirement: str
    parsed_points: List[str]
    test_cases: List[TestCase]
    review_notes: str
    gaps_found: bool
    uncovered_points: List[str]
    retries: int
    max_retries: int
    final_output_paths: Dict[str, str]
    coverage_summary: Dict[str, Any]
