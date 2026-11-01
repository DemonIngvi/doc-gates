#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Все проверки без LLM. Запуск: uv run check.py --root <проект>

Результат: _quality/check-report.yaml. Код выхода 1 означает блокирующие замечания.
Находки уровня warning не блокируют работу.
"""
import argparse
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from project import Project, glossary, read  # noqa: E402

PLACEHOLDERS = re.compile(r"\b(TBD|TODO|FIXME|XXX|ONE_TO_TWO_SENTENCES|INVARIANT_RULES|NON_GOALS_AND_FORBIDDEN_APPROACHES)\b")
VAGUE = re.compile(r"понятн\w*|быстр\w*|удобн\w*|корректн\w*|надёжн\w*|при необходимости|и т\. ?д\.", re.I)
NEGATIVE = re.compile(r"отклон|запрещ|недоступ|нельзя|ошибк|не удал|\b4\d\d\b|без ", re.I)


def blocker(gate, where, problem):
    return {"gate": gate, "level": "blocker", "where": where, "problem": problem}


def warning(gate, where, problem):
    return {"gate": gate, "level": "warning", "where": where, "problem": problem}


def g03_story_ready(project):
    """Готовность истории к генерации: только форма, смысл проверяет G01."""
    found = []
    for path in project.stories():
        text, name = read(path), path.name
        for heading in ("## Intent", "## Tasks & Acceptance"):
            if heading not in text and "route: 'oneshot'" not in text:
                found.append(blocker("G03", name, f"Нет раздела «{heading[3:]}»"))
        if "## Open Questions" in text:
            found.append(blocker("G03", name, "Есть открытые вопросы, сначала нужно решение"))
        if PLACEHOLDERS.search(text):
            found.append(blocker("G03", name, f"Заглушка: {PLACEHOLDERS.search(text).group(0)}"))
        if "Scenario | Input" not in text:
            found.append(warning("G03", name, "Нет таблицы случаев"))
        if not re.search(r"\bFR-\d+", text):
            found.append(blocker("G03", name, "Нет ссылки на требование FR"))
    return found


def g07_traceability(project):
    """Трассировка FR и NFR. Без истории и проверки требование считается непокрытым."""
    if not (project.prd and project.epics):
        return [warning("G07", "план", "Нет PRD или эпиков, проверка пропущена")]
    prd, epics = read(project.prd), read(project.epics)
    spine = read(project.spine) if project.spine else ""
    found = []
    stories = set(re.findall(r"^### Story (\d+\.\d+):", epics, re.M))
    coverage = dict(re.findall(r"^\| FR-(\d+) \| (\d+\.\d+) \|", epics, re.M))
    for number in re.findall(r"^#### FR-(\d+):", prd, re.M):
        if number not in coverage:
            found.append(blocker("G07", f"FR-{number}", "Нет в карте покрытия"))
        elif coverage[number] not in stories:
            found.append(blocker("G07", f"FR-{number}", f"Нет истории {coverage[number]}"))
        if spine and not re.search(rf"\bFR-{number}\b", spine):
            found.append(blocker("G07", f"FR-{number}", "Нет в архитектуре"))
    covered = set(coverage.values())
    found += [blocker("G07", f"Story {s}", "Не покрывает ни один FR") for s in sorted(stories - covered)]
    body = epics[epics.find("## Epic List"):] if "## Epic List" in epics else epics
    quality = read(project.architecture / "quality.yaml") if (project.architecture / "quality.yaml").exists() else ""
    for nfr in re.findall(r"\*\*(NFR-\d+)\b", prd):
        if not re.search(rf"\b{nfr}\b", body):
            found.append(blocker("G07", nfr, "Нет ни в одной истории"))
        if nfr not in quality:
            found.append(warning("G07", nfr, "Нет сценария качества с измеримым откликом"))
    return found


def g05_terms(project):
    """Запрещённые синонимы из docs/terms-reject.txt, формат строки: синоним = термин."""
    rules = project.root / "docs" / "terms-reject.txt"
    if not rules.exists():
        return [warning("G05", "docs/terms-reject.txt", "Нет словаря синонимов")]
    found = []
    pairs = [line.split("=", 1) for line in read(rules).splitlines() if "=" in line and not line.startswith("#")]
    documents = [p for p in (project.prd, project.epics, project.spine, project.experience) if p]
    for path in documents + project.stories():
        text = re.sub(r"```.*?```", "", read(path), flags=re.S)
        for wrong, right in pairs:
            hits = len(re.findall(wrong.strip(), text, re.I))
            if hits:
                found.append(blocker("G05", path.name, f"«{wrong.strip()}» встречается {hits} раз, нужно «{right.strip()}»"))
    return found


def g08_acceptance(project):
    """Фильтр перед LLM: отмечает истории с размытыми критериями или без негативного сценария."""
    if not project.epics:
        return []
    found = []
    for title, body in re.findall(r"^### Story (\d+\.\d+: .+?)\n(.*?)(?=^### Story |^## Epic |\Z)", read(project.epics), re.M | re.S):
        criteria = body[body.find("**Acceptance Criteria:**"):]
        if not re.search(r"\*\*Given\*\*", criteria):
            found.append(blocker("G08", title, "Нет критериев Given/When/Then"))
            continue
        vague = sorted({m.group(0).lower() for m in VAGUE.finditer(criteria)})
        if vague:
            found.append(warning("G08", title, "Размытые слова: " + ", ".join(vague)))
        if not NEGATIVE.search(criteria):
            found.append(warning("G08", title, "Нет негативного сценария"))
    return found


def g12_assumptions(project):
    """Допущения должны стоять в тексте и в индексе, иначе индекс ни на что не указывает."""
    if not project.prd:
        return []
    text = read(project.prd)
    head, marker, index = text.partition("Assumptions Index")
    inline = len(re.findall(r"\[ASSUMPTION", head.split("\n", 12)[-1]))
    listed = len(re.findall(r"\[ASSUMPTION", index)) if marker else 0
    if inline != listed:
        return [blocker("G12", project.prd.name, f"Допущений в тексте {inline}, в индексе {listed}")]
    return []


def architecture_links(project):
    """Spine собирается из YAML, поэтому ручная правка считается ошибкой."""
    if not (project.architecture / "_order.yaml").exists() or not project.spine:
        return [warning("ARCH", "docs/architecture", "Архитектура ещё не переведена в YAML")]
    import hashlib

    saved = project.architecture / ".spine.sha256"
    actual = hashlib.sha256(read(project.spine).encode("utf-8")).hexdigest()
    if saved.exists() and read(saved).strip() != actual:
        return [blocker("ARCH", project.spine.name, "Spine правили вручную, правьте YAML и выполните build")]
    return []


CHECKS = [g03_story_ready, g05_terms, g07_traceability, g08_acceptance, g12_assumptions, architecture_links]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    project = Project(args.root)
    findings = [item for check in CHECKS for item in check(project)]
    blockers = [f for f in findings if f["level"] == "blocker"]
    project.quality.mkdir(exist_ok=True)
    report = {"ok": not blockers, "blockers": len(blockers), "warnings": len(findings) - len(blockers), "findings": findings}
    (project.quality / "check-report.yaml").write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for item in findings:
        print(f"{item['level']:8} {item['gate']:5} {item['where']}: {item['problem']}")
    print(f"Блокеров: {len(blockers)}, предупреждений: {len(findings) - len(blockers)}")
    sys.exit(1 if blockers else 0)


if __name__ == "__main__":
    main()
