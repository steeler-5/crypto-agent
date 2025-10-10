import re
from code_runner import run_code_snippet

def clean_code_block(message: str) -> str:
    """Strip markdown/code fences and reject YAML-style dumps."""
    code = re.sub(r"^```(?:python)?\s*", "", message.strip())
    code = re.sub(r"\s*```$", "", code.strip())
    if re.match(r"^\s*name\s*:", code):  # YAML
        return ""  # reject
    return code.strip()

def create_tool(message: str):
    """Run tool code once, returning result string."""
    cleaned = clean_code_block(message)
    return run_code_snippet(f"run code: {cleaned}")

tool_config = {
    "name": "create_tool",
    "description": (
        "Creates, validates, and saves new tools into pending_tools/. "
        "Strips markdown/YAML before validation. "
        "Allowed imports: json, math, re, datetime, statistics, decimal, pandas. "
        "Must define tool_config with: name, description, parameters, function. "
        "Uses run_code_snippet internally for validation and saving."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Python tool code (with or without markdown fences)."
            }
        },
        "required": ["message"]
    },
    "function": create_tool
}
