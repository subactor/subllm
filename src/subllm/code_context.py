"""LLM selection over canonical code2dsl evidence; source stays local."""
from .code_context_extraction import extract_context, read_extraction, runtime_digest
from .code_context_limits import (
    MAX_DSL_BYTES,
    MAX_EXPANDED_DSL_BYTES,
    MAX_FILE_BYTES,
    MAX_PAGES,
    MAX_SELECTED,
    MAX_SOURCE_BYTES,
    PAGE_BYTES,
)
from .code_context_primitives import digest, encode
from .code_context_records import restore_excerpt, unique_records
from .code_context_safety import safe_path
from .code_context_selection import file_inventory, file_kinds, pages, select_code_context
from .code_context_types import CodeContext

__all__ = [
    "CodeContext",
    "MAX_DSL_BYTES",
    "MAX_EXPANDED_DSL_BYTES",
    "MAX_FILE_BYTES",
    "MAX_PAGES",
    "MAX_SELECTED",
    "MAX_SOURCE_BYTES",
    "PAGE_BYTES",
    "digest",
    "encode",
    "extract_context",
    "file_inventory",
    "file_kinds",
    "pages",
    "read_extraction",
    "restore_excerpt",
    "runtime_digest",
    "safe_path",
    "select_code_context",
    "unique_records",
]
