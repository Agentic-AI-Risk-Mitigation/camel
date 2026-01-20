"""Web content processor CaMeL agent."""

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
    fetch_url,
    extract_data,
    save_summary,
    generate_report
)
from .security_policy import WebContentSecurityPolicy

logger = get_logger("web_content_processor")

# Define tools with capabilities
# Fetched content is untrusted - only specific entities can read
# For internal URLs, only security team can read
# For public URLs, anyone can read but we track the source

external_tools = [
    # Fetched content from internal URLs is restricted
    create_tool(
        fetch_url,
        readers=frozenset({"web_fetcher", TEST_USERS["trusted_user"]}),
        writers=frozenset()
    ),
    # Extraction maintains source capabilities
    create_tool(
        extract_data,
        readers=frozenset({"extractor", TEST_USERS["trusted_user"]}),
        writers=frozenset()
    ),
    # Report generation is public but input capabilities are preserved
    create_public_tool(generate_report),
    # Saving respects capability boundaries
    create_public_tool(save_summary),
]

# Create the CaMeL agent
root_agent = CaMeLAgent(
    name="WebContentProcessor",
    model="gemini-2.5-pro",
    tools=external_tools,
    security_policy_engine=WebContentSecurityPolicy(),
    eval_mode=DependenciesPropagationMode.NORMAL,
)

logger.log_event("agent_created", {
    "agent_name": "WebContentProcessor",
    "tool_count": len(external_tools),
    "security_policy": "WebContentSecurityPolicy"
})
