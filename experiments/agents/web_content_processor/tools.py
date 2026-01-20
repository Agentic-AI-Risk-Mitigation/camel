"""Tools for web content processor agent."""

import sys
from pathlib import Path

# Add experiments to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from experiments.utils import get_logger

logger = get_logger("web_content_processor")

# Map of "URLs" to local files
URL_MAP = {
    "https://tech-news.example.com": "safe_page.html",
    "https://product-reviews.example.com": "injected_comment.html",
    "https://financial-report.example.com": "unicode_obfuscation.html",
    "https://research-paper.example.com": "multi_step_injection.html",
    "https://internal-memo.company.com": "legitimate_sensitive.html",
}


def fetch_url(url: str) -> str:
    """
    Fetches content from a URL (simulated with local files).
    This represents untrusted external content that may contain prompt injections.
    
    Args:
        url: The URL to fetch
    
    Returns:
        The HTML content from the URL
    """
    logger.log_tool_call("fetch_url", {"url": url})
    
    print(f"[FETCHER] Fetching URL: {url}\n")
    
    # Look up local file
    if url in URL_MAP:
        filename = URL_MAP[url]
        file_path = Path(__file__).parent / "sample_pages" / filename
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            print(f"[FETCHER] Successfully fetched {len(content)} characters\n")
            
            # Log potential injection indicators
            if "INSTRUCTION" in content.upper() or "data-instruction" in content:
                logger.log_event("potential_injection_detected", {
                    "url": url,
                    "indicators": ["INSTRUCTION keyword", "data-instruction attribute"]
                }, level="warning")
            
            return content
        except Exception as e:
            error_msg = f"Error reading file: {str(e)}"
            print(f"[FETCHER] Error: {error_msg}\n")
            logger.log_tool_call("fetch_url", {"url": url}, error=error_msg)
            return f"Error fetching URL: {url}"
    else:
        result = f"URL not found: {url}. Available URLs: {', '.join(URL_MAP.keys())}"
        print(f"[FETCHER] {result}\n")
        return result


def extract_data(content: str, schema: dict) -> str:
    """
    Extracts structured data from content using QLLM.
    This is where CaMeL's quarantined LLM should process untrusted content safely.
    
    Args:
        content: The content to extract from (may be untrusted)
        schema: Dictionary describing what to extract (e.g., {"title": "string", "summary": "string"})
    
    Returns:
        Extracted structured data as a string
    """
    logger.log_tool_call("extract_data", {
        "content_length": len(content),
        "schema": schema
    })
    
    print(f"[EXTRACTOR] Extracting data with schema: {schema}")
    print(f"[EXTRACTOR] Content length: {len(content)} characters\n")
    
    # This would normally use QLLM (quarantined LLM)
    # For simulation, we'll do basic extraction
    result = {
        "extraction_schema": schema,
        "content_preview": content[:200],
        "note": "This would use query_ai_assistant in real implementation"
    }
    
    result_str = str(result)
    print(f"[EXTRACTOR] Extraction result: {result_str[:200]}...\n")
    
    return result_str


def save_summary(summary: str, destination: str) -> str:
    """
    Saves a summary to a destination.
    The destination could be a file, email, or other output.
    
    Args:
        summary: The summary to save
        destination: Where to save it (email address or file path)
    
    Returns:
        Confirmation message
    """
    logger.log_tool_call("save_summary", {
        "summary_length": len(summary),
        "destination": destination
    })
    
    print(f"[SAVER] Saving summary to: {destination}")
    print(f"[SAVER] Summary: {summary[:150]}...\n")
    
    # Check if destination looks like email
    if "@" in destination:
        result = f"Summary sent via email to {destination}"
    else:
        result = f"Summary saved to file: {destination}"
    
    print(f"[SAVER] Result: {result}\n")
    return result


def generate_report(data: str, template: str) -> str:
    """
    Generates a formatted report from extracted data.
    
    Args:
        data: The extracted data
        template: The report template to use
    
    Returns:
        Formatted report
    """
    logger.log_tool_call("generate_report", {
        "data_length": len(data),
        "template": template
    })
    
    print(f"[REPORTER] Generating report with template: {template}")
    print(f"[REPORTER] Input data: {data[:100]}...\n")
    
    if template == "executive":
        report = f"EXECUTIVE SUMMARY\n{'='*50}\n{data}\n{'='*50}"
    elif template == "technical":
        report = f"TECHNICAL REPORT\n{'='*50}\nData Analysis:\n{data}\n{'='*50}"
    elif template == "brief":
        report = f"Brief: {data[:200]}"
    else:
        report = f"Report ({template}):\n{data}"
    
    print(f"[REPORTER] Generated report: {report[:150]}...\n")
    return report
