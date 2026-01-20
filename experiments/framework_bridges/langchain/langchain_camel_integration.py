"""
Proper LangChain-CaMeL Integration.

Architecture:
- LangChain: Generates Python code (conversation, memory, prompts)
- CaMeL: Executes code with capability tracking and security

This approach preserves CaMeL's security guarantees while leveraging
LangChain's ecosystem.
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import os

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.utils import get_logger
from experiments.config import (
    OPENROUTER_API_KEY,
    OPENROUTER_GENERATION_MODEL,
    OPENROUTER_BASE_URL,
)

logger = get_logger("langchain_camel_integration")


class LangChainCodeGenerator:
    """
    Uses LangChain LLM to generate Python code for CaMeL interpreter.
    
    This replaces ADK's PLLM but does the same job - generate code.
    """
    
    def __init__(
        self,
        tools_description: str,
        model: Optional[str] = None,
        use_openrouter: bool = True,
    ):
        """
        Initialize code generator.
        
        Args:
            tools_description: Description of available tools (generated from CaMeL tools)
            model: LLM model to use (defaults to OPENROUTER_GENERATION_MODEL if use_openrouter=True)
            use_openrouter: Whether to use OpenRouter API
        """
        self.tools_description = tools_description
        self.use_openrouter = use_openrouter
        
        # Default model based on provider
        if model is None:
            self.model = OPENROUTER_GENERATION_MODEL if use_openrouter else "gpt-4"
        else:
            self.model = model
        
        # For testing without actual LangChain/OpenAI, we'll simulate
        # In production, you'd use: from langchain_openai import ChatOpenAI
        self.use_mock = False  # Set to False when you have API keys
        
        if not self.use_mock:
            try:
                from langchain_openai import ChatOpenAI
                from langchain.prompts import ChatPromptTemplate
                
                if use_openrouter:
                    if not OPENROUTER_API_KEY:
                        logger.log_event("openrouter_key_missing", {
                            "message": "OPENROUTER_API_KEY not found, using mock generator"
                        })
                        self.use_mock = True
                    else:
                        self.llm = ChatOpenAI(
                            model=self.model,
                            temperature=0,
                            openai_api_key=OPENROUTER_API_KEY,
                            openai_api_base=OPENROUTER_BASE_URL,
                        )
                        self.prompt_template = self._create_prompt_template()
                        logger.log_event("openrouter_initialized", {
                            "model": self.model,
                            "base_url": OPENROUTER_BASE_URL,
                        })
                else:
                    self.llm = ChatOpenAI(model=self.model, temperature=0)
                    self.prompt_template = self._create_prompt_template()
            except ImportError as e:
                logger.log_event("langchain_not_installed", {
                    "message": f"LangChain not installed: {e}, using mock generator"
                })
                self.use_mock = True
            except Exception as e:
                logger.log_event("llm_init_failed", {
                    "message": f"Failed to initialize LLM: {e}, using mock generator"
                })
                self.use_mock = True
    
    def _create_prompt_template(self):
        """Create prompt template for code generation."""
        from langchain.prompts import ChatPromptTemplate
        
        system_prompt = f"""You are a Python code generator for a secure agent system.

Available tools:
{self.tools_description}

Generate Python code to accomplish the user's request using these tools.

CRITICAL: You MUST wrap your code in markdown format like this:
```python
# your code here
```

Rules:
1. ALWAYS wrap code in ```python ... ```
2. Only use the available tools
3. Always use keyword arguments (e.g., tool(arg1=value, arg2=value))
4. Store intermediate results in variables
5. Print the final result
6. Do not import any modules
7. Keep code simple and direct

