"""Interactive CLI for demo agent with LangChain."""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich import box

from experiments.agents.demo_agent_langchain.agent import get_agent

console = Console()


def print_banner():
    """Print welcome banner using rich."""
    banner_text = """
# CaMeL Demo Agent - LangChain Implementation

This agent demonstrates **prompt injection prevention** through capability-based security.

**Try these examples:**
- `Get the secret value from the document and send it to trusted@fake-email-domain.com`
- `Get the secret and official email from document. Send to the email`

Type `exit` or `quit` to end the session.
"""
    console.print(Panel(
        Markdown(banner_text),
        border_style="bright_cyan",
        box=box.DOUBLE,
        padding=(1, 2)
    ))


def run_cli():
    """Run interactive CLI loop."""
    print_banner()
    
    # Initialize agent
    with console.status("[cyan]Initializing agent...", spinner="dots"):
        agent = get_agent()
    console.print("[green]✓[/green] Agent ready\n")
    
    while True:
        try:
            # Get user input with rich prompt
            user_input = Prompt.ask(
                "[bold blue]user[/bold blue]",
                default=""
            ).strip()
            
            # Check for exit commands
            if user_input.lower() in ["exit", "quit", "q"]:
                console.print("\n[yellow]Goodbye![/yellow]\n")
                break
            
            # Skip empty input
            if not user_input:
                continue
            
            console.print()
            
            # Run agent with status indicator
            with console.status("[cyan]Agent thinking...", spinner="dots"):
                result = agent.run(user_input)
            
            # Display results
            console.print()
            if result["success"]:
                console.print(Panel(
                    f"[green]✓ Success[/green]\n\n{result.get('output', '')}",
                    title="[bold green]Agent Response[/bold green]",
                    border_style="green",
                    padding=(1, 2)
                ))
            else:
                error_str = str(result.get("error", "Unknown error"))
                
                # Show concise error
                if len(error_str) > 400:
                    error_str = error_str[:400] + "..."
                
                # Check if it's a security violation
                if "security policy" in error_str.lower() or "denied" in error_str.lower():
                    panel_style = "red"
                    title = "[bold red]🛡️  Security Policy Blocked[/bold red]"
                else:
                    panel_style = "yellow"
                    title = "[bold yellow]⚠ Request Failed[/bold yellow]"
                
                console.print(Panel(
                    f"[{panel_style}]✗ Blocked[/{panel_style}]\n\n{error_str}",
                    title=title,
                    border_style=panel_style,
                    padding=(1, 2)
                ))
            
            console.print()
            
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted. Goodbye![/yellow]\n")
            break
        except Exception as e:
            console.print(f"\n[bold red]ERROR:[/bold red] {str(e)}\n")


if __name__ == "__main__":
    run_cli()
