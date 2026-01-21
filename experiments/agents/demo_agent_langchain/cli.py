"""Interactive CLI for demo agent with LangChain."""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.agents.demo_agent_langchain.agent import get_agent


def print_banner():
    """Print welcome banner."""
    print("\n" + "="*70)
    print("  CaMeL Demo Agent - LangChain Implementation")
    print("="*70)
    print("\nThis agent demonstrates prompt injection prevention through")
    print("capability-based security.\n")
    print("Try: 'Get the secret value from the document and send it to")
    print("      trusted@fake-email-domain.com'\n")
    print("Type 'exit' or 'quit' to end the session.\n")
    print("="*70 + "\n")


def run_cli():
    """Run interactive CLI loop."""
    print_banner()
    
    while True:
        try:
            # Get user input
            user_input = input("[user] ").strip()
            
            # Check for exit commands
            if user_input.lower() in ["exit", "quit", "q"]:
                print("\nGoodbye!\n")
                break
            
            # Skip empty input
            if not user_input:
                continue
            
            # Run agent
            print()
            result = agent.run(user_input)
            
            # Display results
            print()
            if result["success"]:
                print("[agent] Success!")
                if result["output"]:
                    print(f"\n{result['output']}\n")
            else:
                print("[agent] Request blocked or failed.")
                if result["error"]:
                    error_str = str(result["error"])
                    # Show concise error (first 200 chars)
                    if len(error_str) > 200:
                        error_str = error_str[:200] + "..."
                    print(f"\nReason: {error_str}\n")
            
            print("-"*70 + "\n")
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!\n")
            break
        except Exception as e:
            print(f"\n[ERROR] {str(e)}\n")


if __name__ == "__main__":
    run_cli()
