import io
import contextlib
import pandas as pd
import re
import math
import datetime

def run_code_snippet(message):
    match = re.search(r"run code:(.*)", message, re.DOTALL)
    if not match:
        return "Usage: run code: <your python code>"

    code = match.group(1).strip()

    restricted_globals = {
        "__builtins__": {
            "abs": abs, "min": min, "max": max, "sum": sum,
            "len": len, "range": range, "print": print, "sorted": sorted,
            "open": open  # allows reading/writing files like facts.json
        },
        "pd": pd,
        "math": math,
        "datetime": datetime,
        "re": re
    }

    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output):
            exec(code, restricted_globals)
        result = output.getvalue().strip()
        return f"```python\n{result}\n```" if result else "Code ran with no output."
    except Exception as e:
        return f"```python\nError running code: {e}\n```"
