"""Application entry point. Run with: uv run uvicorn heatwave_api.main:app --reload

The model and explainer load in the app's startup (lifespan), so a bad artifact stops
the process here instead of on the first prediction request.
"""

from heatwave_api.app import create_app

app = create_app()
