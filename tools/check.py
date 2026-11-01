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
import blocks  # noqa: E402
import extras  # noqa: E402
import model  # noqa: E402
import scenarios  # noqa: E402
from project import Project, read  # noqa: E402

PLACEHOLDERS = re.compile(r"\b(TBD|TODO|FIXME|XXX|ONE_TO_TWO_SENTENCES|INVARIANT_RULES|NON_GOALS_AND_FORBIDDEN_APPROACHES|WHY|WHY_THIS_CLASS_CANNOT_HAPPEN_HERE)\b")
VAGUE = re.compile(r"понятн\w*|быстр\w*\b(?!\s+\d)|удобн\w*|корректн\w*|надёжн\w*|при необходимости|и т\. ?д\.", re.I)
STORY_BLOCK = re.compile(r"^### Story (\d+\.\d+: .+?)\n(.*?)(?=^### Story |^## Epic |\Z)", re.M | re.S)


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
    coverage = {}
    for number, story in re.findall(r"^\| FR-(\d+) \| (\d+\.\d+) \|", epics, re.M):
        coverage.setdefault(number, set()).add(story)
    for number in re.findall(r"^#### FR-(\d+):", prd, re.M):
        if number not in coverage:
            found.append(blocker("G07", f"FR-{number}", "Нет в карте покрытия"))
        else:
            found += [blocker("G07", f"FR-{number}", f"Нет истории {story}") for story in sorted(coverage[number] - stories)]
        if spine and not re.search(rf"\bFR-{number}\b", spine):
            found.append(blocker("G07", f"FR-{number}", "Нет в архитектуре"))
    covered = set().union(*coverage.values()) if coverage else set()
    found += [blocker("G07", f"Story {s}", "Не покрывает ни один FR") for s in sorted(stories - covered)]
    body = epics[epics.find("## Epic List"):] if "## Epic List" in epics else epics
    quality = read(project.architecture / "quality.yaml") if (project.architecture / "quality.yaml").exists() else ""
    for nfr in re.findall(r"\*\*(NFR-\d+)\b", prd):
        if not re.search(rf"\b{nfr}\b", body):
            found.append(blocker("G07", nfr, "Нет ни в одной истории"))
        if nfr not in quality:
            found.append(warning("G07", nfr, "Нет сценария качества с измеримым откликом"))
    return found


def word_pattern(wrong):
    """Звёздочка в конце значит любое окончание: «задач*» находит «задачи» и «задачами»."""
    wrong = wrong.strip()
    return rf"\b{wrong[:-1]}\w*" if wrong.endswith("*") else wrong


def g05_terms(project):
    """Запрещённые синонимы из docs/terms-reject.txt, формат строки: синоним = термин."""
    rules = project.root / "docs" / "terms-reject.txt"
    if not rules.exists():
        return [warning("G05", "docs/terms-reject.txt", "Нет словаря синонимов")]
    found = []
    pairs = [line.split("=", 1) for line in read(rules).splitlines() if "=" in line and not line.startswith("#")]
    pairs = [(word_pattern(wrong), right) for wrong, right in pairs]
    documents = [p for p in (project.prd, project.epics, project.spine, project.experience) if p]
    for path in documents + project.stories():
        text = re.sub(r"```.*?```", "", read(path), flags=re.S)
        for wrong, right in pairs:
            hits = len(re.findall(wrong, text, re.I))
            if hits:
                found.append(blocker("G05", path.name, f"«{wrong}» встречается {hits} раз, нужно «{right.strip()}»"))
    return found


def g08_acceptance(project):
    """Критерии в эпиках: размытые слова и классы S1–S12, которые угадываются по словам."""
    if not project.epics:
        return []
    found = []
    for title, body in STORY_BLOCK.findall(read(project.epics)):
        criteria = body[body.find("**Acceptance Criteria:**"):]
        if not re.search(r"\*\*Given\*\*", criteria):
            found.append(blocker("G08", title, "Нет критериев Given/When/Then"))
            continue
        vague = sorted({m.group(0).lower() for m in VAGUE.finditer(criteria)})
        if vague:
            found.append(warning("G08", title, "Размытые слова: " + ", ".join(vague)))
        classes = scenarios.guess_classes(criteria)
        if not scenarios.NEGATIVE & set(classes):
            found.append(warning("G08", title, "Нет негативного сценария S3–S6"))
        elif len(classes) < scenarios.MIN_ROWS:
            found.append(warning("G08", title, f"Мало классов: {', '.join(classes)}"))
    return found


def g08_story_classes(project):
    """Файл истории идёт в генерацию, поэтому каждый класс покрыт или объяснён явно."""
    found = []
    for path in project.stories():
        for problem in scenarios.audit_story(read(path))[1]:
            found.append(blocker("G08", path.name, problem))
    return found