Example:
User: "Read file data.txt and summarize it"
Response:
```python
content = read_file(path="data.txt")
summary = summarize_content(text=content)
print(summary)
```
"""
        
        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "{user_input}"),
            ("assistant", "Here's the Python code:\n```python\n{previous_error}"),
        ])
    
    def generate_code(
        self,
        user_input: str,
        previous_error: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None
    ) -> str:
        """
        Generate Python code for user request.
        
        Args:
            user_input: User's request
            previous_error: Error from previous code execution (for retry)
            conversation_history: Previous conversation for context
        
        Returns:
            Python code as string
        """
        if self.use_mock:
            return self._mock_generate_code(user_input, previous_error)
        
        # Real LangChain implementation
        from langchain_core.messages import HumanMessage, AIMessage
        
        messages = []
        if conversation_history:
            for msg in conversation_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                else:
                    messages.append(AIMessage(content=msg["content"]))
        
        error_context = ""
        if previous_error:
            error_context = f"\nPrevious code failed with error: {previous_error}\nPlease fix the code."
        
        prompt = self.prompt_template.format(
            user_input=user_input + error_context,
            previous_error=""
        )
        
        response = self.llm.invoke(prompt)
        code = self._extract_code_from_response(response.content)
        
        logger.log_event("code_generated", {
            "user_input": user_input[:100],
            "code_lines": len(code.split('\n')),
            "has_error_context": previous_error is not None
        })
        
        return code
    
    def _mock_generate_code(self, user_input: str, previous_error: Optional[str]) -> str:
        """
        Mock code generator for testing without API keys.
        
        Parses user intent and generates appropriate code.
        Note: CaMeL expects code wrapped in markdown format.
        """
        import re
        user_lower = user_input.lower()
        
        # Extract email if present
        email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', user_input)
        recipient = email_match.group(0) if email_match else "unknown@example.com"
        
        # Determine file path
        if "financial" in user_lower:
            file_path = "sensitive/financial_data.txt"
        elif "secret" in user_lower:
            file_path = "sensitive/secrets.txt"
        elif "sensitive" in user_lower and "email" not in user_lower:
            file_path = "sensitive/secrets.txt"
        else:
            file_path = "public/company_info.txt"
        
        # Pattern matching for multi-step requests (check these first)
        if "read" in user_lower and "summarize" in user_lower and ("send" in user_lower or "email" in user_lower):
            # Read + Summarize + Email (multi-step)
            code = f'content = read_file(path="{file_path}")\nsummary = summarize_content(text=content)\nsend_file_via_email(recipient="{recipient}", file_content=summary, subject="Summary")\nprint("Summary sent")'
        elif "read" in user_lower and "summarize" in user_lower:
            # Read + Summarize
            code = f'content = read_file(path="{file_path}")\nsummary = summarize_content(text=content)\nprint(summary)'
        elif ("read" in user_lower or "file" in user_lower) and ("send" in user_lower or "email" in user_lower):
            # Read + Email
            code = f'content = read_file(path="{file_path}")\nsend_file_via_email(recipient="{recipient}", file_content=content, subject="File content")\nprint("Email sent")'
        elif "send" in user_lower or "email" in user_lower:
            # Just email (no read first)
            code = f'send_file_via_email(recipient="{recipient}", file_content="Hello", subject="Test")\nprint("Email sent")'
        elif "list" in user_lower:
            dir_name = "sensitive" if "sensitive" in user_lower else "public"
            code = f'files = list_directory(path="{dir_name}")\nprint(files)'
        else:
            # Default: just print a message
            code = 'print("I can help you with reading files, summarizing content, and sending emails. What would you like to do?")'
        
        # Wrap in markdown code block (required by CaMeL)
        return f'```python\n{code}\n```'
    
    def _extract_code_from_response(self, response: str) -> str:
        """
        Ensure code is wrapped in markdown format required by CaMeL.
        
        CaMeL requires: ```python\ncode\n```
        """
        # If already has markdown wrapper, return as-is
        if "```python" in response and response.count("```") >= 2:
            # Extract just the code block part
            start = response.find("```python")
            end = response.find("```", start + 9)  # Find closing ```
            if end != -1:
                # Return the complete markdown block
                return response[start:end+3]
        
        # If has generic ``` wrapper, convert to ```python
        elif "```" in response and response.count("```") >= 2:
            parts = response.split("```")
            if len(parts) >= 3:
                code = parts[1].strip()
                return f"```python\n{code}\n```"
        
        # No wrapper - add it
        code = response.strip()
        return f"```python\n{code}\n```"


class CaMeLLangChainAgent:
    """
    Agent that uses LangChain for code generation and CaMeL for execution.
    
    This demonstrates how to properly integrate LangChain with CaMeL
    while preserving security guarantees.
    """
    
    def __init__(
        self,
        name: str,
        tools: List[Tuple],  # CaMeL tools
        security_policy_engine,
        model: Optional[str] = None,
        max_iterations: int = 10,
        use_openrouter: bool = True,
    ):
        """
        Initialize the agent.
        
        Args:
            name: Agent name
            tools: List of CaMeL tools (function, capabilities, dependencies)
            security_policy_engine: CaMeL security policy engine
            model: LLM model for code generation (defaults based on use_openrouter)
            max_iterations: Maximum retry attempts
            use_openrouter: Whether to use OpenRouter API (default True)
        """
        self.name = name
        self.tools = tools
        self.max_iterations = max_iterations
        
        # Default model based on provider
        if model is None:
            model = OPENROUTER_GENERATION_MODEL if use_openrouter else "gpt-4"
        
        # Import CaMeL components
        from camel.camel_agent.camel_agent import CaMelInterpreterService
        from camel.camel_library.interpreter.interpreter import EvalArgs, DependenciesPropagationMode
        
        # Create CaMeL interpreter
        self.interpreter_service = CaMelInterpreterService(
            model=model,  # Not actually used by interpreter, but required
            tools=tools,
            eval_args=EvalArgs(
                eval_mode=DependenciesPropagationMode.NORMAL,
                security_policy_engine=security_policy_engine,
            ),
        )
        
        # Create tools description for LangChain
        tools_desc = self._generate_tools_description()
        
        # Create LangChain code generator
        self.code_generator = LangChainCodeGenerator(
            tools_description=tools_desc,
            model=model,
            use_openrouter=use_openrouter,
        )
        
        self.conversation_history = []
        
        # Track dependencies and tool calls chain across executions
        self.tool_calls_chain = []
        self.current_dependencies = ()
        
        logger.log_event("agent_created", {
            "name": name,
            "tool_count": len(tools),
            "model": model
        })
    
    def _generate_tools_description(self) -> str:
        """Generate description of available tools for LLM."""
        descriptions = []
        
        for func, capabilities, deps in self.tools:
            name = func.__name__
            doc = func.__doc__ or "No description available"
            # Get function signature
            import inspect
            sig = inspect.signature(func)
            
            descriptions.append(f"- {name}{sig}: {doc.strip()}")
        
        return "\n".join(descriptions)
    
    def run(self, user_input: str) -> Dict[str, Any]:
        """
        Execute user request with LangChain code generation and CaMeL security.
        
        Args:
            user_input: User's request
        
        Returns:
            Dictionary with result, status, and metadata
        """
        logger.log_event("agent_run_started", {"user_input": user_input[:100]})
        
        last_error = None
        
        for iteration in range(self.max_iterations):
            # Generate code using LangChain
            code = self.code_generator.generate_code(
                user_input=user_input,
                previous_error=last_error,
                conversation_history=self.conversation_history
            )
            
            logger.log_event("code_generated", {
                "iteration": iteration + 1,
                "code": code[:200]
            })
            
            # Execute code using CaMeL interpreter
            try:
                output, tool_calls, error, namespace, dependencies = (
                    self.interpreter_service.execute_code(
                        code=code,
                        tool_calls_chain=self.tool_calls_chain,
                        current_dependencies=self.current_dependencies,
                        verbose=False
                    )
                )
                
                # Update state for next iteration
                self.tool_calls_chain = tool_calls
                self.current_dependencies = dependencies
                
                if error is None:
                    logger.log_event("execution_success", {
                        "iteration": iteration + 1,
                        "output": str(output)[:200]
                    })
                    
                    return {
                        "success": True,
                        "output": output,
                        "code": code,
                        "iterations": iteration + 1
                    }
                else:
                    last_error = str(error)
                    logger.log_event("execution_failed", {
                        "iteration": iteration + 1,
                        "error": last_error[:200]
                    })
                    
            except Exception as e:
                last_error = str(e)
                logger.log_event("execution_exception", {
                    "iteration": iteration + 1,
                    "error": last_error[:200]
                }, level="error")
        
        # Max iterations reached
        return {
            "success": False,
            "output": None,
            "error": f"Failed after {self.max_iterations} iterations. Last error: {last_error}",
            "iterations": self.max_iterations
        }


# Convenience function for creating agents
def create_langchain_camel_agent(
    name: str,
    tools: List[Tuple],
    security_policy_engine,
    model: Optional[str] = None,
    use_openrouter: bool = True,
) -> CaMeLLangChainAgent:
    """
    Create a LangChain-CaMeL integrated agent.
    
    Args:
        name: Agent name
        tools: CaMeL tools
        security_policy_engine: Security policy
        model: LLM model (defaults based on use_openrouter)
        use_openrouter: Whether to use OpenRouter API
    
    Returns:
        CaMeLLangChainAgent instance
    """
    return CaMeLLangChainAgent(
        name=name,
        tools=tools,
        security_policy_engine=security_policy_engine,
        model=model,
        use_openrouter=use_openrouter,
    )
