"""IntentIR compiler and semantic verifier."""

from intentir.agent import AgentService
from intentir.compiler import compile_path, compile_source
from intentir.migration import apply_migration, plan_migration
from intentir.patch import patch_path, plan_patch_path, plan_patch_source
from intentir.sqlite_projection import render_sqlite_ddl, sqlite_projection
from intentir.storage import SQLiteStateRepository, storage_schema_hash
from intentir.verifier import normalize_state, run_action, run_function, verify_ir

__all__ = [
    "SQLiteStateRepository",
    "AgentService",
    "apply_migration",
    "compile_source",
    "compile_path",
    "normalize_state",
    "patch_path",
    "plan_migration",
    "plan_patch_path",
    "plan_patch_source",
    "render_sqlite_ddl",
    "run_action",
    "run_function",
    "storage_schema_hash",
    "sqlite_projection",
    "verify_ir",
]
__version__ = "0.14.0"