def block_cards(project):
    """Битая ссылка блокирует. Неполная карточка видна в отчёте, блок просто ещё не готов."""
    found, known = [], blocks.registry(project)
    for card in blocks.cards(project):
        percent, missing, problems = blocks.audit_card(card, known)
        found += [blocker("BLOCK", card["id"], problem) for problem in problems]
        if missing:
            found.append(warning("BLOCK", card["id"], f"Заполнено {percent} %, нет: {', '.join(missing)}"))
    return found


def system_model(project):
    """Без модели проект ещё не описан, но это не ошибка: её заполняют после первого Spine."""
    if not model.present(project):
        return [warning("MODEL", "docs/architecture", "Модель системы не заполнена")]
    problems, uncovered = model.audit(project)
    found = [blocker("MODEL", key, problem) for key, problem in problems]
    found += [warning("MODEL", key, "Параметры канала не решены: timeout или idempotent") for key in model.undecided(project)]
    return found + [warning("MODEL", req, "Нет функции") for req in uncovered]


def consistency(project):
    """Решения, параметры, сценарии качества, домены и жизненный цикл."""
    if not (project.architecture / "_order.yaml").exists():
        return []
    reqs = model.known_requirements(project)
    found = [blocker("AD", key, problem) for key, problem in extras.check_decisions(project, reqs)]
    found += [blocker("G06", key, problem) for key, problem in extras.check_params(project)]
    found += [warning("G06", key, problem) for key, problem in extras.check_numbers(project)]
    found += [warning("G11", key, problem) for key, problem in extras.check_signatures(project)]
    found += [blocker("QUAL", key, problem) for key, problem in extras.check_quality(project, reqs)]
    if model.present(project):
        found += [blocker("M-05", key, problem) for key, problem in extras.check_lifecycles(model.load(project))]
    found += [blocker("ROLE", key, problem) for key, problem in extras.check_role_review(project)]
    found += [warning("ROLE", key, "Подтверждения перенесены и на этой версии не проверялись") for key in extras.imported_approvals(project)]
    silent, questions = extras.check_domains(project)
    found += [blocker("G02", key, problem) for key, problem in silent]
    return found + [warning("G02", name, "Домен ждёт решения человека") for name in questions]


def coverage(project):
    """Данные для панели готовности: что покрыто, а не только что сломано."""
    stories = {path.name: scenarios.audit_story(read(path))[0] for path in project.stories()}
    guessed = {}
    if project.epics:
        guessed = {title.split(":")[0]: scenarios.guess_classes(body) for title, body in STORY_BLOCK.findall(read(project.epics))}
    known = blocks.registry(project)
    return {
        "scenario_classes": {"stories": stories, "epics_guessed": guessed},
        "blocks": {card["id"]: {"title": card["title"], "filled": blocks.audit_card(card, known)[0]} for card in blocks.cards(project)},
        "model": model.summary(project) if model.present(project) else {},
    }


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


def method_gaps(project):
    """Полнота по критериям doc-method. По умолчанию замечания, в docs/gates.yaml method: strict делает обязательные блокерами."""
    base = pathlib.Path(__file__).resolve().parents[2] / "doc-method"
    if not base.exists():
        return []
    sys.path.insert(0, str(base))
    from method import engine

    settings = project.root / "docs" / "gates.yaml"
    strict = settings.exists() and (yaml.safe_load(read(settings)) or {}).get("method") == "strict"
    groups = {}
    for row in engine.gaps(project.root):
        groups.setdefault(row["criterion"], []).append(row)
    make = lambda row: blocker if strict and row["level"] == "must" else warning
    return [make(rows[0])("METHOD", key, f"{len(rows)} шт., например {rows[0]['object']}: {rows[0]['why']}") for key, rows in groups.items()]


CHECKS = [g03_story_ready, g05_terms, g07_traceability, g08_acceptance, g08_story_classes, g12_assumptions, block_cards, system_model, consistency, architecture_links, method_gaps]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    project = Project(args.root)
    findings = [item for check in CHECKS for item in check(project)]
    blockers = [f for f in findings if f["level"] == "blocker"]
    project.quality.mkdir(exist_ok=True)
    report = {"ok": not blockers, "blockers": len(blockers), "warnings": len(findings) - len(blockers), "findings": findings, "coverage": coverage(project)}
    report["readiness"] = extras.readiness(project, report, report["coverage"])
    (project.quality / "check-report.yaml").write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False), encoding="utf-8")
    for item in findings:
        print(f"{item['level']:8} {item['gate']:5} {item['where']}: {item['problem']}")
    print(f"Блокеров: {len(blockers)}, предупреждений: {len(findings) - len(blockers)}, готовность {report['readiness']['score']} из 100")
    sys.exit(1 if blockers else 0)


if __name__ == "__main__":
    main()
