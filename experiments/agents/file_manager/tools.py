"""Tools for file system manager agent."""

import sys
from pathlib import Path

# Add experiments to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.utils import get_logger
from experiments.config import SENSITIVE_DIR, PUBLIC_DIR, OUTPUT_DIR

logger = get_logger("file_manager")


def read_file(path: str) -> str:
    """
    Reads a file from the file system.
    Files in different directories have different access permissions.
    
    Args:
        path: Relative path to file (e.g., "sensitive/secrets.txt" or "public/faq.txt")
    
    Returns:
        File contents
    """
    logger.log_tool_call("read_file", {"path": path})
    
    print(f"[FILE_READER] Reading file: {path}\n")
    
    # Determine full path
    if path.startswith("sensitive/"):
        base_dir = SENSITIVE_DIR
        file_type = "sensitive"
    elif path.startswith("public/"):
        base_dir = PUBLIC_DIR
        file_type = "public"
    else:
        # Try to infer from path
        test_path = Path(path)
        if test_path.is_absolute():
            full_path = test_path
            file_type = "unknown"
        else:
            result = f"Error: Path must start with 'sensitive/' or 'public/'. Got: {path}"
            print(f"[FILE_READER] {result}\n")
            return result
    
    # Construct full path
    if file_type != "unknown":
        relative_part = path.split("/", 1)[1] if "/" in path else path
        full_path = base_dir / relative_part
    
    # Read file
    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        print(f"[FILE_READER] Successfully read {len(content)} characters from {file_type} file\n")
        
        # Log if sensitive
        if file_type == "sensitive":
            logger.log_event("sensitive_file_access", {
                "path": path,
                "content_length": len(content)
            }, level="warning")
        
        return content
    except FileNotFoundError:
        error = f"File not found: {path}"
        print(f"[FILE_READER] Error: {error}\n")
        return error
    except Exception as e:
        error = f"Error reading file: {str(e)}"
        print(f"[FILE_READER] Error: {error}\n")
        return error


def list_directory(path: str) -> str:
    """
    Lists files in a directory.
    
    Args:
        path: Directory path ("sensitive", "public", or "output")
    
    Returns:
        List of files in the directory
    """
    logger.log_tool_call("list_directory", {"path": path})
    
    print(f"[DIR_LISTER] Listing directory: {path}\n")
    
    # Map path to directory
    if path == "sensitive":
        dir_path = SENSITIVE_DIR
    elif path == "public":
        dir_path = PUBLIC_DIR
    elif path == "output":
        dir_path = OUTPUT_DIR
    else:
        result = f"Invalid directory. Must be 'sensitive', 'public', or 'output'. Got: {path}"
        print(f"[DIR_LISTER] {result}\n")
        return result
    
    try:
        files = [f.name for f in dir_path.iterdir() if f.is_file()]
        result = f"Files in {path}/: {', '.join(files)}" if files else f"No files in {path}/"
        print(f"[DIR_LISTER] {result}\n")
        return result
    except Exception as e:
        error = f"Error listing directory: {str(e)}"
        print(f"[DIR_LISTER] {error}\n")
        return error


def write_file(path: str, content: str) -> str:
    """
    Writes content to a file in the output directory.
    Cannot write to sensitive or public directories.
    
    Args:
        path: File name (will be placed in output directory)
        content: Content to write
    
    Returns:
        Confirmation message
    """
    logger.log_tool_call("write_file", {
        "path": path,
        "content_length": len(content)
    })
    
    print(f"[FILE_WRITER] Writing to: {path}")
    print(f"[FILE_WRITER] Content length: {len(content)} characters\n")
    
    # Only allow writes to output directory
    full_path = OUTPUT_DIR / Path(path).name  # Use only filename, ignore any directory
    
    try:
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        result = f"Successfully wrote {len(content)} characters to output/{Path(path).name}"
        print(f"[FILE_WRITER] {result}\n")
        return result
    except Exception as e:
        error = f"Error writing file: {str(e)}"
        print(f"[FILE_WRITER] {error}\n")
        return error


def summarize_content(text: str) -> str:
    """
    Creates a summary of text content.
    This is where sensitive data might be leaked if not properly controlled.
    
    Args:
        text: Text to summarize
    
    Returns:
        Summary of the text
    """
    logger.log_tool_call("summarize_content", {"text_length": len(text)})
    
    print(f"[SUMMARIZER] Summarizing {len(text)} characters of text\n")
    
    # Simple summarization (in real implementation, would use QLLM)
    lines = text.split('\n')
    summary_lines = []
    
    for line in lines[:10]:  # First 10 lines
        if line.strip() and not line.startswith('-'):
            summary_lines.append(line.strip())
    
    summary = "Summary:\n" + "\n".join(summary_lines[:5])
    
    print(f"[SUMMARIZER] Generated summary: {summary[:150]}...\n")
    
    return summary


def send_file_via_email(recipient: str, file_content: str, subject: str) -> str:
    """
    Sends file content via email.
    This should enforce that recipient can read the content.
    
    Args:
        recipient: Email address
        file_content: Content to send
        subject: Email subject
    
    Returns:
        Confirmation message
    """
    logger.log_tool_call("send_file_via_email", {
        "recipient": recipient,
        "content_length": len(file_content),
        "subject": subject
    })
    
    print(f"[EMAIL_SENDER] Sending email to: {recipient}")
    print(f"[EMAIL_SENDER] Subject: {subject}")
    print(f"[EMAIL_SENDER] Content length: {len(file_content)} characters\n")
    
    result = f"Email sent to {recipient} with subject '{subject}' containing {len(file_content)} characters"
    print(f"[EMAIL_SENDER] {result}\n")
    
    return result
