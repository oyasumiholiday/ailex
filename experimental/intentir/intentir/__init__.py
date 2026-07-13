"""IntentIR compiler and semantic verifier."""

from intentir.compiler import compile_source
from intentir.storage import SQLiteStateRepository, storage_schema_hash
from intentir.verifier import run_action, verify_ir

__all__ = [
    "SQLiteStateRepository",
    "compile_source",
    "run_action",
    "storage_schema_hash",
    "verify_ir",
]
__version__ = "0.5.0"
