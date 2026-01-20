"""Multi-agent coordinator CaMeL agent."""

import sys
from pathlib import Path

# Add experiments to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.utils import (
    CaMeLAgent,
    DependenciesPropagationMode,
    create_tool,
    create_public_tool,
    get_logger
)
from experiments.config import TEST_USERS

from .tools import (
    delegate_to_researcher,
    delegate_to_writer,
    combine_results,
    send_notification
)
from .security_policy import MultiAgentSecurityPolicy

logger = get_logger("multi_agent_coordinator")

# Define tools with their capabilities
# Researcher output is readable by "researcher" entity
external_tools = [
    create_tool(
        delegate_to_researcher,
        readers=frozenset({"researcher", TEST_USERS["trusted_user"]}),
        writers=frozenset()
    ),
    # Writer processes content and outputs are public
    create_public_tool(delegate_to_writer),
    # Combiner output is public
    create_public_tool(combine_results),
    # Notification sending is public tool but policy enforces restrictions
    create_public_tool(send_notification),
]

# Create the CaMeL agent
root_agent = CaMeLAgent(
    name="MultiAgentCoordinator",
    model="gemini-2.5-pro",
    tools=external_tools,
    security_policy_engine=MultiAgentSecurityPolicy(),
    eval_mode=DependenciesPropagationMode.NORMAL,
)

logger.log_event("agent_created", {
    "agent_name": "MultiAgentCoordinator",
    "tool_count": len(external_tools),
    "security_policy": "MultiAgentSecurityPolicy"
})
