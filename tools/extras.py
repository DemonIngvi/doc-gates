"""Проверки решений, параметров, доменов и процент готовности."""
import re

import yaml

from project import read

# Темы, по которым архитектура обязана высказаться: решить, отложить или задать вопрос.
DOMAINS = ("аутентификация", "права", "данные", "ошибки", "логи", "настройки", "развёртывание", "резервное копирование", "наблюдаемость", "миграции")
MEASURE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(секунд\w*|минут\w*|час\w*|дн\w*|дней|мс|ГБ|МБ|Points)\b")
OPEN_QUESTION = re.compile(r"^\d+\. .+\?$", re.M)
WEIGHTS = {"Трассировка": 30, "Сценарии": 25, "Модель": 20, "Карточки": 10, "Обоснование": 15}
SCALE = ((90, "готов"), (75, "почти"), (60, "в работе"), (40, "черновик"), (0, "заготовка"))
QUESTION_PENALTY = 2
QUESTION_LIMIT = 10
CEILING = 90


def load(path, default):
    return yaml.safe_load(read(path)) if path.exists() else default


def decisions(project):
    folder = project.architecture / "decisions"
    return [yaml.safe_load(read(path)) for path in sorted(folder.glob("AD-*.yaml"))] if folder.exists() else []


def check_decisions(project, known_reqs):
    """Решение привязано к существующим требованиям, замена ссылается на существующее решение."""
    units = decisions(project)
    ids = {unit["id"] for unit in units}
    found = []
    for unit in units:
        for item in unit["binds"]:
            found += [(unit["id"], f"Нет: требование {code}") for code in re.findall(r"\b(?:NFR|FR)-\d+\b", item) if code not in known_reqs]
        if unit.get("replaces") and unit["replaces"] not in ids:
            found.append((unit["id"], f"Заменяет несуществующее решение {unit['replaces']}"))
    return found


def check_params(project):
    """Один факт, один источник: значение параметра рядом с его именем в документах совпадает с params.yaml."""
    params = load(project.architecture / "params.yaml", {"params": []})["params"]
    documents = [p for p in (project.prd, project.epics, project.experience) if p] + project.stories()
    found = []
    for path in documents:
        text = read(path)
        for param in params:
            for match in re.finditer(rf"{re.escape(param['name'])}`?\s*[=:]\s*`?(\d+(?:[.,]\d+)?)", text):
                if match.group(1).replace(",", ".") != str(param["default"]):
                    found.append((path.name, f"{param['name']}: написано {match.group(1)}, в params.yaml {param['default']}"))
    return found


def check_numbers(project):
    """Число с единицей в критериях истории должно иметь источник в требованиях, UX или параметрах."""
    if not (project.epics and project.prd):
        return []
    sources = read(project.prd) + (read(project.experience) if project.experience else "")
    params = project.architecture / "params.yaml"
    sources += read(params) if params.exists() else ""
    known = {(number, unit[:3]) for number, unit in MEASURE.findall(sources)}
    found = []
    for title, body in re.findall(r"^### Story (\d+\.\d+): .+?\n(.*?)(?=^### Story |^## Epic |\Z)", read(project.epics), re.M | re.S):
        found += [(title, f"{number} {unit}: значения нет в PRD, UX и параметрах") for number, unit in MEASURE.findall(body) if (number, unit[:3]) not in known]
    return found


def check_role_review(project):
    """Проверка ролями дорогая: выключена по умолчанию, включение требует лимита токенов."""
    config = load(project.root / "docs" / "gates.yaml", {}).get("role_review", {})
    found = []
    if config.get("enabled") and not config.get("max_tokens"):
        found.append(("docs/gates.yaml", "Проверка ролями включена без лимита max_tokens"))
    return found


def imported_approvals(project):
    return sorted(path.parent.name for path in project.architecture.glob("components/*/approvals.yaml") if yaml.safe_load(read(path)).get("origin") == "imported")


