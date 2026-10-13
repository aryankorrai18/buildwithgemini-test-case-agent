"""File and parsing utilities for test case generator agent."""

import csv
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from agent.state import TestCase

logger = logging.getLogger(__name__)


def read_requirement(path_or_text: str) -> str:
    """Read requirement from file or return text directly.

    Args:
        path_or_text: File path to a requirement (.txt, .md) or raw requirement text.

    Returns:
        Cleaned requirement string.

    Raises:
        ValueError: If requirement is empty or too short.
    """
    cleaned = path_or_text.strip()
    potential_path = Path(cleaned)
    if potential_path.is_file():
        try:
            content = potential_path.read_text(encoding="utf-8").strip()
            if not content:
                raise ValueError(f"Requirement file '{path_or_text}' is empty.")
            cleaned = content
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Could not read requirement file '{path_or_text}': {e}")

    if len(cleaned) < 15:
        raise ValueError(
            f"Requirement input is too short ({len(cleaned)} chars). "
            "Please provide a meaningful requirement or user story."
        )

    return cleaned


def clean_json_text(text: str) -> str:
    """Strip markdown code block fences and isolate JSON structure."""
    text = text.strip()
    fence_pattern = r"^```(?:json)?\s*([\s\S]*?)\s*```$"
    match = re.match(fence_pattern, text, re.IGNORECASE)
    if match:
        text = match.group(1).strip()
    else:
        fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fenced_blocks:
            text = fenced_blocks[0].strip()

    first_brace = text.find("{")
    first_bracket = text.find("[")

    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        last_brace = text.rfind("}")
        if last_brace != -1:
            text = text[first_brace : last_brace + 1]
    elif first_bracket != -1:
        last_bracket = text.rfind("]")
        if last_bracket != -1:
            text = text[first_bracket : last_bracket + 1]

    return text.strip()


def parse_json_safely(
    text: str,
    repair_agent_turn: Optional[Any] = None,
) -> Any:
    """Parse JSON string safely, stripping code fences, with optional repair pass."""
    cleaned = clean_json_text(text)
    try:
        return json.loads(cleaned)
    except Exception as initial_error:
        logger.warning(
            "Initial JSON parsing failed: %s. Raw preview: %s",
            initial_error,
            text[:150],
        )

        if repair_agent_turn:
            logger.info("Attempting single JSON repair pass via repair agent...")
            try:
                repair_prompt = f"Fix this invalid JSON (Error: {initial_error}):\n{text}"
                repaired_content = repair_agent_turn(repair_prompt)
                cleaned_repaired = clean_json_text(repaired_content)
                return json.loads(cleaned_repaired)
            except Exception as repair_error:
                logger.error("JSON repair attempt failed: %s", repair_error)

        raise ValueError(
            f"Failed to parse valid JSON from LLM output: {initial_error}\nRaw snippet: {text[:200]}"
        )


def write_csv(test_cases: List[TestCase], output_path: str) -> str:
    """Write test cases to a CSV file.

    Columns: ID, Title, Preconditions, Steps, Expected Result, Type, Requirement Ref
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "ID",
        "Title",
        "Preconditions",
        "Steps",
        "Expected Result",
        "Type",
        "Requirement Ref",
    ]

    with open(path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fieldnames)
        for tc in test_cases:
            steps_formatted = " \n".join(
                [f"{i+1}. {step}" for i, step in enumerate(tc.steps)]
            )
            writer.writerow([
                tc.id,
                tc.title,
                tc.preconditions,
                steps_formatted,
                tc.expected_result,
                tc.type,
                tc.requirement_ref,
            ])

    return str(path.resolve())


def write_markdown(
    test_cases: List[TestCase],
    output_path: str,
    coverage_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Write test cases and coverage summary to a Markdown file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = [
        "# Generated Test Cases",
        "",
        f"*Total Test Cases: {len(test_cases)}*",
        "",
        "| ID | Title | Type | Requirement Ref | Preconditions | Steps | Expected Result |",
        "|---|---|---|---|---|---|---|",
    ]

    for tc in test_cases:
        steps_clean = "<br/>".join(
            [f"{i+1}. {s.replace('|', '-').strip()}" for i, s in enumerate(tc.steps)]
        )
        title_clean = tc.title.replace("|", "-").strip()
        precond_clean = tc.preconditions.replace("|", "-").strip()
        result_clean = tc.expected_result.replace("|", "-").strip()
        req_clean = tc.requirement_ref.replace("|", "-").strip()

        lines.append(
            f"| {tc.id} | {title_clean} | `{tc.type}` | {req_clean} | {precond_clean} | {steps_clean} | {result_clean} |"
        )

    lines.append("")
    lines.append("## Coverage Summary")
    lines.append("")

    if coverage_summary:
        counts = coverage_summary.get("counts_by_type", {})
        lines.append("### Test Case Distribution")
        lines.append(f"- **Positive**: {counts.get('positive', 0)}")
        lines.append(f"- **Negative**: {counts.get('negative', 0)}")
        lines.append(f"- **Edge**: {counts.get('edge', 0)}")
        lines.append(f"- **Total**: {len(test_cases)}")
        lines.append("")

        covered = coverage_summary.get("covered_points", [])
        lines.append(f"### Covered Requirement Points ({len(covered)})")
        for pt in covered:
            lines.append(f"- {pt}")
        lines.append("")

        uncovered = coverage_summary.get("uncovered_points", [])
        lines.append(f"### Uncovered Points ({len(uncovered)})")
        if uncovered:
            for pt in uncovered:
                lines.append(f"- ⚠️ {pt}")
        else:
            lines.append("- *All identified requirement points are fully covered!*")
        lines.append("")

        notes = coverage_summary.get("review_notes", "")
        if notes:
            lines.append("### Review & Quality Notes")
            lines.append(f"> {notes}")
            lines.append("")
    else:
        counts: Dict[str, int] = {}
        for tc in test_cases:
            counts[tc.type] = counts.get(tc.type, 0) + 1
        lines.append(f"- **Positive**: {counts.get('positive', 0)}")
        lines.append(f"- **Negative**: {counts.get('negative', 0)}")
        lines.append(f"- **Edge**: {counts.get('edge', 0)}")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path.resolve())


def write_json(test_cases: List[TestCase], output_path: str) -> str:
    """Write test cases to a structured JSON file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    data = [tc.model_dump() for tc in test_cases]
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path.resolve())
