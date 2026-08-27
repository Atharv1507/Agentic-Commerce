# Agentic Commerce Project — Agent Rules

## Project Overview
Multi-agent system for Razorpay Buildathon (Track 1: AI Growth & Agentic Commerce).
Personal Agent + Seller Agent + React Chat UI using OpenAI + FastAPI + ChromaDB + Razorpay.

## Architecture Rules

### Code Structure
- `rag.py` — ChromaDB setup and search functions only
- `tools.py` — Tool definitions (OpenAI schema) and execution logic
- `main.py` — FastAPI endpoints and LLM integration
- Keep separation of concerns strict — no business logic in endpoints

### Tool Design
- Tools are plain Python functions, not HTTP endpoints
- Tools return dicts — never raise exceptions to the caller
- Errors returned as `{"error": "error_type"}` — LLM relays to user
- All tool calls must be logged (timestamp, input, output)

### LLM Integration
- Use OpenAI function calling — no LangChain
- System prompts must be explicit about tool usage rules
- Always handle multi-round tool calls (e.g., check_stock → create_order)
- Session history capped at 20 messages to prevent token bloat

### Error Handling
- No product match → return empty list, LLM says "No products fit your description"
- Missing tool parameters → tool returns error, LLM asks for clarification
- Razorpay failures → retry once, then return error to LLM
- Never fabricate products or make up data

### Security
- API keys in `.env` files only — never hardcoded
- `.env` in `.gitignore` — never committed
- Use test mode for Razorpay during development

## Code Style

### Python
- Use type hints on all function parameters and return values
- Use `logging` module instead of `print()` statements
- Docstrings on all public functions
- f-strings for string formatting
- Maximum line length: 100 characters

### Git
- Commit messages: `type: description`
- Types: feat, fix, refactor, docs, test
- One logical change per commit
- Never commit `.env` files

## Testing Rules
- Test tool functions standalone before LLM integration
- Verify edge cases: empty results, missing parameters, API failures
- Log all tool calls for debugging
