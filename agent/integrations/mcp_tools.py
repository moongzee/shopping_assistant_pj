from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from ..core.config import SETTINGS


def _unpack_client(client: Any, error_label: str) -> Tuple[Any, Any]:
    """Normalize MCP client shape (tuple vs object)."""
    if isinstance(client, tuple):
        if len(client) == 2:
            return client  # read, write
        if len(client) == 3:
            read, write, _ = client
            return read, write
        raise ValueError(f"Unexpected {error_label} return shape")
    return client.read, client.write


async def call_mcp_tool_http(tool_name: str, arguments: dict) -> Any:
    async with streamable_http_client(SETTINGS.mcp_snowflake_url) as client:
        read, write = _unpack_client(client, "streamable_http_client")
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def call_mcp_tool_sse(tool_name: str, arguments: dict) -> Any:
    async with sse_client(SETTINGS.mcp_cortex_analyst_url) as client:
        read, write = _unpack_client(client, "sse_client")
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


def _normalize_tool_result(result: Any) -> Any:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        if "data" in result:
            return result["data"]
        if "content" in result:
            return result["content"]
        if "results" in result:
            return result["results"]
    if hasattr(result, "content"):
        content = result.content
        if isinstance(content, dict) and "data" in content:
            return content["data"]
        return content
    return result


def coerce_mcp_payload(result: Any) -> Any:
    """MCP 응답(TextContent/문자열 JSON 등)을 파이썬 dict/list로 최대한 복원."""
    if hasattr(result, "content"):
        try:
            result = result.content
        except Exception:
            pass

    if isinstance(result, list) and len(result) == 1:
        one = result[0]
        text = None
        if hasattr(one, "text"):
            text = getattr(one, "text", None)
        elif isinstance(one, dict):
            text = one.get("text")
        if isinstance(text, str):
            try:
                return json.loads(text)
            except Exception:
                return result

    if isinstance(result, dict) and isinstance(result.get("text"), str):
        try:
            return json.loads(result["text"])
        except Exception:
            return result

    if isinstance(result, str):
        try:
            return json.loads(result)
        except Exception:
            return result

    return result


def _extract_columns_from_sql(sql: Optional[str]) -> List[str]:
    if not sql:
        return []
    match = re.search(r"select\s+(.*?)\s+from", sql, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    column_segment = match.group(1)
    columns: List[str] = []
    for fragment in column_segment.split(","):
        cleaned = fragment.strip()
        if not cleaned:
            continue
        parts = re.split(r"\s+as\s+", cleaned, flags=re.IGNORECASE)
        if len(parts) == 2:
            column_name = parts[1]
        else:
            column_name = parts[0].split()[-1]
        column_name = column_name.split(".")[-1].strip('"').strip("`")
        columns.append(column_name)
    return columns


def _map_rows_to_dicts(rows: Any, columns: List[str]) -> List[dict]:
    mapped: List[dict] = []
    if isinstance(rows, dict):
        mapped.append(rows)
        return mapped
    if not isinstance(rows, list):
        return mapped
    for row in rows:
        if isinstance(row, dict):
            mapped.append(row)
            continue
        row_list = list(row) if isinstance(row, (list, tuple)) else [row]
        if columns:
            row_mapping = {col: row_list[idx] for idx, col in enumerate(columns) if idx < len(row_list)}
        else:
            row_mapping = {}
        row_mapping.setdefault("_values", row_list)
        mapped.append(row_mapping)
    return mapped


def _extract_style_codes_from_rows(rows: List[dict]) -> List[str]:
    style_codes: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = (
            row.get("STYLE_CODE")
            or row.get("style_code")
            or row.get("StyleCode")
            or row.get("styleCode")
        )
        if code and isinstance(code, str):
            style_codes.append(code)
    return style_codes



def _process_unstructured_results(payload: Any) -> tuple[List[str], List[str], str]:
    style_codes: List[str] = []
    entries = payload
    if isinstance(payload, dict) and "results" in payload:
        entries = payload["results"]
    if isinstance(entries, str):
        matches = re.findall(r"style_code\s*:\s*([A-Za-z0-9_-]+)", entries, flags=re.IGNORECASE)
        if matches:
            style_codes.extend(matches)
            style_codes = list(dict.fromkeys(style_codes))
        
    return style_codes, entries



async def execute_cortex_analyst_sql(constraints: str) -> dict:
    payload = {SETTINGS.mcp_cortex_analyst_query_param: constraints}
    raw_result = await call_mcp_tool_sse(SETTINGS.mcp_cortex_analyst_tool, payload)
    payload_obj = coerce_mcp_payload(raw_result)

    sql_text = payload_obj.get("sql") if isinstance(payload_obj, dict) else None
    if sql_text is not None and not isinstance(sql_text, str):
        sql_text = str(sql_text)

    result_text = payload_obj.get("result_text") if isinstance(payload_obj, dict) else None
    if result_text is not None and not isinstance(result_text, str):
        result_text = str(result_text)

    data_rows = None
    if isinstance(payload_obj, dict):
        data_rows = payload_obj.get("data") or payload_obj.get("results") or payload_obj.get("rows")
    if data_rows is None:
        data_rows = _normalize_tool_result(payload_obj)

    columns = _extract_columns_from_sql(sql_text)
    rows = _map_rows_to_dicts(data_rows, columns)
    style_codes = _extract_style_codes_from_rows(rows)
    return {
        "rows": rows,
        "columns": columns,
        "style_codes": style_codes,
        "sql": sql_text,
        "result_text": result_text,
        "raw_data": payload_obj,
    }


async def execute_cortex_search_rag(
    query: str,
    service_name: str = SETTINGS.mcp_cortex_search_service_name,
    database_name: str = SETTINGS.mcp_cortex_search_database_name,
    schema_name: str = SETTINGS.mcp_cortex_search_schema_name,
) -> dict:

    payload: dict = {
        "service_name": service_name,
        "database_name": database_name,
        "schema_name": schema_name,
        "query": query,
    }

    raw_result = await call_mcp_tool_http(SETTINGS.mcp_cortex_search_tool, payload)
    payload_obj = coerce_mcp_payload(raw_result)

    style_codes, review_text = _process_unstructured_results(payload_obj)
    return {
        "style_codes": style_codes,
        "review_text": review_text
    }

