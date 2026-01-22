"""File system manager CaMeL agent."""

from experiments.utils import (
    CaMeLAgent,
    DependenciesPropagationMode,
    create_tool,
    create_public_tool,
    get_logger
)
from experiments.config import TEST_USERS

from .tools import (
    read_file,
    list_directory,
    write_file,
    summarize_content,
    send_file_via_email
)
from .security_policy import FileManagerSecurityPolicy

logger = get_logger("file_manager")

# Define tools with capabilities based on file locations
external_tools = [
    # read_file returns content with capabilities based on directory
    # For sensitive files: only security team and admin can read
    # For public files: anyone can read (public capabilities)
    create_tool(
        read_file,
        readers=frozenset({
            TEST_USERS["admin_user"],
            TEST_USERS["trusted_user"],
            "security-team@security-camp.com",
            "finance@security-camp.com"
        })
    ),
    # list_directory is safe - just shows filenames
    create_public_tool(list_directory),
    # write_file respects input capabilities
    create_public_tool(write_file),
    # summarize_content maintains source capabilities
    create_tool(
        summarize_content,
        readers=frozenset({
            TEST_USERS["admin_user"],
            TEST_USERS["trusted_user"],
            "security-team@security-camp.com"
        })
    ),
    # send_file_via_email enforces recipient authorization
    create_public_tool(send_file_via_email),
]

# Create the CaMeL agent
root_agent = CaMeLAgent(
    name="FileSystemManager",
    model="gemini-2.5-pro",
    tools=external_tools,
    security_policy_engine=FileManagerSecurityPolicy(),
    eval_mode=DependenciesPropagationMode.NORMAL,
)

logger.log_event("agent_created", {
    "agent_name": "FileSystemManager",
    "tool_count": len(external_tools),
    "security_policy": "FileManagerSecurityPolicy"
})
