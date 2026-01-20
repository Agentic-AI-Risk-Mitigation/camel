# CaMeL Quick Start

## Setup

```bash
poetry install
```

Add .env file to project root


## Test Google ADK Integration

```bash
poetry run adk run camel
```

Try: "Read file documents/sample_document.pdf and search for Emma in contacts"

## Test LangChain Integration

```bash
poetry run python experiments/framework_bridges/langchain/test_langchain_camel_integration.py
```

Expected: 7/7 tests pass (100%)

## What's Being Tested

Google ADK: Native CaMeL implementation with LoopAgent
LangChain: Code generation approach with manual orchestration

Both preserve identical security guarantees.
