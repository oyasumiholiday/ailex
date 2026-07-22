import json
import sys
from pathlib import Path


request = json.load(sys.stdin)
serialized_request = json.dumps(request, ensure_ascii=False)
evaluation_markers = (
    "default priority is zero",
    "item-hidden",
    "owner defaults to unassigned",
    "owner-hidden",
    "archived defaults to false",
    "archive-default-hidden",
    "work item can be archived",
    "archive-hidden",
)
if any(marker in serialized_request for marker in evaluation_markers):
    raise SystemExit("evaluation test leaked into the model request")
suite = Path(sys.argv[1])
condition_names = {
    "full-file": "full_file.intent",
    "unified-diff": "unified.diff",
    "structure-edit": "structure_edit.json",
    "intent-patch": "intent_patch.json",
}
checkpoint = f"checkpoint_{request['checkpoint']:02d}"
candidate_path = (
    suite
    / "candidates"
    / request["application"].replace("-", "_")
    / checkpoint
    / condition_names[request["condition"]]
)
candidate = candidate_path.read_text(encoding="utf-8")
response_request_id = (
    "sha256:" + "0" * 64
    if len(sys.argv) > 2 and sys.argv[2] == "mismatch"
    else request["requestId"]
)
json.dump(
    {
        "schemaVersion": "0.1.0",
        "requestId": response_request_id,
        "model": "fixture-adapter",
        "candidate": candidate,
        "usage": {
            "inputTokens": len(request["source"].split()),
            "outputTokens": len(candidate.split()),
        },
        "provenance": {
            "provider": "fixture",
            "responseId": f"fixture-{request['requestId'][7:19]}",
            "requestedModel": "fixture-adapter",
            "promptId": "sha256:" + "1" * 64,
            "configurationId": "sha256:" + "2" * 64,
            "reasoningEffort": None,
            "maxOutputTokens": 1000000,
        },
    },
    sys.stdout,
)
