"""ADK-based multi-agent workflow for the Test Case Generator Agent.

Constructs specialized Google ADK Agents:
- Parser Agent: decomposes user stories into structured requirement criteria
- Generator Agent: generates positive, negative, and edge test cases
- Reviewer Agent: checks for gaps, duplicates, and coverage defects
- Orchestration Runner: controls the self-correction loop up to max_retries and finalizes outputs
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.llm import get_default_model
from agent.prompts import (
    PARSER_INSTRUCTION,
    GENERATOR_INSTRUCTION,
    REVIEWER_INSTRUCTION,
    REPAIR_JSON_INSTRUCTION,
)
from agent.state import AgentState, TestCase
from agent.tools import (
    parse_json_safely,
    write_csv,
    write_markdown,
    write_json,
)

logger = logging.getLogger(__name__)


def create_adk_agents(model: Optional[str] = None) -> Dict[str, Agent]:
    """Create the specialized Google ADK agents."""
    model_name = get_default_model(model)
    gen_config = types.GenerateContentConfig(
        temperature=0.2,
        response_mime_type="application/json",
    )

    parser = Agent(
        name="requirement_parser",
        model=model_name,
        instruction=PARSER_INSTRUCTION,
        generate_content_config=gen_config,
    )

    generator = Agent(
        name="test_case_generator",
        model=model_name,
        instruction=GENERATOR_INSTRUCTION,
        generate_content_config=gen_config,
    )

    reviewer = Agent(
        name="test_case_reviewer",
        model=model_name,
        instruction=REVIEWER_INSTRUCTION,
        generate_content_config=gen_config,
    )

    repairer = Agent(
        name="json_repairer",
        model=model_name,
        instruction=REPAIR_JSON_INSTRUCTION,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )

    return {
        "parser": parser,
        "generator": generator,
        "reviewer": reviewer,
        "repairer": repairer,
    }


def execute_agent_turn(
    agent: Agent,
    prompt_text: str,
    user_id: str = "qa_user",
    app_name: str = "test_case_app",
    custom_runner: Optional[Any] = None,
    max_rate_retries: int = 4,
) -> str:
    """Execute a single turn with an ADK agent with exponential backoff on 429 quota."""
    if custom_runner is not None:
        return custom_runner(agent, prompt_text)

    for attempt in range(max_rate_retries):
        try:
            session_service = InMemorySessionService()
            session = session_service.create_session_sync(app_name=app_name, user_id=user_id)
            runner = Runner(agent=agent, session_service=session_service, app_name=app_name)

            content = types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])
            collected_text = []

            for event in runner.run(session_id=session.id, user_id=user_id, new_message=content):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.text:
                            collected_text.append(part.text)

            return "".join(collected_text).strip()
        except Exception as e:
            err_str = str(e)
            if ("429" in err_str or "RESOURCE_EXHAUSTED" in err_str) and attempt < max_rate_retries - 1:
                wait_secs = 5 * (2 ** attempt)
                logger.warning(
                    "Rate limit / TPM exhausted on attempt %d. Backing off for %ds... Error: %s",
                    attempt + 1,
                    wait_secs,
                    e,
                )
                print(f"[Rate Limit] Backing off for {wait_secs}s before retry...")
                time.sleep(wait_secs)
            else:
                raise


def parse_node(
    state: AgentState,
    agents: Dict[str, Agent],
    custom_runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """Node 1: Extract features and acceptance criteria into points."""
    print("\n[Node 1: parse_node] Starting requirements analysis with ADK Parser Agent...")
    prompt = f"Requirement:\n{state['requirement']}"

    raw_response = execute_agent_turn(
        agents["parser"],
        prompt,
        custom_runner=custom_runner,
    )

    data = parse_json_safely(raw_response)
    points = []
    if isinstance(data, dict):
        points = data.get("requirement_points", [])
    elif isinstance(data, list):
        points = [str(x) for x in data]

    if not points:
        points = [state["requirement"]]

    print(f"[Node 1: parse_node] Finished. Extracted {len(points)} requirement points.")
    return {
        "parsed_points": points,
        "retries": state.get("retries", 0),
        "max_retries": state.get("max_retries", 2),
    }


def generate_node(
    state: AgentState,
    agents: Dict[str, Agent],
    custom_runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """Node 2: Generate positive, negative, and edge test cases."""
    print("\n[Node 2: generate_node] Generating test cases with ADK Generator Agent...")
    uncovered = state.get("uncovered_points", [])
    notes = state.get("review_notes", "")
    existing_cases = state.get("test_cases", [])

    feedback_text = ""
    if uncovered or notes:
        feedback_text = (
            f"\n\n--- FEEDBACK FROM REVIEW PASS ---\n"
            f"Review Notes: {notes}\n"
            f"Uncovered Points to Cover: {json.dumps(uncovered)}\n"
            "Action Required: Produce new or improved test cases covering all uncovered points, negative paths, and edge cases."
        )

    prompt = (
        f"Requirement Specification:\n{state['requirement']}\n\n"
        f"Parsed Requirement Points:\n{json.dumps(state.get('parsed_points', []), indent=2)}"
        f"{feedback_text}"
    )

    raw_response = execute_agent_turn(
        agents["generator"],
        prompt,
        custom_runner=custom_runner,
    )

    data = parse_json_safely(raw_response)
    raw_cases = []
    if isinstance(data, dict):
        raw_cases = data.get("test_cases", [])
    elif isinstance(data, list):
        raw_cases = data

    validated_cases: List[TestCase] = []
    for item in raw_cases:
        try:
            validated_cases.append(TestCase.model_validate(item))
        except Exception as e:
            logger.warning("Dropped invalid test case: %s. Error: %s", item, e)

    # Combine cases and deduplicate by title
    combined_cases: List[TestCase] = []
    seen_titles = set()
    for tc in existing_cases + validated_cases:
        norm = tc.title.strip().lower()
        if norm not in seen_titles:
            seen_titles.add(norm)
            combined_cases.append(tc)

    print(
        f"[Node 2: generate_node] Finished. Total validated cases so far: {len(combined_cases)}"
    )
    return {"test_cases": combined_cases}


def review_node(
    state: AgentState,
    agents: Dict[str, Agent],
    custom_runner: Optional[Any] = None,
) -> Dict[str, Any]:
    """Node 3: Quality review and gap detection."""
    print("\n[Node 3: review_node] Reviewing test suite with ADK Reviewer Agent...")
    cases = state.get("test_cases", [])
    cases_dicts = [tc.model_dump() for tc in cases]

    prompt = (
        f"Original Requirement:\n{state['requirement']}\n\n"
        f"Parsed Points:\n{json.dumps(state.get('parsed_points', []), indent=2)}\n\n"
        f"Generated Test Cases:\n{json.dumps(cases_dicts, indent=2)}"
    )

    raw_response = execute_agent_turn(
        agents["reviewer"],
        prompt,
        custom_runner=custom_runner,
    )

    data = parse_json_safely(raw_response)
    gaps_found = False
    uncovered_points = []
    review_notes = ""
    updated_cases = cases

    if isinstance(data, dict):
        gaps_found = bool(data.get("gaps_found", False))
        uncovered_points = data.get("uncovered_points", []) or []
        review_notes = data.get("review_notes", "") or ""

        dedup_raw = data.get("deduplicated_cases")
        if dedup_raw and isinstance(dedup_raw, list):
            valid_dedup = []
            for item in dedup_raw:
                try:
                    valid_dedup.append(TestCase.model_validate(item))
                except Exception:
                    pass
            if valid_dedup:
                updated_cases = valid_dedup

    # Programmatic quality gate check
    type_counts: Dict[str, int] = {}
    for tc in updated_cases:
        type_counts[tc.type] = type_counts.get(tc.type, 0) + 1

    neg_count = type_counts.get("negative", 0)
    edge_count = type_counts.get("edge", 0)

    if neg_count < 2 or edge_count < 2 or len(updated_cases) < 8:
        gaps_found = True
        extra_note = (
            f"Quality gate: {neg_count} negative (need 2+), "
            f"{edge_count} edge (need 2+), {len(updated_cases)} total (need 8+)."
        )
        review_notes = f"{review_notes} | {extra_note}".strip(" |")

    print(
        f"[Node 3: review_node] Finished. gaps_found={gaps_found}, "
        f"uncovered_points={len(uncovered_points)}, retries={state.get('retries', 0)}"
    )

    return {
        "test_cases": updated_cases,
        "gaps_found": gaps_found,
        "uncovered_points": uncovered_points,
        "review_notes": review_notes,
    }


def should_continue(state: AgentState) -> str:
    """Conditional edge determining whether to loop back or finalize."""
    gaps_found = state.get("gaps_found", False)
    retries = state.get("retries", 0)
    max_retries = state.get("max_retries", 2)

    if gaps_found and retries < max_retries:
        print(
            f"\n[Router] Gaps detected. Looping back to generate_node (retry {retries + 1}/{max_retries})."
        )
        return "generate_node"

    print("\n[Router] Proceeding to finalize_node.")
    return "finalize_node"


def finalize_node(state: AgentState, out_dir: Optional[str] = None) -> Dict[str, Any]:
    """Node 4: Renumber IDs sequentially, build coverage metrics, write files."""
    print("\n[Node 4: finalize_node] Finalizing test cases and writing outputs...")

    output_directory = out_dir or "outputs"
    cases = state.get("test_cases", [])
    parsed_points = state.get("parsed_points", [])

    renumbered_cases: List[TestCase] = []
    for i, tc in enumerate(cases):
        updated_dict = tc.model_dump()
        updated_dict["id"] = f"TC-{i+1:03d}"
        renumbered_cases.append(TestCase.model_validate(updated_dict))

    counts_by_type: Dict[str, int] = {"positive": 0, "negative": 0, "edge": 0}
    covered_refs = set()
    for tc in renumbered_cases:
        counts_by_type[tc.type] = counts_by_type.get(tc.type, 0) + 1
        for ref_part in tc.requirement_ref.split(","):
            cleaned_ref = ref_part.strip().lower()
            if cleaned_ref:
                covered_refs.add(cleaned_ref)

    covered_points = []
    uncovered_points = []
    for pt in parsed_points:
        pt_lower = pt.lower()
        matched = False
        for ref in covered_refs:
            if ref in pt_lower or (":" in pt_lower and pt_lower.split(":")[0].strip() == ref):
                matched = True
                break
        if matched:
            covered_points.append(pt)
        else:
            uncovered_points.append(pt)

    if not covered_points and parsed_points:
        covered_points = parsed_points
        uncovered_points = []

    coverage_summary = {
        "total_test_cases": len(renumbered_cases),
        "counts_by_type": counts_by_type,
        "covered_points": covered_points,
        "uncovered_points": uncovered_points,
        "review_notes": state.get("review_notes", ""),
    }

    csv_path = write_csv(renumbered_cases, f"{output_directory}/test_cases.csv")
    md_path = write_markdown(
        renumbered_cases,
        f"{output_directory}/test_cases.md",
        coverage_summary=coverage_summary,
    )
    json_path = write_json(renumbered_cases, f"{output_directory}/test_cases.json")

    output_paths = {
        "csv": csv_path,
        "markdown": md_path,
        "json": json_path,
    }

    print(f"[Node 4: finalize_node] Finished. Output written to {output_directory}/")
    return {
        "test_cases": renumbered_cases,
        "final_output_paths": output_paths,
        "coverage_summary": coverage_summary,
    }


class ADKTestCaseWorkflow:
    """Orchestrates the Google ADK multi-agent workflow with self-correction."""

    def __init__(
        self,
        model: Optional[str] = None,
        out_dir: Optional[str] = None,
        custom_runner: Optional[Any] = None,
    ):
        self.out_dir = out_dir or "outputs"
        self.custom_runner = custom_runner
        self.agents = create_adk_agents(model=model)

    def run(self, initial_state: AgentState) -> AgentState:
        """Execute the multi-agent workflow."""
        state = dict(initial_state)
        state.setdefault("retries", 0)
        state.setdefault("max_retries", 2)
        state.setdefault("test_cases", [])

        # Node 1: Parse
        parse_res = parse_node(state, self.agents, custom_runner=self.custom_runner)
        state.update(parse_res)

        # Loop: Generate -> Review -> Conditional Edge
        while True:
            gen_res = generate_node(state, self.agents, custom_runner=self.custom_runner)
            state.update(gen_res)

            rev_res = review_node(state, self.agents, custom_runner=self.custom_runner)
            state.update(rev_res)

            next_step = should_continue(state)
            if next_step == "generate_node":
                state["retries"] = state.get("retries", 0) + 1
                continue
            else:
                break

        # Node 4: Finalize
        fin_res = finalize_node(state, out_dir=self.out_dir)
        state.update(fin_res)
        return state


def build_graph(
    model: Optional[str] = None,
    out_dir: Optional[str] = None,
    custom_runner: Optional[Any] = None,
) -> ADKTestCaseWorkflow:
    """Build and return the ADK Test Case Workflow."""
    return ADKTestCaseWorkflow(model=model, out_dir=out_dir, custom_runner=custom_runner)
