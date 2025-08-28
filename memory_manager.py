import os
import redis
import psycopg2
from psycopg2.extras import RealDictCursor

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_DB = os.getenv("POSTGRES_DB", "rebo_memory")
POSTGRES_USER = os.getenv("POSTGRES_USER", "rebo")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "password")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))

# Connect to Redis
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True
)

# Connect to Postgres
def get_pg_connection():
    return psycopg2.connect(
        host=POSTGRES_HOST,
        database=POSTGRES_DB,
        user=POSTGRES_USER,
        password=POSTGRES_PASSWORD,
        port=POSTGRES_PORT,
        cursor_factory=RealDictCursor
    )

# Save short-term memory in Redis
def save_short_term(user_id, messages):
    redis_client.set(f"user:{user_id}:history", str(messages), ex=3600)  # 1 hour expiry

def get_short_term(user_id):
    history = redis_client.get(f"user:{user_id}:history")
    return eval(history) if history else []

# Save permanent fact in Postgres
def save_fact(category, key, value):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO facts (category, key, value) VALUES (%s, %s, %s)",
        (category, key, value)
    )
    conn.commit()
    cur.close()
    conn.close()

# Save full conversation history in Postgres
def save_long_term(user_id, messages):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO conversations (user_id, messages) VALUES (%s, %s)",
        (user_id, str(messages))
    )
    conn.commit()
    cur.close()
    conn.close()

def get_long_term(user_id, limit=10):
    conn = get_pg_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT messages FROM conversations WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    history = []
    for row in rows:
        history.extend(eval(row['messages']))
    return history
def search_facts(query, limit=5):
    """Simple keyword-based search for relevant facts in Postgres."""
    conn = get_pg_connection()
    cur = conn.cursor()

    normalized_query = query.replace(" ", "_")  # handle underscores
    cur.execute(
        """
        SELECT key, value
        FROM facts
        WHERE key ILIKE %s OR key ILIKE %s OR value ILIKE %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (f"%{query}%", f"%{normalized_query}%", f"%{query}%", limit)
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return None
    return "\n".join([f"- {row['key']}: {row['value']}" for row in rows])
