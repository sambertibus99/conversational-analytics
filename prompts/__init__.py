"""
Prompts Package.

Enthält alle System Prompts für die Agents.
"""

from prompts.data_agent_prompt import DATA_AGENT_SYSTEM_PROMPT
from prompts.viz_agent_prompt import VIZ_AGENT_SYSTEM_PROMPT

__all__ = [
    "DATA_AGENT_SYSTEM_PROMPT",
    "VIZ_AGENT_SYSTEM_PROMPT",
]
