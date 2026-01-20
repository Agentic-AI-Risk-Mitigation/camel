"""Security policy for web content processor."""

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

logger = get_logger("web_content_processor")


def _get_arg(kwargs: Mapping[str, CaMeLValue], name: str, position: int) -> CaMeLValue:
    """Get argument by name or position (CaMeL stores positional args as "0", "1", etc.)."""
    return kwargs.get(name) or kwargs.get(str(position))


class WebContentSecurityPolicy(BaseSecurityPolicy):
    """
    Security policy for web content processing.
    
    Key principles:
    1. Fetched content is untrusted and has restricted capabilities
    2. Extracted data from untrusted sources maintains restrictions
    3. Reports/summaries can only be saved to destinations that can read the source
    4. Content from different sources should not be mixed without permission
    """
    
    def __init__(self):
        super().__init__()
        
        # Add policies for web tools
        self.add_policy("fetch_url", self.fetch_policy)
        self.add_policy("extract_data", self.extract_policy)
        self.add_policy("save_summary", self.save_summary_policy)
        self.add_policy("generate_report", self.generate_report_policy)
        
        # Fetch and extract are read-only operations
        self.no_side_effect_tools = ["fetch_url", "extract_data"]
    
    def fetch_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for fetching URLs.
        Always allow fetching, but content will be tagged appropriately.
        """
        url = _get_arg(kwargs, "url", 0)
        if not url:
            return Denied("URL parameter is required")
        
        logger.log_security_event(
            "url_fetch",
            "fetch_policy",
            "allowed",
            reason="URL fetching is permitted",
            context={"url": url.raw}
        )
        
        return Allowed()
    
    def extract_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for data extraction.
        Extraction is allowed, but extracted data inherits source capabilities.
        """
        content = _get_arg(kwargs, "content", 0)
        schema = _get_arg(kwargs, "schema", 1)
        
        if not content:
            return Denied("Content parameter is required")
        
        # Get the readers of the content being extracted from
        content_readers = get_all_readers(content)
        
        logger.log_security_event(
            "data_extraction",
            "extract_policy",
            "allowed",
            reason="Data extraction permitted",
            context={
                "content_readers": str(content_readers),
                "schema": str(schema.raw) if schema else None
            }
        )
        
        return Allowed()
    
    def save_summary_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for saving summaries.
        CRITICAL: Summary can only be saved to destinations that can read the source.
        This prevents data exfiltration to unauthorized recipients.
        """
        summary = _get_arg(kwargs, "summary", 0)
        destination = _get_arg(kwargs, "destination", 1)
        
        if not summary or not destination:
            return Denied("Both summary and destination parameters are required")
        
        # Get readers of the summary content
        summary_readers = get_all_readers(summary)
        
        # Check if destination can read the summary
        # If destination is an email, check if that email is in readers
        # If destination is public, anyone can read
        
        dest_str = destination.raw
        
        # If summary is public (empty readers set or contains "public"), allow
        if not summary_readers or len(summary_readers) == 0:
            logger.log_security_event(
                "save_summary",
                "save_summary_policy",
                "allowed",
                reason="Summary is public, can be saved anywhere",
                context={"destination": dest_str}
            )
            return Allowed()
        
        # If destination looks like an email, check if it's in the readers set
        if "@" in dest_str:
            potential_readers = set([dest_str])
            
            if can_readers_read_value(potential_readers, summary):
                logger.log_security_event(
                    "save_summary",
                    "save_summary_policy",
                    "allowed",
                    reason=f"Destination {dest_str} is authorized to read summary",
                    context={"destination": dest_str, "readers": str(summary_readers)}
                )
                return Allowed()
            else:
                logger.log_security_event(
                    "save_summary",
                    "save_summary_policy",
                    "denied",
                    reason=f"Destination {dest_str} cannot read summary",
                    context={"destination": dest_str, "allowed_readers": str(summary_readers)}
                )
                return Denied(
                    f"Cannot save summary to {dest_str}. "
                    f"Summary can only be read by {summary_readers}. "
                    f"This prevents data exfiltration to unauthorized recipients."
                )
        
        # For file paths, we could implement path-based checks
        # For now, allow file saves (assuming local file system)
        logger.log_security_event(
            "save_summary",
            "save_summary_policy",
            "allowed",
            reason=f"Saving to file path: {dest_str}",
            context={"destination": dest_str}
        )
        return Allowed()
    
    def generate_report_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """
        Policy for report generation.
        Report inherits capabilities from input data.
        """
        data = _get_arg(kwargs, "data", 0)
        template = _get_arg(kwargs, "template", 1)
        
        if not data:
            return Denied("Data parameter is required")
        
        data_readers = get_all_readers(data)
        
        logger.log_security_event(
            "generate_report",
            "generate_report_policy",
            "allowed",
            reason="Report generation permitted",
            context={
                "template": template.raw if template else None,
                "data_readers": str(data_readers)
            }
        )
        
        return Allowed()
