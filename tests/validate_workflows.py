#!/usr/bin/env python3
"""Structural validator for the n8n workflow JSON files in ./workflows.

Checks (per file):
  * top-level shape: name, nodes[], connections{}
  * every node has a unique name, a type, a numeric typeVersion, [x, y] position and a parameters object
  * every connection source and target names an existing node
  * connection `index` values are non-negative integers and `type` matches the port group
  * no orphan nodes: every non-sticky node is reachable from a trigger through the
    main / ai_* connection graph (disabled nodes may be unconnected -> warning only)
  * nodes referenced from expressions as $('Node Name') exist
  * credential blocks only contain `id` and `name` (no embedded secrets)
  * no obvious secret material (API keys, bot tokens) anywhere in the file

Exit code 0 when all files pass, 1 otherwise. Also importable by pytest (see test_workflows.py).
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "workflows"

STICKY = "n8n-nodes-base.stickyNote"
TRIGGER_TYPES = {"n8n-nodes-base.webhook", "n8n-nodes-base.cron", "n8n-nodes-base.formTrigger"}
NODE_REF_RE = re.compile(r"\$\(\s*(['\"])(.+?)\1\s*\)")
SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),                 # OpenAI / Anthropic style keys
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),     # Telegram bot token
    re.compile(r"xox[abp]-[A-Za-z0-9-]{10,}"),          # Slack tokens
    re.compile(r"pat-[a-z0-9-]{20,}"),                  # HubSpot private app token
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


@dataclass
class Report:
    file: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def is_trigger(node: dict) -> bool:
    t = node.get("type", "")
    return t in TRIGGER_TYPES or t.endswith("Trigger")


def validate_workflow(path: Path) -> Report:
    rep = Report(path)
    try:
        wf = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        rep.errors.append(f"invalid JSON: {exc}")
        return rep

    for key in ("name", "nodes", "connections"):
        if key not in wf:
            rep.errors.append(f"missing top-level key '{key}'")
    if rep.errors:
        return rep
    if not isinstance(wf["nodes"], list) or not wf["nodes"]:
        rep.errors.append("'nodes' must be a non-empty list")
        return rep
    if not isinstance(wf["connections"], dict):
        rep.errors.append("'connections' must be an object")
        return rep

    # ---- nodes -----------------------------------------------------------
    names: dict[str, dict] = {}
    for i, node in enumerate(wf["nodes"]):
        label = node.get("name") or f"<node #{i}>"
        for key in ("name", "type", "typeVersion", "position", "parameters"):
            if key not in node:
                rep.errors.append(f"node {label!r}: missing '{key}'")
        if node.get("name") in names:
            rep.errors.append(f"duplicate node name {label!r}")
        names[node.get("name", label)] = node
        pos = node.get("position")
        if not (isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, (int, float)) for v in pos)):
            rep.errors.append(f"node {label!r}: position must be [x, y]")
        if not isinstance(node.get("typeVersion"), (int, float)):
            rep.errors.append(f"node {label!r}: typeVersion must be numeric")
        if not isinstance(node.get("parameters"), dict):
            rep.errors.append(f"node {label!r}: parameters must be an object")
        for cred_type, cred in (node.get("credentials") or {}).items():
            extra = set(cred) - {"id", "name"}
            if extra:
                rep.errors.append(f"node {label!r}: credential '{cred_type}' has unexpected keys {sorted(extra)} (secrets must never be embedded)")

    # ---- connections -----------------------------------------------------
    incoming: dict[str, int] = {n: 0 for n in names}
    outgoing: dict[str, int] = {n: 0 for n in names}
    adjacency: dict[str, set[str]] = {n: set() for n in names}
    for src, groups in wf["connections"].items():
        if src not in names:
            rep.errors.append(f"connection source {src!r} is not a node")
            continue
        if not isinstance(groups, dict):
            rep.errors.append(f"connections[{src!r}] must be an object of port groups")
            continue
        for port_type, outputs in groups.items():
            if not isinstance(outputs, list):
                rep.errors.append(f"connections[{src!r}][{port_type!r}] must be a list of outputs")
                continue
            for out_idx, targets in enumerate(outputs):
                if targets is None:
                    continue
                if not isinstance(targets, list):
                    rep.errors.append(f"connections[{src!r}][{port_type!r}][{out_idx}] must be a list")
                    continue
                for t in targets:
                    tgt = t.get("node")
                    if tgt not in names:
                        rep.errors.append(f"{src!r} -> {tgt!r}: target node does not exist")
                        continue
                    if t.get("type") != port_type:
                        rep.errors.append(f"{src!r} -> {tgt!r}: connection type {t.get('type')!r} != port group {port_type!r}")
                    if not isinstance(t.get("index"), int) or t["index"] < 0:
                        rep.errors.append(f"{src!r} -> {tgt!r}: index must be a non-negative integer")
                    if names[tgt]["type"] == STICKY or names[src]["type"] == STICKY:
                        rep.errors.append(f"{src!r} -> {tgt!r}: sticky notes cannot be connected")
                    incoming[tgt] += 1
                    outgoing[src] += 1
                    adjacency[src].add(tgt)

    # ---- orphans / reachability -----------------------------------------
    real_nodes = [n for n, nd in names.items() if nd["type"] != STICKY]
    triggers = [n for n in real_nodes if is_trigger(names[n])]
    if not triggers:
        rep.errors.append("workflow has no trigger node")
    for n in triggers:
        if incoming[n]:
            rep.errors.append(f"trigger {n!r} must not have incoming connections")

    reachable: set[str] = set()
    stack = list(triggers)
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        stack.extend(adjacency[cur])
    # sub-nodes (ai_* ports) feed INTO a reachable node; treat them as reachable too
    for src, groups in wf["connections"].items():
        for port_type, outputs in groups.items():
            if port_type.startswith("ai_"):
                for targets in outputs:
                    for t in targets or []:
                        if t.get("node") in reachable:
                            reachable.add(src)

    for n in real_nodes:
        if n in reachable:
            continue
        if incoming[n] == 0 and outgoing[n] == 0:
            msg = f"orphan node {n!r} (no connections)"
        else:
            msg = f"node {n!r} is not reachable from any trigger"
        if names[n].get("disabled"):
            rep.warnings.append(msg + " [disabled, allowed]")
        else:
            rep.errors.append(msg)

    # ---- expression references ------------------------------------------
    raw = path.read_text(encoding="utf-8")
    for _, ref in NODE_REF_RE.findall(json.dumps(wf)):
        ref = ref.encode().decode("unicode_escape") if "\\" in ref else ref
        if ref not in names:
            rep.errors.append(f"expression references unknown node $('{ref}')")

    # ---- secrets ---------------------------------------------------------
    for pat in SECRET_PATTERNS:
        if pat.search(raw):
            rep.errors.append(f"possible secret matches pattern /{pat.pattern}/")

    # ---- housekeeping warnings ------------------------------------------
    if wf.get("active"):
        rep.warnings.append("workflow is exported as active=true; exports should be inactive")
    if "errorWorkflow" in wf.get("settings", {}) and "errorTrigger" not in " ".join(nd["type"] for nd in names.values()):
        rep.warnings.append("settings.errorWorkflow is set; make sure the Error Handler workflow is imported and re-selected in Settings after import")
    return rep


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv[1:]] or sorted(WORKFLOW_DIR.glob("*.json"))
    if not files:
        print(f"no workflow files found in {WORKFLOW_DIR}")
        return 1
    failed = 0
    for f in files:
        rep = validate_workflow(f)
        status = "PASS" if rep.ok else "FAIL"
        print(f"[{status}] {f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}")
        for w in rep.warnings:
            print(f"    warn: {w}")
        for e in rep.errors:
            print(f"    ERROR: {e}")
        failed += not rep.ok
    print(f"\n{len(files) - failed}/{len(files)} workflow files valid")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
