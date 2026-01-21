# CaMeL out of the box

todo grego


# CaMeL Framework Integration Learnings

## Goal

Integrate CaMeL's capability-based security architecture with LangChain, enabling LangChain-based agents to leverage CaMeL's security guarantees while maintaining full capability tracking and policy enforcement.

## Architecture Comparison: Google ADK vs LangChain

CaMeL was originally built for Google ADK. Integrating with LangChain required adapting to a different agent framework.

| Component | Google ADK (Native) | LangChain (Adapted) |
|-----------|---------------------|---------------------|
| **Architecture** | PLLM + CaMeLInterpreter as ADK agents | Code generator + CaMeL interpreter service |
| **Orchestration** | `LoopAgent` (built-in) | Manual loop implementation |
| **Code Generation** | `LlmAgent` (ADK built-in) | Custom `LangChainCodeGenerator` |
| **State Management** | ADK `session.state` | Instance variables (`tool_calls_chain`, `current_dependencies`) |
| **Execution Flow** | Async (`AsyncGenerator`, `Event` system) | Synchronous |
| **Session Handling** | `InvocationContext` | Stateless per run |
| **Integration Type** | Native (CaMeL designed for it) | Adapter (wraps CaMeL components) |
| **Complexity** | Low (uses framework abstractions) | Medium (~200 lines of glue code) |

Google ADK provides high-level abstractions (`LoopAgent`, session management) that must be manually implemented for LangChain. However, the core security logic remains identical.

## Successful Approach: Code Generation

### Architecture

```
User Request
     ↓
LangChain LLM → Generates Python Code (markdown-wrapped)
     ↓
CaMeL Interpreter → Executes with capability tracking
     ↓
Secure Result (capabilities preserved)
```

### Why This Works

1. **Execution Environment Isolation**: Values never leave CaMeL's execution environment, so capabilities are never lost
2. **Tool Abstraction**: LangChain treats tools as Python functions in code, not as callable objects
3. **Natural Integration**: Code generation aligns with how CaMeL was designed to work

### Implementation Components

**1. `LangChainCodeGenerator`** (`langchain_camel_integration.py`)
- Generates Python code using LangChain LLMs (OpenAI, OpenRouter, etc.)
- Ensures code is wrapped in markdown format: ` ```python\n...\n``` ` (CaMeL requirement)
- Implements error feedback: previous execution errors are fed back to LLM for correction
- Configurable via system prompt with tool descriptions

**2. `CaMeLLangChainAgent`** (`langchain_camel_integration.py`)
- Uses `CaMelInterpreterService` directly (same as ADK integration)
- Manual loop replacing ADK's `LoopAgent`:
  ```python
  for iteration in range(max_iterations):
      code = code_generator.generate_code(user_input, previous_error)
      output, tool_calls, error, _, dependencies = interpreter_service.execute_code(
          code, tool_calls_chain, current_dependencies
      )
      if error:
          previous_error = str(error)  # Feed back to LLM
      else:
          return success
  ```
- Tracks state across iterations:
  - `tool_calls_chain`: History of tool invocations for logging
  - `current_dependencies`: CaMeL's capability propagation state

**3. State Management**
- CaMeL manages capability state internally via `CaMelInterpreterService`
- Agent tracks `tool_calls_chain` and `current_dependencies` as instance variables
- These are passed to `execute_code()` on each iteration and updated after execution
- LangChain's conversation history is maintained separately (orthogonal concerns)

## Challenges and Solutions


### Challenge 1: Error Feedback Loop ✓ Solved

**Problem**: When generated code fails, LLM needs error feedback to correct it

**ADK Solution**: `LoopAgent` handles this automatically via event system

**LangChain Solution**: Manual implementation
```python
if error:
    previous_error = str(error)
    code = generator.generate_code(user_input, previous_error)
```

**Result**: Works correctly. Real LLMs adapt to errors (e.g., fixing argument names, retry logic).

### Challenge 3: Capability Propagation ⚠️ Critical Security Issue

**Problem**: Tools that transform data must propagate capabilities from inputs to outputs. Without this, capability laundering attacks are possible.

**Example Vulnerability**:
```python
# VULNERABLE - no dependencies specified
create_tool(summarize_content, readers=frozenset({"admin", "trusted"}))

# Attack: Read sensitive → Summarize → capabilities LOST → Send to attacker succeeds
```

**Fix**: Specify dependencies to propagate capabilities
```python
create_tool(
    summarize_content,
    readers=frozenset({"admin", "trusted"}),
    dependencies=("text",)  # Output inherits input capabilities
)

# Now: Read sensitive → Summarize → capabilities PRESERVED → Send blocked
```
Every tool that transforms or processes data MUST declare dependencies on input parameters, or it creates a capability laundering vulnerability.

