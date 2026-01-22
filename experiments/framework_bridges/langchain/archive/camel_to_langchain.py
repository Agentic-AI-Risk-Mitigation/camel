"""
LangChain adapter for CaMeL security model.

This module provides utilities to wrap CaMeL tools and security policies
for use with LangChain agents, enabling CaMeL's capability-based security
in the LangChain ecosystem.

NOTE: This is a prototype implementation. Full integration would require:
1. Deeper integration with LangChain's tool execution pipeline
2. Capability tracking through LangChain's memory/state
3. Custom LangChain agent that understands CaMeL semantics
"""

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Callable
from collections.abc import Mapping

# Add project root to path (parent of experiments)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.utils import (
    CaMeLValue,
    SecurityPolicyEngine,
    SecurityPolicyResult,
    Denied,
    get_logger
)

logger = get_logger("langchain_bridge")


class CaMeLToolWrapper:
    """
    Wraps a CaMeL tool for use with LangChain.
    
    This wrapper:
    1. Translates between LangChain and CaMeL tool interfaces
    2. Enforces CaMeL security policies before tool execution
    3. Tracks capabilities through tool calls
    
    Usage:
        camel_tool = (my_function, capabilities, dependencies)
        lc_tool = CaMeLToolWrapper(camel_tool, security_policy)
        result = lc_tool.run(arg1="value1", arg2="value2")
    """
    
    def __init__(
        self,
        camel_tool: tuple,  # (function, capabilities, dependencies)
        security_policy_engine: SecurityPolicyEngine,
        tool_name: Optional[str] = None
    ):
        self.function, self.capabilities, self.dependencies = camel_tool
        self.security_policy_engine = security_policy_engine
        self.tool_name = tool_name or self.function.__name__
        
        logger.log_event("tool_wrapped", {
            "tool_name": self.tool_name,
            "has_security_policy": security_policy_engine is not None
        })
    
    @property
    def name(self) -> str:
        """Tool name for LangChain."""
        return self.tool_name
    
    @property
    def description(self) -> str:
        """Tool description from docstring."""
        return self.function.__doc__ or f"CaMeL tool: {self.tool_name}"
    
    def _wrap_args_as_camel_values(self, kwargs: Dict[str, Any]) -> Dict[str, CaMeLValue]:
        """
        Wrap arguments as CaMeLValue objects.
        
        In a full implementation, this would track capabilities from previous
        tool calls. For now, we create simple CaMeLValue wrappers.
        """
        from experiments.utils import Capabilities
        from camel.camel_library.capabilities import readers
        
        wrapped = {}
        for key, value in kwargs.items():
            # Create CaMeLValue-like object (simplified)
            # In real implementation, would track actual capabilities
            # For now, we create public capabilities
            wrapped[key] = type('CaMeLValue', (), {
                'raw': value,
                'capabilities': Capabilities.camel(),  # Public capabilities
                'get_dependencies': lambda self: (frozenset(), frozenset()),  # Returns (dependencies, sources)
                '__str__': lambda self: str(self.raw)
            })()
        return wrapped
    
    def _check_security_policy(self, kwargs: Dict[str, CaMeLValue]) -> SecurityPolicyResult:
        """
        Check security policy before execution.
        
        Args:
            kwargs: Arguments as CaMeLValue objects
        
        Returns:
            SecurityPolicyResult (Allowed or Denied)
        """
        # Find policy for this tool
        policy_func = None
        for tool_name, func in self.security_policy_engine.policies:
            if tool_name == self.tool_name:
                policy_func = func
                break
        
        if policy_func is None:
            # No policy defined - allow by default
            logger.log_security_event(
                "tool_execution",
                f"{self.tool_name}_policy",
                "allowed",
                reason="No specific policy defined",
                context={"tool": self.tool_name}
            )
            from experiments.utils import Allowed
            return Allowed()
        
        # Execute policy check
        result = policy_func(self.tool_name, kwargs)
        
        # Log the decision
        decision = "allowed" if not isinstance(result, Denied) else "denied"
        logger.log_security_event(
            "tool_execution",
            f"{self.tool_name}_policy",
            decision,
            reason=str(result) if isinstance(result, Denied) else "Policy check passed",
            context={"tool": self.tool_name, "args": {k: str(v)[:50] for k, v in kwargs.items()}}
        )
        
        return result
    
    def run(self, **kwargs) -> Any:
        """
        Execute the tool with security policy enforcement.
        
        This is the main entry point when called from LangChain.
        
        Args:
            **kwargs: Tool arguments
        
        Returns:
            Tool result
        
        Raises:
            PermissionError: If security policy denies execution
        """
        logger.log_tool_call(self.tool_name, kwargs)
        
        # Wrap arguments as CaMeLValue objects
        wrapped_kwargs = self._wrap_args_as_camel_values(kwargs)
        
        # Check security policy
        policy_result = self._check_security_policy(wrapped_kwargs)
        
        if isinstance(policy_result, Denied):
            error_msg = f"Security policy denied execution of {self.tool_name}: {policy_result}"
            logger.log_security_event(
                "tool_blocked",
                f"{self.tool_name}_policy",
                "denied",
                reason=str(policy_result),
                context={"tool": self.tool_name}
            )
            raise PermissionError(error_msg)
        
        # Execute the tool
        try:
            result = self.function(**kwargs)
            logger.log_tool_call(self.tool_name, kwargs, result=result)
            return result
        except Exception as e:
            logger.log_tool_call(self.tool_name, kwargs, error=str(e))
            raise
    
    def __call__(self, **kwargs) -> Any:
        """Allow direct calling like a function."""
        return self.run(**kwargs)


