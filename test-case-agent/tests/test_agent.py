"""Unit and integration tests for Google ADK Test Case Generator Agent."""

import json
import os
import pytest
from unittest.mock import MagicMock
from pydantic import ValidationError

from agent.state import TestCase, AgentState
from agent.tools import (
    read_requirement,
    clean_json_text,
    parse_json_safely,
    write_csv,
    write_markdown,
    write_json,
)
from agent.graph import should_continue, parse_node, generate_node, review_node, finalize_node, build_graph


# --- 1. JSON Parsing Tests ---
def test_json_cleaner_and_parser_handles_fences():
    """Verify clean_json_text and parse_json_safely strip code fences."""
    fenced_json = """```json
    {
      "key": "value",
      "count": 42
    }
    ```"""
    data = parse_json_safely(fenced_json)
    assert data["key"] == "value"
    assert data["count"] == 42


def test_json_cleaner_handles_prose_wrapping():
    """Verify parser extracts JSON object when surrounded by conversational prose."""
    prose_json = """Here is the extracted test output:
    {
      "status": "success",
      "items": [1, 2, 3]
    }
    Done."""
    data = parse_json_safely(prose_json)
    assert data["status"] == "success"
    assert len(data["items"]) == 3


def test_json_parser_repair_pass_on_malformed_json():
    """Verify that an initial json parse error triggers the repair agent callback."""
    bad_json = "{ key: 'missing quotes and bad syntax' "
    mock_repair_turn = MagicMock(return_value='{"key": "repaired"}')

    data = parse_json_safely(bad_json, repair_agent_turn=mock_repair_turn)
    assert data["key"] == "repaired"
    mock_repair_turn.assert_called_once()


def test_json_parser_raises_on_unrepairable_json():
    """Verify that ValueError is raised if JSON cannot be parsed even after repair."""
    bad_json = "plain invalid text"
    with pytest.raises(ValueError, match="Failed to parse valid JSON"):
        parse_json_safely(bad_json)


# --- 2. TestCase Pydantic Validation Tests ---
def test_test_case_validation_success():
    """Valid TestCase attributes should instantiate cleanly."""
    tc = TestCase(
        id="TC-001",
        title="Valid login",
        preconditions="User exists",
        steps=["Step 1", "Step 2"],
        expected_result="Login succeeded",
        type="positive",
        requirement_ref="REQ-1",
    )
    assert tc.id == "TC-001"
    assert tc.type == "positive"


def test_test_case_validation_rejects_bad_type():
    """TestCase should reject types other than positive, negative, edge."""
    with pytest.raises(ValidationError):
        TestCase(
            id="TC-002",
            title="Invalid type test",
            preconditions="None",
            steps=["Step 1"],
            expected_result="Fails",
            type="exploratory",  # Invalid type
            requirement_ref="REQ-1",
        )


def test_test_case_validation_rejects_empty_fields():
    """TestCase should reject empty id, title, or steps."""
    with pytest.raises(ValidationError):
        TestCase(
            id="",
            title="Empty ID",
            preconditions="None",
            steps=["Step 1"],
            expected_result="Fails",
            type="positive",
            requirement_ref="REQ-1",
        )

    with pytest.raises(ValidationError):
        TestCase(
            id="TC-003",
            title="No steps",
            preconditions="None",
            steps=[],  # Min length is 1
            expected_result="Fails",
            type="positive",
            requirement_ref="REQ-1",
        )


# --- 3. Conditional Edge Routing Tests ---
def test_conditional_edge_routes_to_generate_on_gaps():
    """Router loops to generate_node when gaps_found is True and retries < max_retries."""
    state: AgentState = {
        "gaps_found": True,
        "retries": 0,
        "max_retries": 2,
    }
    next_node = should_continue(state)
    assert next_node == "generate_node"


def test_conditional_edge_routes_to_finalize_when_max_retries_reached():
    """Router stops and routes to finalize_node when retries >= max_retries."""
    state: AgentState = {
        "gaps_found": True,
        "retries": 2,
        "max_retries": 2,
    }
    next_node = should_continue(state)
    assert next_node == "finalize_node"


def test_conditional_edge_routes_to_finalize_when_no_gaps():
    """Router routes to finalize_node when gaps_found is False."""
    state: AgentState = {
        "gaps_found": False,
        "retries": 0,
        "max_retries": 2,
    }
    next_node = should_continue(state)
    assert next_node == "finalize_node"


# --- 4. CSV Export Tests ---
def test_write_csv_produces_expected_columns(tmp_path):
    """write_csv should generate CSV with all required columns."""
    sample_cases = [
        TestCase(
            id="TC-001",
            title="Verify positive login",
            preconditions="Account active",
            steps=["Enter email", "Enter password", "Click Login"],
            expected_result="Redirected to dashboard",
            type="positive",
            requirement_ref="REQ-1",
        ),
        TestCase(
            id="TC-002",
            title="Verify lockout on 5 attempts",
            preconditions="Account active",
            steps=["Enter wrong password 5 times"],
            expected_result="Account locked",
            type="negative",
            requirement_ref="REQ-2",
        ),
    ]

    csv_out = str(tmp_path / "test_cases.csv")
    result_path = write_csv(sample_cases, csv_out)
    assert os.path.exists(result_path)

    import csv
    with open(result_path, mode="r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        headers = reader[0]
        assert headers == [
            "ID",
            "Title",
            "Preconditions",
            "Steps",
            "Expected Result",
            "Type",
            "Requirement Ref",
        ]
        assert len(reader) == 3
        assert reader[1][0] == "TC-001"
        assert reader[1][5] == "positive"
        assert reader[2][0] == "TC-002"
        assert reader[2][5] == "negative"


# --- 5. Empty / Short Input Validation Tests ---
def test_read_requirement_rejects_empty_or_short_input(tmp_path):
    """read_requirement should reject empty or short strings and files."""
    with pytest.raises(ValueError, match="too short"):
        read_requirement("Short text")

    with pytest.raises(ValueError, match="too short"):
        read_requirement("   ")

    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("   ", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        read_requirement(str(empty_file))


def test_read_requirement_reads_valid_file(tmp_path):
    """read_requirement reads valid file correctly."""
    valid_file = tmp_path / "req.md"
    content = "As a registered customer, I want to securely log in to my account with my email."
    valid_file.write_text(content, encoding="utf-8")
    result = read_requirement(str(valid_file))
    assert result == content


# --- 6. Integration Test (Optional) ---
@pytest.mark.integration
def test_full_adk_workflow_with_real_api(tmp_path):
    """End-to-end integration test with Google ADK on Vertex AI / Gemini API."""
    from agent.graph import build_graph

    workflow = build_graph(out_dir=str(tmp_path))
    state = {
        "requirement": "As a user I want to log in with my email and password. Lock out after 5 failures.",
        "parsed_points": [],
        "test_cases": [],
        "review_notes": "",
        "gaps_found": False,
        "uncovered_points": [],
        "retries": 0,
        "max_retries": 1,
    }

    final_state = workflow.run(state)
    assert len(final_state["test_cases"]) >= 1
    assert os.path.exists(tmp_path / "test_cases.csv")
    assert os.path.exists(tmp_path / "test_cases.md")
    assert os.path.exists(tmp_path / "test_cases.json")
