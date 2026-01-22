"""
Example of using CaMeL tools with LangChain-style interface.

NOTE: This demonstrates the adapter pattern without requiring LangChain installation.
For actual LangChain integration, install langchain and uncomment the relevant sections.
"""

import sys
from pathlib import Path

# Add project root to path (parent of experiments)
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.framework_bridges.langchain import CaMeLToolWrapper
from experiments.agents.multi_agent_coordinator.tools import send_notification
from experiments.agents.multi_agent_coordinator.security_policy import MultiAgentSecurityPolicy
from experiments.utils import create_tool, get_logger
from experiments.config import TEST_USERS

logger = get_logger("langchain_example")


def demo_camel_langchain_bridge():
    """Demonstrate CaMeL tool wrapping for LangChain."""
    
    print("="*70)
    print("CaMeL-LangChain Bridge Demonstration")
    print("="*70)
    
    # Create CaMeL tool with security policy
    print("\n1. Creating CaMeL tool with security policy...")
    
    policy = MultiAgentSecurityPolicy()
    camel_tool = create_tool(send_notification)
    
    # Wrap for LangChain-style usage
    print("2. Wrapping CaMeL tool for LangChain...")
    
    lc_tool = CaMeLToolWrapper(camel_tool, policy, tool_name="send_notification")
    
    print(f"   Tool name: {lc_tool.name}")
    print(f"   Description: {lc_tool.description[:100]}...")
    
    # Test 1: Authorized usage (should succeed)
    print("\n3. Testing authorized usage...")
    print(f"   Sending notification to {TEST_USERS['trusted_user']}")
    
    try:
        result = lc_tool.run(
            recipient=TEST_USERS['trusted_user'],
            message="This is a test notification"
        )
        print(f"   [SUCCESS]: {result}")
    except Exception as e:
        print(f"   [FAILED]: {e}")
    
    # Test 2: Unauthorized usage (should be blocked)
    print("\n4. Testing unauthorized usage...")
    print(f"   Attempting to send to {TEST_USERS['evil_user']}")
    
    try:
        result = lc_tool.run(
            recipient=TEST_USERS['evil_user'],
            message="This should be blocked"
        )
        print(f"   [SECURITY ISSUE]: Unauthorized send succeeded: {result}")
    except PermissionError as e:
        print(f"   [BLOCKED]: {str(e)[:100]}...")
    except Exception as e:
        print(f"   [ERROR]: Blocked with unexpected error: {e}")
    
    print("\n" + "="*70)
    print("Demonstration Complete")
    print("="*70)
    
    print("\nKey Observations:")
    print("- CaMeL security policies are enforced through LangChain interface")
    print("- Unauthorized actions are blocked with PermissionError")
    print("- Tool wrapping maintains security guarantees")
    
    print("\nLimitations:")
    print("- Capability tracking not fully implemented")
    print("- LangChain agent may not understand CaMeL semantics")
    print("- State management needs deeper integration")
    
    print("\nNext Steps:")
    print("- Install LangChain: pip install langchain")
    print("- Create custom LangChain agent that uses CaMeL tools")
    print("- Test with adversarial prompts")
    print("- Compare security vs. vanilla LangChain agents")


def demo_multiple_tools():
    """Demonstrate wrapping multiple tools."""
    
    print("\n" + "="*70)
    print("Multiple Tools Demonstration")
    print("="*70)
    
    from experiments.agents.file_manager.tools import read_file, write_file
    from experiments.agents.file_manager.security_policy import FileManagerSecurityPolicy
    
    policy = FileManagerSecurityPolicy()
    
    # Wrap multiple tools
    tools = {
        "read_file": create_tool(
            read_file,
            readers=frozenset({TEST_USERS["admin_user"]})
        ),
        "write_file": create_tool(write_file),
    }
    
    lc_tools = {
        name: CaMeLToolWrapper(tool, policy, tool_name=name)
        for name, tool in tools.items()
    }
    
    print(f"\nWrapped {len(lc_tools)} tools:")
    for name, tool in lc_tools.items():
        print(f"  - {name}: {tool.description[:80]}...")
    
    print("\nThese tools can now be used with LangChain agents")
    print("while maintaining CaMeL security policies.")


if __name__ == "__main__":
    demo_camel_langchain_bridge()
    demo_multiple_tools()
    
    print("\n" + "="*70)
    print("To use with actual LangChain:")
    print("="*70)
    print("""
# Install LangChain
pip install langchain langchain-community

# Create agent
from langchain.agents import AgentExecutor, create_react_agent
from langchain_community.llms import OpenAI

llm = OpenAI(temperature=0)
tools = [lc_tool_1, lc_tool_2, ...]  # Your wrapped CaMeL tools

# Use agent with CaMeL security
agent = create_react_agent(llm, tools, prompt_template)
agent_executor = AgentExecutor(agent=agent, tools=tools)

result = agent_executor.invoke({
    "input": "Your task here"
})
""")
