"""Extraction, transport and selection budgets for code2dsl evidence."""
from __future__ import annotations

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_DSL_BYTES = 16 * 1024 * 1024
# Validated transport projection fits the original limit; larger input still fails closed.
MAX_EXPANDED_DSL_BYTES = 64 * 1024 * 1024
PAGE_BYTES = 48_000
MAX_PAGES = 128
MAX_SELECTED = 32
