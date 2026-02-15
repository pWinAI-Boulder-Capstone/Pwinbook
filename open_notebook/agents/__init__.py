"""Multi-agent system for podcast generation.

This module contains individual agent implementations for the agentic podcast workflow:
- Director: Creates strategic outline
- Writer: Generates transcript based on outline
"""

from open_notebook.agents.director import director_agent
from open_notebook.agents.writer import writer_agent

__all__ = ["director_agent", "writer_agent"]
