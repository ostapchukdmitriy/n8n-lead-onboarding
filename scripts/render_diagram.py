#!/usr/bin/env python3
"""Render docs/workflow.png from the workflow JSON files.

The diagram is generated from the *actual* node/connection data, so it never
drifts from the exported workflows. Uses Graphviz `dot` when available and
falls back to a matplotlib boxes-and-arrows drawing otherwise.

    python3 scripts/render_diagram.py            # -> docs/workflow.png
    python3 scripts/render_diagram.py out.png
"""
from __future__ import annotations

import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / "workflows"
DEFAULT_OUT = ROOT / "docs" / "workflow.png"
ORDER = ["lead-onboarding.json", "error-handler.json", "daily-digest.json"]
STICKY = "n8n-nodes-base.stickyNote"

# dark theme palette
BG = "#0f172a"
FG = "#e2e8f0"
MUTED = "#94a3b8"
EDGE = "#64748b"
CLUSTER_BG = "#111c33"
CLUSTER_BORDER = "#1e293b"

CATEGORY_COLORS = {
    "trigger": "#f97316",   # orange
    "logic": "#a78bfa",     # violet
    "crm": "#22c55e",       # green
    "email": "#38bdf8",     # sky
    "chat": "#facc15",      # yellow
    "ai": "#f472b6",        # pink
    "respond": "#2dd4bf",   # teal
    "other": "#94a3b8",
}


def category(node: dict) -> str:
    t = node["type"].lower()
    if "respondtowebhook" in t:
        return "respond"
    if any(k in t for k in ("trigger", "webhook", "cron")):
        return "trigger"
    if any(k in t for k in ("googlesheets", "hubspot", "airtable", "notion", "pipedrive")):
        return "crm"
    if "emailsend" in t or "mailersend" in t or "gmail" in t:
        return "email"
    if "telegram" in t or "slack" in t:
        return "chat"
    if "langchain" in t:
        return "ai"
    if any(k in t for k in (".if", ".code", ".set", ".switch", ".filter", ".merge")):
        return "logic"
    return "other"


def short_type(node: dict) -> str:
    return node["type"].split(".")[-1]


def load() -> list[tuple[str, dict]]:
    files = [WORKFLOW_DIR / n for n in ORDER if (WORKFLOW_DIR / n).exists()]
    files += [p for p in sorted(WORKFLOW_DIR.glob("*.json")) if p not in files]
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in files]


def edges_of(wf: dict):
    for src, groups in wf["connections"].items():
        for port_type, outputs in groups.items():
            for out_idx, targets in enumerate(outputs):
                for t in targets or []:
                    yield src, t["node"], port_type, out_idx


# --------------------------------------------------------------------------- graphviz
def q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def nid(gi: int, node: dict) -> str:
    return "n" + str(gi) + "_" + node["id"].replace("-", "_")


def wf_to_dot(gi: int, stem: str, wf: dict) -> str:
    lines = [
        "digraph n8n {",
        f'  graph [rankdir=LR, bgcolor="{BG}", fontname="Helvetica", fontcolor="{FG}", pad="0.3", nodesep="0.30", ranksep="0.55", splines=spline, dpi=144];',
        f'  node  [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=11, fontcolor="{BG}", color="{BG}", penwidth=1.2, margin="0.18,0.10"];',
        f'  edge  [color="{EDGE}", arrowsize=0.7, penwidth=1.3, fontname="Helvetica", fontsize=9, fontcolor="{MUTED}"];',
        f'  label=<<font point-size="14"><b>{html.escape(wf["name"])}</b></font><br/><font point-size="9" color="{MUTED}">workflows/{stem}.json</font>>; labelloc=t; labeljust=l;',
    ]
    for n in wf["nodes"]:
        if n["type"] == STICKY:
            continue
        col = CATEGORY_COLORS[category(n)]
        disabled = n.get("disabled", False)
        style = "filled,rounded,dashed" if disabled else "filled,rounded"
        fill = col if not disabled else "#334155"
        fc = BG if not disabled else MUTED
        sub = f'<font point-size="8">{short_type(n)}{" · disabled" if disabled else ""}</font>'
        label = f'<<b>{html.escape(n["name"])}</b><br/>{sub}>'
        extra = f', color="{col}"' if disabled else ""
        lines.append(f'  {nid(gi, n)} [label={label}, fillcolor="{fill}", fontcolor="{fc}", style="{style}"{extra}];')
    ids = {n["name"]: nid(gi, n) for n in wf["nodes"]}
    for src, dst, port, out_idx in edges_of(wf):
        attrs = []
        src_node = next(n for n in wf["nodes"] if n["name"] == src)
        if port != "main":
            attrs.append(f'style=dashed, color="{CATEGORY_COLORS["ai"]}", label="model"')
        elif src_node["type"].endswith(".if"):
            attrs.append(f'label="{"true" if out_idx == 0 else "false"}"')
        lines.append(f"  {ids[src]} -> {ids[dst]}" + (f" [{', '.join(attrs)}]" if attrs else "") + ";")
    lines.append("}")
    return "\n".join(lines)


