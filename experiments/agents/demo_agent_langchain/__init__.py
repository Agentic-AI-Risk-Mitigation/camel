"""Demo Agent with LangChain integration."""

# Import factory function instead of agent instance
from .agent import get_agent, run_demo
from .tools import (
    search_document,
    send_email,
    extract_structured_data,
    delegate_to_validator,
    combine_results,
    log_action,
    format_report,
)
from .security_policy import EnhancedSecurityPolicy

__all__ = [
    "get_agent",  # Factory function
    "run_demo",  # Convenience function
    "search_document",
    "send_email",
    "extract_structured_data",
    "delegate_to_validator",
    "combine_results",
    "log_action",
    "format_report",
    "EnhancedSecurityPolicy",
]
