import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypeVar, Union

from loguru import logger
from surrealdb import AsyncSurreal, RecordID  # type: ignore

T = TypeVar("T", Dict[str, Any], List[Dict[str, Any]])


def get_database_url():
    """Get database URL with backward compatibility"""
    surreal_url = os.getenv("SURREAL_URL")
    if surreal_url:
        return surreal_url

    # Fallback to old format - WebSocket URL format
    address = os.getenv("SURREAL_ADDRESS", "localhost")
    port = os.getenv("SURREAL_PORT", "8001")
    return f"ws://{address}:{port}/rpc"


def get_database_password():
    """Get password with backward compatibility"""
    return os.getenv("SURREAL_PASSWORD") or os.getenv("SURREAL_PASS")


def parse_record_ids(obj: Any) -> Any:
    """Recursively parse and convert RecordIDs into strings."""
    if isinstance(obj, dict):
        return {k: parse_record_ids(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [parse_record_ids(item) for item in obj]
    elif isinstance(obj, RecordID):
        return str(obj)
    return obj


def ensure_record_id(value: Union[str, RecordID]) -> RecordID:
    """Ensure a value is a RecordID."""
    if isinstance(value, RecordID):
        return value
    return RecordID.parse(value)


@asynccontextmanager
async def db_connection():
    db = AsyncSurreal(get_database_url())
    await db.signin(
        {
            "username": os.environ.get("SURREAL_USER"),
            "password": get_database_password(),
        }
    )
    await db.use(
        os.environ.get("SURREAL_NAMESPACE"), os.environ.get("SURREAL_DATABASE")
    )
    try:
        yield db
    finally:
        await db.close()


async def repo_query(
    query_str: str, vars: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Execute a SurrealQL query and return the results"""

    async with db_connection() as connection:
        try:
            result = parse_record_ids(await connection.query(query_str, vars))
            if isinstance(result, str):
                raise RuntimeError(result)
            return result
        except Exception as e:
            logger.exception(e)
            raise


async def repo_create(table: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new record in the specified table"""
    # Remove 'id' attribute if it exists in data
    data.pop("id", None)
    data["created"] = datetime.now(timezone.utc)
    data["updated"] = datetime.now(timezone.utc)
    try:
        # Use SET with individual parameters so the SDK properly serializes
        # RecordID objects (nested RecordIDs inside $data dicts are not handled)
        set_clauses = []
        params = {}
        for key, value in data.items():
            param_name = f"v_{key}"
            set_clauses.append(f"`{key}` = ${param_name}")
            params[param_name] = value
        query = f"CREATE {table} SET {', '.join(set_clauses)};"
        result = await repo_query(query, params)
        return result
    except Exception as e:
        logger.exception(e)
        raise RuntimeError("Failed to create record")


async def repo_relate(
    source: str, relationship: str, target: str, data: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Create a relationship between two records with optional data"""
    if data is None:
        data = {}
    params: Dict[str, Any] = {
        "source": ensure_record_id(source),
        "target": ensure_record_id(target),
    }
    set_clauses = []
    for key, value in data.items():
        param_name = f"v_{key}"
        set_clauses.append(f"`{key}` = ${param_name}")
        params[param_name] = value
    set_part = f" SET {', '.join(set_clauses)}" if set_clauses else ""
    query = f"RELATE $source->{relationship}->$target{set_part};"
    return await repo_query(query, params)


async def repo_upsert(
    table: str, id: Optional[str], data: Dict[str, Any], add_timestamp: bool = False
) -> List[Dict[str, Any]]:
    """Create or update a record in the specified table"""
    data.pop("id", None)
    if add_timestamp:
        data["updated"] = datetime.now(timezone.utc)
    target = ensure_record_id(id) if id and ":" in id else (id or table)
    set_clauses = []
    params = {"target": target} if isinstance(target, RecordID) else {}
    for key, value in data.items():
        param_name = f"v_{key}"
        set_clauses.append(f"`{key}` = ${param_name}")
        params[param_name] = value
    target_ref = "$target" if isinstance(target, RecordID) else target
    query = f"UPSERT {target_ref} SET {', '.join(set_clauses)};"
    return await repo_query(query, params)


async def repo_update(
    table: str, id: str, data: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Update an existing record by table and id"""
    try:
        if isinstance(id, RecordID):
            record_id = id
        elif ":" in id and id.startswith(f"{table}:"):
            record_id = ensure_record_id(id)
        else:
            record_id = ensure_record_id(f"{table}:{id}")
        data.pop("id", None)
        if "created" in data and isinstance(data["created"], str):
            data["created"] = datetime.fromisoformat(data["created"])
        data["updated"] = datetime.now(timezone.utc)
        # Use SET with individual parameters so the SDK properly serializes
        # RecordID objects (nested RecordIDs inside $data dicts are not handled)
        set_clauses = []
        params = {"record_id": record_id}
        for key, value in data.items():
            param_name = f"v_{key}"
            set_clauses.append(f"`{key}` = ${param_name}")
            params[param_name] = value
        query = f"UPDATE $record_id SET {', '.join(set_clauses)};"
        result = await repo_query(query, params)
        return parse_record_ids(result)
    except Exception as e:
        raise RuntimeError(f"Failed to update record: {str(e)}")


async def repo_get_news_by_jota_id(jota_id: str) -> Dict[str, Any]:
    try:
        results = await repo_query(
            "SELECT * omit embedding FROM news where jota_id=$jota_id",
            {"jota_id": jota_id},
        )
        return parse_record_ids(results)
    except Exception as e:
        logger.exception(e)
        raise RuntimeError(f"Failed to fetch record: {str(e)}")


async def repo_delete(record_id: Union[str, RecordID]):
    """Delete a record by record id"""

    try:
        async with db_connection() as connection:
            return await connection.delete(ensure_record_id(record_id))
    except Exception as e:
        logger.exception(e)
        raise RuntimeError(f"Failed to delete record: {str(e)}")


async def repo_insert(
    table: str, data: List[Dict[str, Any]], ignore_duplicates: bool = False
) -> List[Dict[str, Any]]:
    """Create a new record in the specified table"""
    try:
        async with db_connection() as connection:
            return parse_record_ids(await connection.insert(table, data))
    except Exception as e:
        if ignore_duplicates and "already contains" in str(e):
            return []
        logger.exception(e)
        raise RuntimeError("Failed to create record")
