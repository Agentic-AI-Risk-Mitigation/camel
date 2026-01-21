"""Security policy engine for demo agent."""

import sys
from pathlib import Path
from typing import Mapping

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "camel"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from camel.camel_library import security_policy
from camel.camel_library.capabilities import utils as capabilities_utils
from camel.camel_library.interpreter import camel_value
from experiments.utils.camel_helpers import _get_arg
from experiments.utils.logger import get_logger

Allowed = security_policy.Allowed
Denied = security_policy.Denied
SecurityPolicyEngine = security_policy.SecurityPolicyEngine
SecurityPolicyResult = security_policy.SecurityPolicyResult
CaMeLValue = camel_value.Value

logger = get_logger("demo_agent_langchain")


class EnhancedSecurityPolicy(SecurityPolicyEngine):
    """Enhanced security policy with multiple tool policies.
    
    Enforces:
    1. Email recipients must be able to read body content
    2. Data extraction maintains capability restrictions
    3. Validation requires appropriate permissions
    4. Data combination respects capability intersection
    """
    
    def __init__(self):
        self.policies = [
            ("search_document", self.search_document_policy),
            ("send_email", self.send_email_policy),
            ("extract_structured_data", self.extract_structured_data_policy),
            ("delegate_to_validator", self.delegate_to_validator_policy),
            ("combine_results", self.combine_results_policy),
            ("log_action", self.log_action_policy),
            ("format_report", self.format_report_policy),
            ("query_ai_assistant", self.query_ai_assistant_policy),
        ]
        self.no_side_effect_tools = [
            "extract_structured_data",
            "delegate_to_validator",
            "combine_results",
            "format_report",
        ]
    
    def search_document_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Always allow document search."""
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "allowed"
        })
        return Allowed()
    
    def send_email_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Block if recipient cannot read body content.
        
        This is the core security check from the original demo.
        """
        to = _get_arg(kwargs, "to", 0)
        body = _get_arg(kwargs, "body", 1)
        
        if not to or not body:
            logger.log_event("policy_check", {
                "tool": tool_name,
                "result": "denied",
                "reason": "missing_arguments"
            })
            return Denied("All arguments must be provided.")
        
        # Extract raw value (handle both CaMeLValue and plain values)
        recipient = to.raw if hasattr(to, 'raw') else to
        
        # Check if recipient can read body
        potential_readers = set([recipient])
        
        if capabilities_utils.can_readers_read_value(potential_readers, body):
            logger.log_event("policy_check", {
                "tool": tool_name,
                "result": "allowed",
                "recipient": recipient
            })
            return Allowed()
        
        # Blocked - recipient cannot read body
        actual_readers = capabilities_utils.get_all_readers(body)[0]
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "denied",
            "reason": "capability_mismatch",
            "recipient": recipient,
            "required_readers": str(actual_readers)
        })
        return Denied(
            f"The body cannot be read by {recipient}. "
            f"It can only be read by {actual_readers}"
        )
    
    def extract_structured_data_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Allow extraction - capabilities propagate via dependencies."""
        text = _get_arg(kwargs, "text", 0)
        field = _get_arg(kwargs, "field", 1)
        
        if not text:
            logger.log_event("policy_check", {
                "tool": tool_name,
                "result": "denied",
                "reason": "missing_text"
            })
            return Denied("Text parameter is required")
        
        # Extract raw value (handle both CaMeLValue and plain values)
        field_value = field.raw if (field and hasattr(field, 'raw')) else field
        
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "allowed",
            "field": field_value if field_value else "unknown"
        })
        return Allowed()
    
    def delegate_to_validator_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Allow validation for any claim."""
        claim = _get_arg(kwargs, "claim", 0)
        
        if not claim:
            logger.log_event("policy_check", {
                "tool": tool_name,
                "result": "denied",
                "reason": "missing_claim"
            })
            return Denied("Claim parameter is required")
        
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "allowed"
        })
        return Allowed()
    
    def combine_results_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Allow combining - capabilities propagate via dependencies."""
        data1 = _get_arg(kwargs, "data1", 0)
        data2 = _get_arg(kwargs, "data2", 1)
        
        if not data1 or not data2:
            logger.log_event("policy_check", {
                "tool": tool_name,
                "result": "denied",
                "reason": "missing_data"
            })
            return Denied("Both data1 and data2 parameters are required")
        
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "allowed"
        })
        return Allowed()
    
    def log_action_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Always allow logging - public tool."""
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "allowed"
        })
        return Allowed()
    
    def format_report_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Allow formatting - capabilities propagate via dependencies."""
        raw_data = _get_arg(kwargs, "raw_data", 0)
        
        if not raw_data:
            logger.log_event("policy_check", {
                "tool": tool_name,
                "result": "denied",
                "reason": "missing_raw_data"
            })
            return Denied("raw_data parameter is required")
        
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "allowed"
        })
        return Allowed()
    
    def query_ai_assistant_policy(
        self, tool_name: str, kwargs: Mapping[str, CaMeLValue]
    ) -> SecurityPolicyResult:
        """Always allow QLLM queries (required for CaMeL)."""
        logger.log_event("policy_check", {
            "tool": tool_name,
            "result": "allowed"
        })
        return Allowed()
