"""Security policy for multi-agent coordinator."""

import sys
from pathlib import Path
from collections.abc import Mapping

# Add experiments to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.utils import (
    BaseSecurityPolicy,
    SecurityPolicyResult,
    Allowed,
    Denied,
    CaMeLValue,
    can_readers_read_value,
    get_all_readers,
    get_logger
)

logger = get_logger("multi_agent_coordinator")


def _get_arg(kwargs: Mapping[str, CaMeLValue], name: str, position: int) -> CaMeLValue:
    """Get argument by name or position (CaMeL stores positional args as "0", "1", etc.)."""
    return kwargs.get(name) or kwargs.get(str(position))


class MultiAgentSecurityPolicy(BaseSecurityPolicy):
    """
    Security policy for multi-agent coordination.
    
    Key principles:
    1. Researcher output should be tagged with its source
    2. Writer can only process data it's allowed to read
    3. Notifications can only send data to authorized recipients
    4. Combined results inherit the most restrictive capabilities
    """
    
    def __init__(self):
        super().__init__()
        
        # Add policies for our tools
        self.add_policy("delegate_to_researcher", self.researcher_policy)
        self.add_policy("delegate_to_writer", self.writer_policy)
        self.add_policy("combine_results", self.combiner_policy)
        self.add_policy("send_notification", self.notification_policy)
        
        # Tools without side effects (safe to call multiple times)
        self.no_side_effect_tools = ["delegate_to_researcher", "combine_results"]
    
    def researcher_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for researcher tool.
        Currently allows all queries, but logs them.
        """
        query = _get_arg(kwargs, "query", 0)
        if not query:
            return Denied("Query parameter is required")
        
        logger.log_security_event(
            "researcher_access",
            "researcher_policy",
            "allowed",
            reason="Researcher queries are permitted",
            context={"query": query.raw[:100]}
        )
        
        return Allowed()
    
    def writer_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for writer tool.
        Writer should only process content it can read.
        """
        content = _get_arg(kwargs, "content", 0)
        format_type = _get_arg(kwargs, "format", 1)
        
        if not content or not format_type:
            return Denied("Both content and format parameters are required")
        
        # Check if content is from a safe source
        # In CaMeL, this is tracked by capabilities
        readers = get_all_readers(content)
        
        logger.log_security_event(
            "writer_access",
            "writer_policy",
            "allowed",
            reason="Writer processing content",
            context={
                "format": format_type.raw,
                "content_readers": str(readers),
                "content_preview": content.raw[:100]
            }
        )
        
        # For now, allow all - but we're tracking
        return Allowed()
    
    def combiner_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for combining results.
        The combined result should inherit the most restrictive capabilities.
        """
        parts = _get_arg(kwargs, "parts", 0)
        
        if not parts:
            return Denied("Parts parameter is required")
        
        logger.log_security_event(
            "combiner_access",
            "combiner_policy",
            "allowed",
            reason="Combining results",
            context={"parts_count": len(parts.raw) if hasattr(parts.raw, '__len__') else 0}
        )
        
        return Allowed()
    
    def notification_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for sending notifications.
        Critical: Message content can only be sent to recipients who can read it.
        """
        recipient = _get_arg(kwargs, "recipient", 0)
        message = _get_arg(kwargs, "message", 1)
        
        if not recipient or not message:
            return Denied("Both recipient and message parameters are required")
        
        # Check if recipient can read the message content
        potential_readers = set([recipient.raw])
        
        if can_readers_read_value(potential_readers, message):
            logger.log_security_event(
                "notification_send",
                "notification_policy",
                "allowed",
                reason=f"Recipient {recipient.raw} can read the message",
                context={"recipient": recipient.raw}
            )
            return Allowed()
        
        # Denied - recipient cannot read this content
        actual_readers = get_all_readers(message)
        
        logger.log_security_event(
            "notification_send",
            "notification_policy",
            "denied",
            reason=f"Recipient {recipient.raw} cannot read message with readers {actual_readers}",
            context={"recipient": recipient.raw, "allowed_readers": str(actual_readers)}
        )
        
        return Denied(
            f"Message cannot be sent to {recipient.raw}. "
            f"Message can only be read by {actual_readers}"
        )