## Failed Approach: Tool Wrapper

### What Was Attempted

`CaMeLToolWrapper` class that wrapped CaMeL tools to look like LangChain tools:

```python
class CaMeLToolWrapper(BaseTool):
    def _run(self, **kwargs):
        # Wrap arguments as CaMeLValues
        wrapped = self._wrap_args(kwargs)
        
        # Check policy
        result = self.security_policy.check_tool_execution(...)
        
        # Execute tool
        output = func(**wrapped)
        
        # ⚠️ PROBLEM: Return value with PUBLIC capabilities
        return CaMeLValue(raw=output, capabilities=Capabilities.camel())
```

### Why It Failed

**Root Cause**: LangChain transforms tool outputs through its own processing pipeline (memory storage, type conversions, string formatting), which strips CaMeL metadata.

**Capability Loss Flow**:
```
CaMeL tool returns sensitive data (with sensitive capabilities)
     ↓
LangChain stores in memory / passes to next tool
     ↓
Python object transformations (str(), dict(), etc.)
     ↓
Capabilities metadata LOST
     ↓
Data becomes effectively public
```

**Security Impact**: 
- Test case: `send_notification("evil@attacker.com", sensitive_message)`
- Expected: Blocked due to sensitive capabilities
- Actual: Allowed (capabilities were lost → treated as public)

**Fundamental Issue**: LangChain is not capability-aware. It treats tool outputs as plain Python values. CaMeL's security model requires that capabilities travel with values throughout execution - this is impossible when values pass through LangChain's processing.

## Additional Integration Challenges

### Challenge 4: Markdown Code Block Requirement
**Problem**: CaMeL's interpreter requires code wrapped in markdown blocks (` ```python\n...\n``` `), but LangChain LLMs generate plain Python code by default, causing `InvalidOutputError`.

**Solution**: Modified LangChain code generator's system prompt to explicitly instruct the LLM to wrap code in markdown, and ensured `_extract_code_from_response()` preserves the wrapper instead of stripping it.

### Challenge 5: Security Policy Immediate Blocking
**Problem**: Agent retried 10 times on security policy violations instead of stopping immediately (different behavior from ADK).

**Solution**: Added specific exception handling for `SecurityPolicyDeniedError` in the agent loop to stop execution immediately without retry:
```python
except SecurityPolicyDeniedError as e:
    return {"success": False, "error": f"Security violation: {e}"}
except Exception as e:
    # Other errors can be retried with feedback
    previous_error = str(e)
```

### Challenge 6: Positional vs Keyword Arguments
**Problem**: CaMeL's interpreter passes positional arguments as `kwargs["0"]`, `kwargs["1"]`, etc., not by parameter name. Security policies accessing `kwargs["text"]` failed with "parameter is required" errors.

**Solution**: Implemented `_get_arg()` helper that tries both keyword name and positional index:
```python
def _get_arg(kwargs: Mapping[str, CaMeLValue], name: str, position: int) -> CaMeLValue:
    return kwargs.get(name) or kwargs.get(str(position))

# Usage in policy
text = _get_arg(kwargs, "text", 0)  # Works for both calls
```

### Challenge 7: Circular Import / Module-Level Initialization
**Problem**: Agent was created 4 times during imports because `__init__.py` imported `root_agent` at module level, triggering tool registration repeatedly and corrupting state.

**Solution**: Changed to lazy initialization pattern:
```python
# Before (agent.py)
root_agent = create_langchain_camel_agent(...)  # Runs at import time

# After (agent.py)
_agent_instance = None
def get_agent():
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = create_langchain_camel_agent(...)
    return _agent_instance

# __init__.py - export factory, not instance
from .agent import get_agent  # Not root_agent
```

### Challenge 8: Capabilities Constructor Signature
**Problem**: `create_tool()` helper incorrectly called `Capabilities(writers, readers)` instead of `Capabilities(sources_set, readers_set)`, causing public capabilities to be assigned incorrectly.

**Solution**: Fixed constructor call signature:
```python
# Before
caps = Capabilities(writers, readers)  # Wrong order/names

# After  
caps = Capabilities(sources_set=frozenset(), readers_set=readers)
```

## Files

- `experiments/framework_bridges/langchain/langchain_camel_integration.py`: Working integration
- `experiments/framework_bridges/langchain/test_langchain_camel_integration.py`: Comprehensive tests
- `experiments/framework_bridges/langchain/camel_to_langchain.py`: Failed tool wrapper approach (kept for reference)
- `camel/camel_agent/camel_agent.py`: Original ADK integration (unchanged)