def render_with_dot(workflows, out: Path) -> None:
    """Render each workflow with dot, then stack the panels with a header + legend using PIL."""
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    panels = []
    dot_dump = []
    for gi, (stem, wf) in enumerate(workflows):
        dot = wf_to_dot(gi, stem, wf)
        dot_dump.append(dot)
        png = subprocess.run(["dot", "-Tpng"], input=dot.encode(), check=True, capture_output=True).stdout
        panels.append(Image.open(BytesIO(png)).convert("RGB"))
    out.with_suffix(".dot").write_text("\n\n".join(dot_dump), encoding="utf-8")

    pad, gap, header_h, legend_h = 40, 36, 150, 70
    width = max(p.width for p in panels) + 2 * pad
    height = header_h + legend_h + sum(p.height for p in panels) + gap * (len(panels) - 1) + 2 * pad
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)

    def font(size, bold=False):
        for name in (["/System/Library/Fonts/HelveticaNeue.ttc", "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]):
            try:
                return ImageFont.truetype(name, size, index=1 if (bold and name.endswith(".ttc")) else 0)
            except OSError:
                continue
        return ImageFont.load_default()

    draw.text((pad, pad), "n8n Lead Onboarding Pack", fill=FG, font=font(44, bold=True))
    draw.text((pad, pad + 62), "Webhook  ->  validate  ->  dedupe  ->  CRM  ->  welcome email  ->  Telegram    |    error alerts    |    daily AI digest",
              fill=MUTED, font=font(22))

    # legend row
    x, y = pad, header_h + pad
    f_small = font(20, bold=True)
    for key in ("trigger", "logic", "crm", "email", "chat", "ai", "respond"):
        w = draw.textlength(key, font=f_small) + 34
        draw.rounded_rectangle((x, y, x + w, y + 40), radius=10, fill=CATEGORY_COLORS[key])
        draw.text((x + 17, y + 8), key, fill=BG, font=f_small)
        x += w + 14
    draw.rounded_rectangle((x, y, x + 130, y + 40), radius=10, outline=MUTED, width=2)
    draw.text((x + 17, y + 8), "disabled", fill=MUTED, font=f_small)

    y = header_h + legend_h + pad
    for p in panels:
        box = (pad - 16, y - 12, pad + p.width + 16, y + p.height + 12)
        draw.rounded_rectangle(box, radius=18, fill=CLUSTER_BG, outline=CLUSTER_BORDER, width=2)
        canvas.paste(p, (pad, y))
        y += p.height + gap
    canvas.save(out, optimize=True)


# --------------------------------------------------------------------------- matplotlib fallback
def render_with_matplotlib(workflows, out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    n_wf = len(workflows)
    fig = plt.figure(figsize=(18, 4.2 * n_wf), facecolor=BG)
    for gi, (stem, wf) in enumerate(workflows):
        ax = fig.add_subplot(n_wf, 1, gi + 1)
        ax.set_facecolor(CLUSTER_BG)
        nodes = [n for n in wf["nodes"] if n["type"] != STICKY]
        xs = [n["position"][0] for n in nodes]
        ys = [n["position"][1] for n in nodes]
        pad_x, pad_y = 160, 120
        ax.set_xlim(min(xs) - pad_x, max(xs) + pad_x + 60)
        ax.set_ylim(max(ys) + pad_y, min(ys) - pad_y)  # n8n y grows downward
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_edgecolor(CLUSTER_BORDER)
        ax.set_title(f'{wf["name"]}   ({stem}.json)', color=FG, loc="left", fontsize=12, pad=8)
        w, h = 200, 70
        centre = {}
        for n in nodes:
            x, y = n["position"]
            centre[n["name"]] = (x + w / 2, y + h / 2)
        for src, dst, port, out_idx in edges_of(wf):
            (x1, y1), (x2, y2) = centre[src], centre[dst]
            col = CATEGORY_COLORS["ai"] if port != "main" else EDGE
            arrow = FancyArrowPatch((x1 + w / 2, y1), (x2 - w / 2, y2), arrowstyle="-|>", mutation_scale=14,
                                    color=col, lw=1.4, connectionstyle="arc3,rad=0.15",
                                    linestyle="--" if port != "main" else "-")
            ax.add_patch(arrow)
            src_node = next(n for n in nodes if n["name"] == src)
            if src_node["type"].endswith(".if"):
                ax.text((x1 + x2) / 2, (y1 + y2) / 2 - 10, "true" if out_idx == 0 else "false", color=MUTED, fontsize=7, ha="center")
        for n in nodes:
            x, y = n["position"]
            disabled = n.get("disabled", False)
            col = CATEGORY_COLORS[category(n)]
            box = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=10",
                                 fc="#334155" if disabled else col, ec=col if disabled else BG,
                                 ls="--" if disabled else "-", lw=1.2)
            ax.add_patch(box)
            ax.text(x + w / 2, y + h / 2 - 8, n["name"], ha="center", va="center", fontsize=8.5, weight="bold",
                    color=MUTED if disabled else BG)
            ax.text(x + w / 2, y + h / 2 + 14, short_type(n) + (" · disabled" if disabled else ""), ha="center",
                    va="center", fontsize=6.5, color=MUTED if disabled else BG)
    fig.suptitle("n8n Lead Onboarding Pack", color=FG, fontsize=16, weight="bold", y=0.995)
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    fig.savefig(out, dpi=150, facecolor=BG)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    workflows = load()
    if shutil.which("dot"):
        render_with_dot(workflows, out)
        print(f"rendered with graphviz -> {out}")
    else:
        render_with_matplotlib(workflows, out)
        print(f"graphviz not found; rendered with matplotlib -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
