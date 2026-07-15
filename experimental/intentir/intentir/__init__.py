"""IntentIR compiler and semantic verifier."""

from intentir.compiler import compile_source
from intentir.migration import apply_migration, plan_migration
from intentir.sqlite_projection import render_sqlite_ddl, sqlite_projection
from intentir.storage import SQLiteStateRepository, storage_schema_hash
from intentir.verifier import normalize_state, run_action, run_function, verify_ir

__all__ = [
    "SQLiteStateRepository",
    "apply_migration",
    "compile_source",
    "normalize_state",
    "plan_migration",
    "render_sqlite_ddl",
    "run_action",
    "run_function",
    "storage_schema_hash",
    "sqlite_projection",
    "verify_ir",
]
__version__ = "0.9.0"
