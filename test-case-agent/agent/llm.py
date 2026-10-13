"""ADK Agent and GenAI model configuration."""

import os
from dotenv import load_dotenv

load_dotenv()


def configure_adk_environment():
    """Ensure Vertex AI / Gemini environment settings are populated."""
    # If GOOGLE_GENAI_USE_VERTEXAI is enabled or project is available, configure Vertex AI defaults
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI") == "1" or not os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "1"
        if not os.getenv("GOOGLE_CLOUD_PROJECT"):
            # Try to grab active gcloud project
            try:
                import subprocess

                proc = subprocess.run(
                    ["gcloud", "config", "get-value", "project"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                proj = proc.stdout.strip()
                if proj and " " not in proj:
                    os.environ["GOOGLE_CLOUD_PROJECT"] = proj
            except Exception:
                pass

        if not os.getenv("GOOGLE_CLOUD_LOCATION"):
            os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"


def get_default_model(model: str = None) -> str:
    """Return configured Gemini model name."""
    configure_adk_environment()
    return model or os.getenv("GEMINI_MODEL") or os.getenv("LLM_MODEL") or "gemini-2.5-flash"
