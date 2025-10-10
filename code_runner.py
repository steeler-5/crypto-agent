import io
import contextlib
import pandas as pd
import re
import math
import datetime
import os
import signal
import json
import statistics
import decimal

# === Timeout Handling ===
class TimeoutException(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutException("Code execution timed out")

# === Safe Import Hook ===
def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    allowed = {"json", "math", "re", "datetime", "statistics", "decimal", "pandas"}
    if name in allowed:
        return __import__(name, globals, locals, fromlist, level)
    raise ImportError(f"⚠️ Import of '{name}' is not allowed in this sandbox")

# === Safe Globals (sandboxed) ===
restricted_globals = {
    "__builtins__": {
        "abs": abs, "min": min, "max": max, "sum": sum,
        "len": len, "range": range, "print": print, "sorted": sorted,
        "__import__": safe_import  # ✅ only safe imports allowed
    },
    "pd": pd,
    "math": math,
    "datetime": datetime,
    "re": re,
    "json": json,
    "statistics": statistics,
    "decimal": decimal
}

# === Config ===
MAX_ATTEMPTS = 3
TIMEOUT = 3  # seconds
PENDING_DIR = "pending_tools"

if not os.path.exists(PENDING_DIR):
    os.makedirs(PENDING_DIR)

# === Core Runner with Retries ===
def run_with_retries(code: str):
    errors = []
    output = io.StringIO()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(TIMEOUT)

            with contextlib.redirect_stdout(output):
                exec(code, restricted_globals)

            signal.alarm(0)  # disable alarm
            return {"success": True, "output": output.getvalue(), "errors": errors}

        except TimeoutException as e:
            errors.append(f"Attempt {attempt}: {e}")
            output = io.StringIO()
            continue

        except Exception as e:
            errors.append(f"Attempt {attempt}: {e}")
            output = io.StringIO()  # reset buffer for next try
            continue

    return {"success": False, "output": None, "errors": errors}

def sanitize_name(name: str) -> str:
    """Ensure tool name is API-safe: only a-z, A-Z, 0-9, _ and -"""
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    return safe.lower()  # optional: force lowercase for consistency

# === Tool Validation + Self-Test ===
def validate_and_save_tool(code: str):
    """Check if tool_config is valid, self-test it, and save to pending_tools/."""
    local_env = {}

    try:
        exec(code, restricted_globals, local_env)
    except Exception as e:
        return f"⚠️ Failed to execute tool code: {e}"

    if "tool_config" not in local_env:
        return "⚠️ No tool_config defined in submitted code."

    tool_config = local_env["tool_config"]
    # Sanitize tool name for OpenAI compliance
    tool_config["name"] = sanitize_name(tool_config["name"])

    # Handle case where tool_config is a list
    if isinstance(tool_config, list):
        print("⚠️ tool_config was a list, taking first element only")
        tool_config = tool_config[0]

    required_keys = {"name", "description", "parameters", "function"}
    if not required_keys.issubset(tool_config.keys()):
        return f"⚠️ Invalid tool_config. Missing keys: {required_keys - tool_config.keys()}"

    # === Normalize parameters schema ===
    params = tool_config.get("parameters")

    # Case A: shorthand list of strings
    if isinstance(params, list) and all(isinstance(p, str) for p in params):
        props = {p: {"type": "number", "description": f"{p} value"} for p in params}
        tool_config["parameters"] = {"type": "object", "properties": props, "required": params}
        print("⚠️ Converted shorthand list of strings into JSON schema.")

    # Case B: list of dicts
    elif isinstance(params, list) and all(isinstance(p, dict) for p in params):
        props, required = {}, []
        for p in params:
            name = p.get("name")
            if not name:
                continue
            props[name] = {
                "type": "number" if p.get("type") in ("float", "int", "number") else "string",
                "description": p.get("description", f"{name} value")
            }
            required.append(name)
        tool_config["parameters"] = {"type": "object", "properties": props, "required": required}
        print("⚠️ Converted list of dicts into JSON schema.")

    elif isinstance(params, dict):
        tool_config["parameters"]["type"] = "object"  # enforce type

    # === Tool Self-Test ===
    try:
        func = tool_config["function"]

        # Build sample args for test
        sample_args = {}
        if tool_config["parameters"].get("properties"):
            for key, meta in tool_config["parameters"]["properties"].items():
                if meta.get("type") == "string":
                    sample_args[key] = "test"
                elif meta.get("type") in ("number", "integer"):
                    sample_args[key] = 1
                else:
                    sample_args[key] = None

        test_result = func(**sample_args) if sample_args else func()

        # Save metadata
        filename = os.path.join(PENDING_DIR, f"{tool_config['name']}.json")
        with open(filename, "w") as f:
            json.dump({
                "name": tool_config["name"],
                "description": tool_config["description"],
                "parameters": tool_config["parameters"]
            }, f, indent=2)
        print(f"DEBUG saving tool metadata → {filename}")

        # Overwrite the tool_config inside code string with normalized version
        try:
            normalized_code = re.sub(
                r"tool_config\s*=\s*{.*}",  # match the dict block
                f"tool_config = {json.dumps(tool_config, indent=4)}",  # insert fixed version
                code,
                flags=re.DOTALL
            )
        except Exception:
            normalized_code = code  # fallback if regex fails

        # Save normalized code to pending_tools/
        py_filename = os.path.join(PENDING_DIR, f"{tool_config['name']}.py")
        with open(py_filename, "w") as f:
            f.write(normalized_code)
        print(f"DEBUG saving tool code → {py_filename}")

        return f"✅ Tool '{tool_config['name']}' validated, self-tested successfully, and saved to pending_tools/.\nSample result: {test_result}"

    except Exception as e:
        return f"⚠️ Tool '{tool_config.get('name','UNKNOWN')}' failed during self-test: {e}"


# === Public Entry Point ===
def run_code_snippet(message: str):
    match = re.search(r"run code:(.*)", message, re.DOTALL)
    if not match:
        return "Usage: run code: <your python code>"

    code = match.group(1).strip()

    # If this looks like a tool definition, handle differently
    if "tool_config" in code:
        return validate_and_save_tool(code)

    # Otherwise, just run as snippet
    result = run_with_retries(code)
    if result["success"]:
        return f"```python\n{result['output'].strip() or 'Code ran with no output.'}\n```"
    else:
        return f"```python\nAll {MAX_ATTEMPTS} attempts failed.\nErrors:\n" + "\n".join(result["errors"]) + "\n```"

# === Tool Config ===
tool_config = {
    "name": "run_code_snippet",
    "description": "Execute Python code safely with retries, error tracking, and tool validation.",
    "parameters": {
        "type": "object",
        "properties": {
            "message": {"type": "string"}
        },
        "required": ["message"]
    },
    "function": run_code_snippet
}
