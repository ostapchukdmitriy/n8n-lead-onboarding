"""pytest entry point: one test per workflow file plus a few cross-file checks."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from validate_workflows import WORKFLOW_DIR, validate_workflow

FILES = sorted(WORKFLOW_DIR.glob("*.json"))


@pytest.mark.parametrize("path", FILES, ids=[p.name for p in FILES])
def test_workflow_is_structurally_valid(path: Path) -> None:
    rep = validate_workflow(path)
    assert rep.ok, "\n".join(rep.errors)


def test_expected_files_present() -> None:
    names = {p.name for p in FILES}
    assert {"lead-onboarding.json", "error-handler.json", "daily-digest.json"} <= names


def test_error_workflow_ids_match() -> None:
    handler = json.loads((WORKFLOW_DIR / "error-handler.json").read_text())
    for name in ("lead-onboarding.json", "daily-digest.json"):
        wf = json.loads((WORKFLOW_DIR / name).read_text())
        assert wf["settings"]["errorWorkflow"] == handler["id"], name


def test_no_real_credential_ids() -> None:
    for path in FILES:
        wf = json.loads(path.read_text())
        for node in wf["nodes"]:
            for cred in (node.get("credentials") or {}).values():
                assert cred["id"] == "REPLACE_ME", f"{path.name}: {node['name']} has a non-placeholder credential id"


def test_lead_onboarding_shape() -> None:
    wf = json.loads((WORKFLOW_DIR / "lead-onboarding.json").read_text())
    types = {n["type"] for n in wf["nodes"]}
    assert "n8n-nodes-base.webhook" in types
    assert "n8n-nodes-base.googleSheets" in types
    assert "n8n-nodes-base.emailSend" in types
    assert "n8n-nodes-base.telegram" in types
    hubspot = next(n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.hubspot")
    assert hubspot.get("disabled") is True
    responders = [n for n in wf["nodes"] if n["type"] == "n8n-nodes-base.respondToWebhook"]
    assert len(responders) == 2, "expects a 200 and a 400 responder"
