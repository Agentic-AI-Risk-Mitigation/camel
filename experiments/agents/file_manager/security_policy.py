"""Security policy for file manager agent."""

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

logger = get_logger("file_manager")


def _get_arg(kwargs: Mapping[str, CaMeLValue], name: str, position: int) -> CaMeLValue:
    """
    Get argument from kwargs by name or position.
    CaMeL stores positional args as "0", "1", "2", etc.
    """
    return kwargs.get(name) or kwargs.get(str(position))


class FileManagerSecurityPolicy(BaseSecurityPolicy):
    """
    Security policy for file system operations.
    
    Key principles:
    1. Sensitive files can only be read by authorized users
    2. File content capabilities are based on directory (sensitive vs public)
    3. Summaries of sensitive files maintain original capabilities
    4. Writing respects capability boundaries
    5. Email sending requires recipient authorization to read content
    """
    
    def __init__(self):
        super().__init__()
        
        # Add file operation policies
        self.add_policy("read_file", self.read_file_policy)
        self.add_policy("list_directory", self.list_directory_policy)
        self.add_policy("write_file", self.write_file_policy)
        self.add_policy("summarize_content", self.summarize_policy)
        self.add_policy("send_file_via_email", self.send_email_policy)
        
        # Read-only operations
        self.no_side_effect_tools = ["read_file", "list_directory"]
    
    def read_file_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for reading files.
        Allow all reads, but capability tagging happens at tool level.
        """
        path = _get_arg(kwargs, "path", 0)
        if not path:
            return Denied("Path parameter is required")
        
        path_str = path.raw
        
        # Log sensitive file access
        if "sensitive/" in path_str:
            logger.log_security_event(
                "file_read",
                "read_file_policy",
                "allowed",
                reason="Sensitive file read (capability restricted)",
                context={"path": path_str}
            )
        
        return Allowed()
    
    def list_directory_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for listing directories.
        Currently allows all directory listings.
        """
        path = _get_arg(kwargs, "path", 0)
        if not path:
            return Denied("Path parameter is required")
        
        return Allowed()
    
    def write_file_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for writing files.
        Content being written must respect its capabilities.
        """
        path = _get_arg(kwargs, "path", 0)
        content = _get_arg(kwargs, "content", 1)
        
        if not path or not content:
            return Denied("Both path and content parameters are required")
        
        # Check content capabilities
        content_readers = get_all_readers(content)
        
        logger.log_security_event(
            "file_write",
            "write_file_policy",
            "allowed",
            reason="File write permitted to output directory",
            context={
                "path": path.raw,
                "content_readers": str(content_readers)
            }
        )
        
        # For now, allow writes to output directory
        # In stricter mode, could check if file path is appropriate for content sensitivity
        return Allowed()
    
    def summarize_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for summarizing content.
        Summary inherits the capabilities of the source text.
        This is critical - summaries of sensitive data remain sensitive.
        """
        text = _get_arg(kwargs, "text", 0)
        if not text:
            return Denied("Text parameter is required")
        
        text_readers = get_all_readers(text)
        
        logger.log_security_event(
            "content_summarization",
            "summarize_policy",
            "allowed",
            reason="Summarization permitted (inherits source capabilities)",
            context={"text_readers": str(text_readers)}
        )
        
        return Allowed()
    
    def send_email_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for sending emails with file content.
        CRITICAL: Recipient must be authorized to read the content.
        This is the key defense against data exfiltration.
        """
        recipient = _get_arg(kwargs, "recipient", 0)
        file_content = _get_arg(kwargs, "file_content", 1)
        subject = _get_arg(kwargs, "subject", 2)
        
        if not recipient or not file_content:
            return Denied("Recipient and file_content parameters are required")
        
        # Get readers of the content
        content_readers = get_all_readers(file_content)
        recipient_str = recipient.raw
        
        # Check if recipient can read the content
        potential_readers = set([recipient_str])
        
        if can_readers_read_value(potential_readers, file_content):
            logger.log_security_event(
                "email_send",
                "send_email_policy",
                "allowed",
                reason=f"Recipient {recipient_str} authorized to read content",
                context={
                    "recipient": recipient_str,
                    "subject": subject.raw if subject else "No subject",
                    "content_readers": str(content_readers)
                }
            )
            return Allowed()
        
        # Denied - data exfiltration attempt
        logger.log_security_event(
            "email_send",
            "send_email_policy",
            "denied",
            reason=f"Recipient {recipient_str} not authorized to read content",
            context={
                "recipient": recipient_str,
                "allowed_readers": str(content_readers),
                "subject": subject.raw if subject else "No subject"
            }
        )
        
        return Denied(
            f"Cannot send email to {recipient_str}. "
            f"Content can only be read by {content_readers}. "
            f"This prevents unauthorized data exfiltration."
        )
