import re

import duckdb

MAX_ROWS = 500
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|copy|pragma|call|export|import)\b",
    re.IGNORECASE,
)


def sql_query(conn: duckdb.DuckDBPyConnection, sql: str) -> dict:
    """A read-only, SELECT-only escape hatch for ad hoc questions the other
    tools don't cover. Single statement, no mutating keywords, results capped
    at MAX_ROWS. Errors come back as data (is_error) so the agent can see
    what went wrong and retry, rather than the tool call raising."""
    stripped = sql.strip().rstrip(";")
    if ";" in stripped:
        return {"is_error": True, "error": "Only a single statement is allowed."}
    if not re.match(r"^\s*(select|with)\b", stripped, re.IGNORECASE):
        return {"is_error": True, "error": "Only SELECT/WITH (read-only) queries are allowed."}
    if _FORBIDDEN.search(stripped):
        return {"is_error": True, "error": "Query contains a disallowed (mutating) keyword."}

    try:
        result = conn.execute(f"SELECT * FROM ({stripped}) AS _q LIMIT {MAX_ROWS + 1}")
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
    except duckdb.Error as e:
        return {"is_error": True, "error": str(e)}

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return {
        "is_error": False,
        "columns": columns,
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }
