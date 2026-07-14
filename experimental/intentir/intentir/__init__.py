"""IntentIR compiler and semantic verifier."""

from intentir.compiler import compile_source
from intentir.migration import apply_migration, plan_migration
from intentir.storage import SQLiteStateRepository, storage_schema_hash
from intentir.verifier import normalize_state, run_action, verify_ir

__all__ = [
    "SQLiteStateRepository",
    "apply_migration",
    "compile_source",
    "normalize_state",
    "plan_migration",
    "run_action",
    "storage_schema_hash",
    "verify_ir",
]
__version__ = "0.6.0"
