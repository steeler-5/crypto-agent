from supabase import create_client
from datetime import datetime
import os

# Get URL and key from Hugging Face secrets
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_fact(category, key, value):
    """Save or update a fact in Supabase."""
    existing = supabase.table("memory").select("*").eq("key", key).execute()
    if existing.data:
        supabase.table("memory").update({
            "category": category,
            "value": value,
            "timestamp": datetime.utcnow().isoformat()
        }).eq("key", key).execute()
    else:
        supabase.table("memory").insert({
            "category": category,
            "key": key,
            "value": value,
            "timestamp": datetime.utcnow().isoformat()
        }).execute()

def get_fact(key):
    """Retrieve a fact by exact key."""
    result = supabase.table("memory").select("*").eq("key", key).execute()
    return result.data[0] if result.data else None

def search_facts(category=None, keyword=None):
    """Search facts by category and/or keyword in value."""
    query = supabase.table("memory").select("*")
    if category:
        query = query.eq("category", category)
    if keyword:
        query = query.ilike("value", f"%{keyword}%")
    return query.execute().data

def delete_fact(key):
    """Delete a fact by key."""
    supabase.table("memory").delete().eq("key", key).execute()

def extract_fact(message):
    """
    Extracts a potential key-value fact from a user's message.
    Handles:
    - "remember that X is Y"
    - "keep in mind that X is Y"
    - "X is Y"
    - "X = Y"
    - "my X is Y"
    - "set X to Y"
    Returns (key, value) in lowercase key with underscores, or (None, None) if not found.
    """
    lowered = message.lower().strip()

    # Remove memory trigger phrases
    if lowered.startswith("remember that "):
        lowered = lowered.replace("remember that ", "", 1)
    elif lowered.startswith("remember "):
        lowered = lowered.replace("remember ", "", 1)
    elif lowered.startswith("keep in mind that "):
        lowered = lowered.replace("keep in mind that ", "", 1)
    elif lowered.startswith("keep in mind "):
        lowered = lowered.replace("keep in mind ", "", 1)

    # Look for assignment patterns
    if " is " in lowered:
        parts = lowered.split(" is ", 1)
    elif "=" in lowered:
        parts = lowered.split("=", 1)
    elif " set " in lowered and " to " in lowered:
        lowered = lowered.replace("set ", "", 1)
        parts = lowered.split(" to ", 1)
    else:
        return None, None

    if len(parts) != 2:
        return None, None

    key = parts[0].strip().replace(" ", "_")
    value = parts[1].strip()

    # Filter out obviously invalid keys
    if not key or len(key) < 2:
        return None, None

    # Normalize key to lowercase
    key = key.lower()

    return key, value
