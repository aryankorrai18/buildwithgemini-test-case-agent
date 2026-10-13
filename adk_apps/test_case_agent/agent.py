"""ADK Agent entry point for `adk web`."""
import os
import sys

# Add test-case-agent to sys.path so its modules (agent.state, agent.graph, etc.) can be loaded
_base_dir = "/config/Desktop/BuildWithGemini/test-case-agent"
if _base_dir not in sys.path:
    sys.path.insert(0, _base_dir)

from google.adk.agents import Agent
from agent.llm import get_default_model
from agent.graph import build_graph

model_name = get_default_model()


def generate_and_review_test_cases(requirement_text: str) -> str:
    """Analyze a user story or software requirement, extract criteria, generate positive/negative/edge test cases, review for gaps, and export test suites.

    Args:
        requirement_text: The user story, functional requirement, or acceptance criteria text.

    Returns:
        A formatted markdown summary of the generated test suite, test cases count, and file paths.
    """
    workflow = build_graph(model=model_name, out_dir="/config/Desktop/BuildWithGemini/test-case-agent/outputs")
    initial_state = {
        "requirement": requirement_text,
        "parsed_points": [],
        "test_cases": [],
        "review_notes": "",
        "gaps_found": False,
        "uncovered_points": [],
        "retries": 0,
        "max_retries": 2,
    }
    final_state = workflow.run(initial_state)

    coverage = final_state.get("coverage_summary", {})
    counts = coverage.get("counts_by_type", {})
    cases = final_state.get("test_cases", [])
    paths = final_state.get("final_output_paths", {})

    lines = [
        f"### 🎉 Test Suite Generated Successfully ({len(cases)} Cases)",
        "",
        f"- **Positive Cases**: {counts.get('positive', 0)}",
        f"- **Negative Cases**: {counts.get('negative', 0)}",
        f"- **Edge Cases**: {counts.get('edge', 0)}",
        "",
        "#### Generated Artifacts:",
        f"- **CSV**: `{paths.get('csv')}`",
        f"- **Markdown**: `{paths.get('markdown')}`",
        f"- **JSON**: `{paths.get('json')}`",
        "",
        "#### Generated Test Scenarios:",
    ]

    for tc in cases[:6]:
        lines.append(f"- **[{tc.id}] {tc.title}** (`{tc.type}`): Expected: {tc.expected_result}")

    if len(cases) > 6:
        lines.append(f"\n*(...and {len(cases) - 6} more test cases saved to files)*")

    return "\n".join(lines)


root_agent = Agent(
    name="test_case_generator_agent",
    model=model_name,
    instruction=(
        "You are an expert QA Automation Lead and Test Case Generator Agent. "
        "When a user provides a requirement, user story, or feature description, "
        "call the tool `generate_and_review_test_cases` with the user's requirement. "
        "Summarize the results cleanly and present the test cases, distribution, and file locations."
    ),
    tools=[generate_and_review_test_cases],
)
