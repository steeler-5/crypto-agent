import os
import shutil
import json

PENDING_DIR = "pending_tools"
TOOLS_DIR = "tools"

def list_pending_tools():
    """Return a list of all pending tools waiting for approval."""
    try:
        return os.listdir(PENDING_DIR)
    except FileNotFoundError:
        return []

def approve_tool(tool_name: str):
    """Move a tool from pending_tools/ to tools/ upon approval."""
    src = os.path.join(PENDING_DIR, f"{tool_name}.json")
    dst = os.path.join(TOOLS_DIR, f"{tool_name}.json")

    if not os.path.exists(src):
        return f"⚠️ Tool '{tool_name}' not found in pending_tools/."

    shutil.move(src, dst)

    # Move Python implementation too (if exists)
    py_src = os.path.join(PENDING_DIR, f"{tool_name}.py")
    py_dst = os.path.join(TOOLS_DIR, f"{tool_name}.py")
    if os.path.exists(py_src):
        shutil.move(py_src, py_dst)

    print(f"DEBUG approving: {tool_name}")
    return f"✅ Tool '{tool_name}' has been approved and moved to tools/."

def reject_tool(tool_name: str):
    """Delete a tool from pending_tools/."""
    src = os.path.join(PENDING_DIR, f"{tool_name}.json")

    if not os.path.exists(src):
        return f"⚠️ Tool '{tool_name}' not found in pending_tools/."

    os.remove(src)
    print(f"DEBUG rejecting: {tool_name}")
    return f"❌ Tool '{tool_name}' has been rejected and deleted from pending_tools/."

# === Tool Configs for Agent Integration ===
tool_configs = [
    {
        "name": "list_pending_tools",
        "description": "List all tools waiting in pending_tools/.",
        "parameters": {
            "type": "object",
            "properties": {}
        },
        "function": lambda: list_pending_tools()
    },
    {
        "name": "approve_tool",
        "description": "Approve a tool by moving it from pending_tools/ to tools/.",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "The tool name to approve"
                }
            },
            "required": ["tool_name"]
        },
        "function": lambda tool_name: approve_tool(tool_name)
    },
    {
        "name": "reject_tool",
        "description": "Reject a tool by deleting it from pending_tools/.",
        "parameters": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "The tool name to reject"
                }
            },
            "required": ["tool_name"]
        },
        "function": lambda tool_name: reject_tool(tool_name)
    }
]
