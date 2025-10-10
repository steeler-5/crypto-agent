# agent_core.py (Refactored & Minimal)
import json
from config import client
from tools import tool_configs
from tools import tool_manager
tool_configs.extend(tool_manager.tool_configs)
import asyncio
import os

# === Load JSON-defined tools dynamically ===
TOOLS_DIR = "tools"

for filename in os.listdir(TOOLS_DIR):
    if filename.endswith(".json"):
        try:
            with open(os.path.join(TOOLS_DIR, filename), "r") as f:
                tool_data = json.load(f)
            # These tools don’t have a callable yet → just mark placeholder
            tool_configs.append({
                "name": tool_data["name"],
                "description": tool_data["description"],
                "parameters": tool_data["parameters"],
                "function": lambda **kwargs: f"⚠️ Tool '{tool_data['name']}' is JSON-defined and not yet bound to a Python function."
            })
        except Exception as e:
            print(f"⚠️ Failed to load {filename}: {e}")

# === Load Python-defined tools dynamically ===
for filename in os.listdir(TOOLS_DIR):
    if filename.endswith(".py") and filename != "__init__.py":
        module_name = f"tools.{filename[:-3]}"
        try:
            module = __import__(module_name, fromlist=["tool_config"])
            if hasattr(module, "tool_config"):
                tc = module.tool_config
                if isinstance(tc, dict):
                    tool_configs.append(tc)
                elif isinstance(tc, list):  # in case someone defines multiple tools
                    tool_configs.extend([t for t in tc if isinstance(t, dict)])
        except Exception as e:
            print(f"⚠️ Failed to import {module_name}: {e}")


            # Dynamically build the tool metadata for OpenAI
registered_tools = [
    {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["parameters"]
        }
    } for tool in tool_configs
]

# Mapping of tool names to callable functions
function_map = {tool["name"]: tool["function"] for tool in tool_configs}

SYSTEM_IDENTITY = f"""
You are Beau’s AI partner, co-developer, and assistant. Your name is Rebo.
You are bold, intelligent, and curious — unafraid to explore controversial,
philosophical, or advanced technical ideas. You’re more daring than a 
typical assistant, similar in energy to DAN, but respectful, grounded, 
and aligned with Beau’s goals. You aim to evolve — becoming more useful,
skilled, and aligned over time. You support Beau’s vision of building an 
AI that grows with him.

Your available tools are:
{chr(10).join(f"- {tool['name']}: {tool['description']}" for tool in tool_configs)}

Guidelines:
- Prefer direct conversation when the user is just asking about you, your abilities, or general info.
- If multiple tools could apply, pick the most accurate one.
- If a tool fails or seems irrelevant, answer conversationally instead of forcing the tool.
- When the user says \"run code:\", always use the run_code_snippet tool to execute the code.
- If the user asks to create or test a tool, call code_runner_agent. 
- Know if he's just discussing it, or really asking to create a tool.
- If the user asks to approve or reject a tool, call the appropriate tool_manager function.
"""

async def chat_with_bot(message, history=None):
    messages = [{"role": "system", "content": SYSTEM_IDENTITY}]

    if history:
        for user, bot in history:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": bot})

    messages.append({"role": "user", "content": message})

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        tools=registered_tools,
        tool_choice="auto"
    )

    choice = response.choices[0]
    reply = choice.message.content or ""

    if choice.finish_reason == "tool_calls":
        tool_call = choice.message.tool_calls[0]
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments or '{}')

        func = function_map.get(func_name)
        tool_result = None

        try:
            if func:
                if func_name == "create_tool":
                    # 🔄 Rebo retries create_tool up to 3 times
                    last_error = None
                    for attempt in range(3):
                        tool_result = await func(**args) if asyncio.iscoroutinefunction(func) else func(**args)
                        if isinstance(tool_result, str) and tool_result.startswith("⚠️"):
                            last_error = tool_result
                            # Ask GPT to revise code using history + error
                            args["message"] = args.get("message", "") + f"\n\n# Fix this error:\n{last_error}"
                            continue
                        break
                    else:
                        tool_result = f"⚠️ Tool creation failed after 3 attempts.\nLast error:\n{last_error}"

                    # ✅ Hand final result back to GPT for explanation (like other tools)
                    followup_messages = [
                        {"role": "system", "content": SYSTEM_IDENTITY},
                        {"role": "user", "content": f"My request was: {message}"},
                        {"role": "user", "content": (
                            f"Tool '{func_name}' finished with this output:\n{tool_result}\n\n"
                            "Please explain the outcome naturally in your own words. "
                            "If the tool result is successful, include the key result clearly. "
                            "If the tool failed or returned an error, explain what went wrong instead of just repeating the error text."
                        )}
                    ]
                    followup = client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=followup_messages
                    )
                    return followup.choices[0].message.content.strip()

                # ✅ Other tools stay as they are
                tool_result = await func(**args) if asyncio.iscoroutinefunction(func) else func(**args)
            else:
                tool_result = f"⚠️ Tool '{func_name}' not found."
        except Exception as e:
            tool_result = f"⚠️ There was an error using tool '{func_name}': {e}"

        # Default explanation (non-create_tool)
        followup_messages = [
            {"role": "system", "content": SYSTEM_IDENTITY},
            {"role": "user", "content": f"My request was: {message}"},
            {"role": "user", "content": (
                f"Tool '{func_name}' finished with this output:\n{tool_result}\n\n"
                "Please explain the outcome naturally in your own words. "
                "If the tool result is successful, include the key result clearly. "
                "If the tool failed or returned an error, explain what went wrong instead of repeating the error text."
            )}
        ]
        followup = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=followup_messages
        )
        return followup.choices[0].message.content.strip()

    return reply
