#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Собирает узкий пакет для LLM-гейта, чтобы модель получала только нужное."""
import argparse
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from project import Project, glossary, read, section  # noqa: E402

BRIEFS = pathlib.Path(__file__).resolve().parent.parent / "briefs"


def architecture_pack(project, requirements):
    """Берёт единицы архитектуры инструментом doc-architecture, установленным в проект."""
    tool = os.environ.get("ARCH_TOOL") or str(project.root / ".doc-kit" / "doc-architecture" / "tools" / "arch.py")
    if not pathlib.Path(tool).exists():
        raise SystemExit(f"Нет {tool}: выполните doc-kit sync или задайте ARCH_TOOL")
    done = subprocess.run(
        ["uv", "run", "--quiet", tool, "pack", str(project.architecture), "--reqs", ",".join(requirements)],
        capture_output=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    if done.returncode:
        raise SystemExit(done.stderr[-800:])
    return done.stdout


def requirement_texts(prd, requirements):
    """Текст требований истории: иначе ревьюер спрашивает о том, что уже решено в PRD."""
    found = []
    for code in requirements:
        pattern = rf"^#### {code}:.*?(?=^#{{2,4}} )" if code.startswith("FR-") else rf"^- \*\*{code}\b.*$"
        match = re.search(pattern, prd, re.M | re.S if code.startswith("FR-") else re.M)
        if match:
            found.append(match.group(0).strip())
    return "# Требования истории\n\n" + "\n\n".join(found)


def criteria_only(text):
    """Оставляет названия историй и критерии, отбрасывая формулировки As a / I want."""
    keep = [line for line in text.splitlines()
            if re.match(r"(### Story|\*\*Given|\*\*When|\*\*Then|\*\*And)", line)]
    return "\n".join(keep)


def build(gate, project, target=None, source=None):
    brief = read(BRIEFS / f"{gate}.md")
    prd = read(project.prd)
    has_yaml = (project.architecture / "_order.yaml").exists()
    use_yaml = has_yaml if source is None else source == "yaml"
    if gate == "G01":
        if not target:
            raise SystemExit("G01 требует --target: файл истории")
        story = read(target)
        requirements = sorted(set(re.findall(r"\bFR-\d+|\bNFR-\d+", story)))
        architecture = architecture_pack(project, requirements) if use_yaml else read(project.spine)
        parts = [story, requirement_texts(prd, requirements), architecture, glossary(prd)]
    elif gate == "G08":
        parts = [criteria_only(read(project.epics))]
    elif gate == "G11":
        parts = [prd, read(project.spine), read(project.epics)]
        if project.experience:
            parts.append(read(project.experience))
    else:
        raise SystemExit(f"Неизвестный гейт {gate}")
    return "\n\n---\n\n".join([brief, *parts])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate")
    parser.add_argument("--root", default=".")
    parser.add_argument("--target")
    parser.add_argument("--format", choices=["yaml", "md"])
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(args.gate, Project(args.root), args.target, args.format), encoding="utf-8")
