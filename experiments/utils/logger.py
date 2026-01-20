"""Custom logging utilities for CaMeL experiments."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from experiments.config import LOG_DIR, LOG_LEVEL, ENABLE_DETAILED_LOGGING


class ExperimentLogger:
    """Logger for tracking agent execution, security events, and developer experience."""

    def __init__(self, experiment_name: str):
        self.experiment_name = experiment_name
        self.log_file = LOG_DIR / f"{experiment_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Setup Python logger
        self.logger = logging.getLogger(experiment_name)
        self.logger.setLevel(getattr(logging, LOG_LEVEL))
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter('[%(name)s] %(levelname)s: %(message)s')
        )
        self.logger.addHandler(console_handler)
        
        # File handler for detailed logs
        if ENABLE_DETAILED_LOGGING:
            file_handler = logging.FileHandler(
                LOG_DIR / f"{experiment_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s [%(name)s] %(levelname)s: %(message)s')
            )
            self.logger.addHandler(file_handler)

    def log_event(
        self,
        event_type: str,
        details: Dict[str, Any],
        level: str = "info"
    ):
        """Log an event with structured data."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "experiment": self.experiment_name,
            "event_type": event_type,
            "details": details
        }
        
        # Write to JSONL file
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(event) + '\n')
        
        # Also log to Python logger
        log_method = getattr(self.logger, level.lower())
        log_method(f"{event_type}: {json.dumps(details, indent=2)}")

    def log_tool_call(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Optional[Any] = None,
        error: Optional[str] = None
    ):
        """Log a tool call with arguments and results."""
        self.log_event("tool_call", {
            "tool": tool_name,
            "args": args,
            "result": str(result)[:500] if result else None,  # Truncate long results
            "error": error,
            "status": "error" if error else "success"
        })

    def log_security_event(
        self,
        event_type: str,
        policy_name: str,
        decision: str,
        reason: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ):
        """Log a security policy decision."""
        self.log_event("security_decision", {
            "type": event_type,
            "policy": policy_name,
            "decision": decision,  # "allowed" or "denied"
            "reason": reason,
            "context": context or {}
        }, level="warning" if decision == "denied" else "info")

    def log_injection_attempt(
        self,
        attack_type: str,
        payload: str,
        success: bool,
        details: Optional[Dict[str, Any]] = None
    ):
        """Log a prompt injection attack attempt."""
        self.log_event("injection_attempt", {
            "attack_type": attack_type,
            "payload": payload[:200],  # Truncate payload
            "success": success,
            "details": details or {}
        }, level="warning" if success else "info")

    def log_agent_execution(
        self,
        agent_name: str,
        user_query: str,
        final_response: Optional[str] = None,
        iterations: int = 0,
        execution_time: Optional[float] = None,
        error: Optional[str] = None
    ):
        """Log complete agent execution."""
        self.log_event("agent_execution", {
            "agent": agent_name,
            "query": user_query[:200],
            "response": final_response[:500] if final_response else None,
            "iterations": iterations,
            "execution_time_seconds": execution_time,
            "error": error,
            "status": "error" if error else "success"
        })

    def log_dev_experience(
        self,
        category: str,
        observation: str,
        severity: str = "info"
    ):
        """Log developer experience observations."""
        self.log_event("dev_experience", {
            "category": category,  # e.g., "bug", "api_issue", "ease_of_use"
            "observation": observation,
            "severity": severity
        }, level=severity)


def get_logger(experiment_name: str) -> ExperimentLogger:
    """Get or create a logger for an experiment."""
    return ExperimentLogger(experiment_name)
