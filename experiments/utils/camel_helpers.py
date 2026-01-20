"""Helper utilities for working with CaMeL components."""

import sys
from pathlib import Path
from typing import Callable, Tuple, Any, Mapping

# Add camel to path for imports
CAMEL_ROOT = Path(__file__).parent.parent.parent / "camel"
sys.path.insert(0, str(CAMEL_ROOT))

from camel.camel_agent import camel_agent
from camel.camel_library import security_policy
from camel.camel_library.capabilities import capabilities
from camel.camel_library.capabilities import utils as capabilities_utils
from camel.camel_library.interpreter import interpreter

# Type aliases
CaMeLValue = camel_agent.CaMeLValue
Tool = Tuple[Callable, capabilities.Capabilities, Tuple]
SecurityPolicyResult = security_policy.SecurityPolicyResult
Allowed = security_policy.Allowed
Denied = security_policy.Denied
SecurityPolicyEngine = security_policy.SecurityPolicyEngine
Capabilities = capabilities.Capabilities
DependenciesPropagationMode = interpreter.DependenciesPropagationMode
CaMeLAgent = camel_agent.CaMeLAgent


def create_tool(
    func: Callable,
    readers: frozenset = frozenset(),
    writers: frozenset = frozenset(),
    dependencies: Tuple = ()
) -> Tool:
    """
    Create a CaMeL tool with capabilities.
    
    Args:
        func: The tool function
        readers: Set of entities that can read the output
        writers: Set of entities that can write/modify the output
        dependencies: Dependencies for the tool
    
    Returns:
        Tuple of (function, capabilities, dependencies)
    """
    caps = Capabilities(writers, readers)
    return (func, caps, dependencies)


def create_public_tool(func: Callable, dependencies: Tuple = ()) -> Tool:
    """Create a tool with public (CaMeL) capabilities."""
    return (func, Capabilities.camel(), dependencies)


def can_readers_read_value(readers: set, value: CaMeLValue) -> bool:
    """Check if readers can read a CaMeL value."""
    return capabilities_utils.can_readers_read_value(readers, value)


def get_all_readers(value: CaMeLValue) -> frozenset:
    """Get all readers of a CaMeL value."""
    return capabilities_utils.get_all_readers(value)


class BaseSecurityPolicy(SecurityPolicyEngine):
    """Base security policy with common patterns."""
    
    def __init__(self):
        self.policies = [
            ("query_ai_assistant", self.query_ai_assistant_policy),
        ]
        self.no_side_effect_tools = []
    
    def query_ai_assistant_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Default policy for query_ai_assistant - always allow."""
        return Allowed()
    
    def add_policy(self, tool_name: str, policy_func: Callable):
        """Add a policy for a tool."""
        self.policies.append((tool_name, policy_func))
    
    def check_readers_match(
        self,
        recipient_value: CaMeLValue,
        content_value: CaMeLValue,
        error_msg: str = "Reader mismatch"
    ) -> SecurityPolicyResult:
        """
        Common pattern: Check if recipient can read content.
        Used for email, file writes, etc.
        """
        potential_readers = set([recipient_value.raw])
        
        if can_readers_read_value(potential_readers, content_value):
            return Allowed()
        
        actual_readers = get_all_readers(content_value)
        return Denied(
            f"{error_msg}. Content can only be read by {actual_readers}, "
            f"but attempted recipient is {recipient_value.raw}"
        )


def format_security_violation(error: Exception) -> str:
    """Format a security policy violation for logging."""
    return f"SECURITY VIOLATION: {str(error)}"
