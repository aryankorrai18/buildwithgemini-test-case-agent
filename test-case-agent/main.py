"""CLI Entry point for the Google ADK Test Case Generator Agent."""

import argparse
import sys
from agent.graph import build_graph
from agent.llm import configure_adk_environment, get_default_model
from agent.tools import read_requirement


def parse_args():
    parser = argparse.ArgumentParser(
        description="Google ADK Test Case Generator Agent: Generate, review, and export test suites from requirements."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--input",
        type=str,
        help="Path to requirement file (.txt, .md)",
    )
    group.add_argument(
        "--text",
        type=str,
        help="Raw text string containing requirement or user story",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Gemini Model name (default: gemini-2.5-flash)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Maximum review refinement iterations (default: 2)",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="outputs",
        help="Output directory for generated files (default: outputs)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Read and validate input
    raw_input = args.input if args.input else args.text
    try:
        requirement_text = read_requirement(raw_input)
    except ValueError as e:
        print(f"\n[Error] Invalid requirement input: {e}", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("🚀 Google ADK Test Case Generator Agent")
    print("=" * 60)
    configure_adk_environment()
    resolved_model = get_default_model(args.model)
    print(f"Target Output Directory: {args.out_dir}")
    print(f"Max Review Retries     : {args.max_retries}")
    print(f"ADK Agent Model        : {resolved_model}")

    # Build and initialize ADK Workflow
    try:
        workflow = build_graph(model=resolved_model, out_dir=args.out_dir)
    except Exception as e:
        print(f"\n[Configuration Error] Failed to initialize ADK workflow: {e}", file=sys.stderr)
        sys.exit(1)

    initial_state = {
        "requirement": requirement_text,
        "parsed_points": [],
        "test_cases": [],
        "review_notes": "",
        "gaps_found": False,
        "uncovered_points": [],
        "retries": 0,
        "max_retries": args.max_retries,
    }

    try:
        final_state = workflow.run(initial_state)
    except Exception as e:
        print(f"\n[Execution Error] Workflow execution failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Success Summary
    test_cases = final_state.get("test_cases", [])
    output_paths = final_state.get("final_output_paths", {})
    coverage = final_state.get("coverage_summary", {})
    counts = coverage.get("counts_by_type", {})

    print("\n" + "=" * 60)
    print("✅ Execution Complete!")
    print("=" * 60)
    print(f"Total Test Cases Generated: {len(test_cases)}")
    print(f"  - Positive Cases : {counts.get('positive', 0)}")
    print(f"  - Negative Cases : {counts.get('negative', 0)}")
    print(f"  - Edge Cases     : {counts.get('edge', 0)}")
    print("\nGenerated Output Files:")
    for key, path in output_paths.items():
        print(f"  - [{key.upper()}]: {path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