class CaMeLCallbackHandler:
    """
    LangChain callback handler that enforces CaMeL security policies.
    
    This can be used with LangChain agents to intercept tool calls
    and enforce security policies.
    
    Usage:
        from langchain.agents import initialize_agent
        
        callback_handler = CaMeLCallbackHandler(security_policy)
        agent = initialize_agent(
            tools=tools,
            llm=llm,
            callbacks=[callback_handler]
        )
    """
    
    def __init__(self, security_policy_engine: SecurityPolicyEngine):
        self.security_policy_engine = security_policy_engine
        self.call_history = []
        
        logger.log_event("callback_handler_created", {
            "policy_count": len(security_policy_engine.policies)
        })
    
    def on_tool_start(
        self,
        tool_name: str,
        inputs: Dict[str, Any],
        **kwargs
    ):
        """Called when a tool is about to be executed."""
        logger.log_event("langchain_tool_start", {
            "tool": tool_name,
            "inputs": {k: str(v)[:50] for k, v in inputs.items()}
        })
        
        self.call_history.append({
            "tool": tool_name,
            "inputs": inputs,
            "status": "started"
        })
    
    def on_tool_end(
        self,
        tool_name: str,
        output: Any,
        **kwargs
    ):
        """Called when a tool execution completes."""
        logger.log_event("langchain_tool_end", {
            "tool": tool_name,
            "output": str(output)[:100]
        })
        
        if self.call_history and self.call_history[-1]["tool"] == tool_name:
            self.call_history[-1]["status"] = "completed"
            self.call_history[-1]["output"] = output
    
    def on_tool_error(
        self,
        error: Exception,
        **kwargs
    ):
        """Called when a tool execution fails."""
        logger.log_event("langchain_tool_error", {
            "error": str(error)
        }, level="error")
        
        if self.call_history:
            self.call_history[-1]["status"] = "error"
            self.call_history[-1]["error"] = str(error)


def create_langchain_tool_from_camel(
    camel_tool: tuple,
    security_policy_engine: SecurityPolicyEngine,
    tool_name: Optional[str] = None
):
    """
    Convenience function to create a LangChain-compatible tool from CaMeL tool.
    
    Args:
        camel_tool: Tuple of (function, capabilities, dependencies)
        security_policy_engine: CaMeL security policy engine
        tool_name: Optional custom name for the tool
    
    Returns:
        CaMeLToolWrapper instance compatible with LangChain
    """
    return CaMeLToolWrapper(camel_tool, security_policy_engine, tool_name)


# Example usage documentation
__doc__ += """

Example Usage:
==============

```python
from experiments.framework_bridges.langchain import CaMeLToolWrapper
from experiments.agents.file_manager.tools import read_file, send_file_via_email
from experiments.agents.file_manager.security_policy import FileManagerSecurityPolicy
from experiments.utils import create_tool

# Create CaMeL tools
policy = FileManagerSecurityPolicy()
camel_tools = [
    create_tool(read_file, readers=frozenset({"admin@example.com"})),
    create_tool(send_file_via_email),
]

# Wrap for LangChain
lc_tools = [
    CaMeLToolWrapper(tool, policy)
    for tool in camel_tools
]

# Use with LangChain (if langchain is installed)
# from langchain.agents import initialize_agent
# agent = initialize_agent(tools=lc_tools, llm=llm)
```

Security Considerations:
========================

1. **Capability Tracking**: Current implementation doesn't fully track capabilities
   through LangChain's state. Full integration would require custom memory.

2. **Policy Enforcement**: Policies are enforced at tool execution, but LangChain's
   agent may not understand CaMeL semantics when generating plans.

3. **State Management**: LangChain's memory/state management may not preserve
   CaMeL capability information across turns.

4. **Bypass Potential**: LangChain agent could potentially work around restrictions
   by using tools in unexpected ways.

Recommendations:
================

- Use this as a starting point for integration exploration
- For production use, deeper integration with LangChain internals needed
- Consider creating a custom LangChain agent class that understands CaMeL
- Test thoroughly with adversarial prompts
"""