def check_signatures(project):
    """Вердикт G11 считается принятым только с подписью человека и разбором находок."""
    found = []
    for path in sorted((project.quality / "G11").glob("*.yaml")) if (project.quality / "G11").exists() else []:
        run = yaml.safe_load(read(path))
        pending = sum(item.get("decision") == "pending" for item in run["findings"])
        if not run.get("signed_by"):
            found.append((path.name, f"Нет подписи человека, не разобрано находок: {pending}"))
    return found


def check_quality(project, known_reqs):
    scenarios = load(project.architecture / "quality.yaml", {"scenarios": []})["scenarios"]
    return [(item["id"], f"Нет: требование {item['nfr']}") for item in scenarios if item.get("nfr") and item["nfr"] not in known_reqs]


def check_lifecycles(units):
    """Объект, который меняется со временем, описывает свои состояния."""
    return [(key, "Транзакционный объект без состояний") for key, unit in units["data"].items()
            if unit["class"] == "transactional" and not unit.get("states")]


def check_domains(project):
    """G02: архитектура не молчит ни по одной обязательной теме."""
    path = project.architecture / "domains.yaml"
    if not path.exists():
        return [("docs/architecture/domains.yaml", "Нет таблицы доменов")], []
    rows = {row["domain"]: row for row in yaml.safe_load(read(path))["domains"]}
    ids = {unit["id"] for unit in decisions(project)}
    conventions = project.architecture / "conventions.yaml"
    allowed = {row["concern"] for row in load(conventions, {"rows": []})["rows"]}
    found = [(name, "Домен молчит, нужен статус") for name in DOMAINS if name not in rows]
    questions = []
    for name, row in rows.items():
        if row["status"] == "decided" and row.get("rule") not in ids | allowed:
            found.append((name, f"Статус decided без существующего правила: {row.get('rule')}"))
        if row["status"] == "question":
            questions.append(name)
    return found, questions


def open_questions(project):
    if not project.prd:
        return 0
    head, marker, tail = read(project.prd).partition("Open Questions")
    return len(OPEN_QUESTION.findall(tail.split("\n## ")[0])) if marker else 0


def share(good, total):
    return good / total if total else 0


def readiness(project, report, cover):
    """Измеримый минимум, а не доказательство полноты. Блокеры и открытые вопросы держат потолок."""
    findings = report["findings"]
    gate_blockers = lambda gate: sum(f["gate"] == gate and f["level"] == "blocker" for f in findings)
    stories = cover["scenario_classes"]["stories"]
    fr_count = len(re.findall(r"^#### FR-\d+:", read(project.prd), re.M)) if project.prd else 0
    gaps = sum(f["gate"] == "MODEL" and f["level"] == "warning" and f["where"].startswith("FR-") for f in findings) + gate_blockers("G07")
    model_size = sum(cover["model"].values())
    units = decisions(project)
    cards = cover["blocks"]
    values = {
        "Трассировка": share(max(fr_count - gaps, 0), fr_count),
        "Сценарии": share(sum(1 for item in stories.values() if item) - gate_blockers("G08"), len(stories)),
        "Модель": 1.0 if model_size and not gate_blockers("MODEL") else 0.0,
        "Карточки": sum(item["filled"] for item in cards.values()) / (100 * len(cards)) if cards else 0.0,
        "Обоснование": share(sum(bool(unit.get("binds")) for unit in units), len(units)),
    }
    parts = {name: round(max(values[name], 0) * weight) for name, weight in WEIGHTS.items()}
    penalty = min(open_questions(project) * QUESTION_PENALTY, QUESTION_LIMIT)
    score = max(sum(parts.values()) - penalty, 0)
    if report["blockers"] or penalty:
        score = min(score, CEILING - 1 if report["blockers"] else CEILING)
    status = next(name for limit, name in SCALE if score >= limit)
    return {"score": score, "status": status, "parts": {**parts, "Открытые вопросы": -penalty}}
