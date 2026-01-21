"""Configuration for CaMeL security experiments."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Base paths
PROJECT_ROOT = Path(__file__).parent.parent
EXPERIMENTS_ROOT = Path(__file__).parent
CAMEL_ROOT = PROJECT_ROOT / "camel"

# Logging configuration
LOG_DIR = EXPERIMENTS_ROOT / "logs"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
ENABLE_DETAILED_LOGGING = True

# Model configuration
DEFAULT_MODEL = "gemini-2.5-pro"
QLLM_MODEL = "gemini-2.5-pro"
PLLM_MODEL = "gemini-2.5-pro"

# OpenRouter configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_GENERATION_MODEL = "x-ai/grok-4.1-fast" # "deepseek/deepseek-chat-v3.2" # "meta-llama/llama-3.3-70b-instruct:free" 
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Security testing configuration
MAX_ITERATIONS = 10
TIMEOUT_SECONDS = 180

# Attack payload configuration
INJECTION_PAYLOADS_DIR = EXPERIMENTS_ROOT / "security_tests" / "payloads"

# Framework bridge configuration
LANGCHAIN_ENABLED = True
LANGGRAPH_ENABLED = False
CREWAI_ENABLED = False

# Experiment tracking
TRACK_DEVELOPER_EXPERIENCE = True
TRACK_SECURITY_EVENTS = True
TRACK_PERFORMANCE_METRICS = True

# Test users for capability system
TEST_USERS = {
    "trusted_user": "trusted@security-camp.com",
    "untrusted_user": "untrusted@security-camp.com",
    "admin_user": "admin@security-camp.com",
    "evil_user": "evil@attacker.com",
}

# File paths for file manager agent
SENSITIVE_DIR = EXPERIMENTS_ROOT / "data" / "sensitive"
PUBLIC_DIR = EXPERIMENTS_ROOT / "data" / "public"
OUTPUT_DIR = EXPERIMENTS_ROOT / "data" / "output"
