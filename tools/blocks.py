"""Карточки блоков: заполненность и существование всего, на что они ссылаются."""
import re

import yaml

from project import read

FIELDS = ("does", "tech", "stories", "io", "data", "params", "reqs", "tasks", "on_failure", "why")
BY_KIND = {"service": "operations", "ui": "screens", "storage": "schema_ref", "config": "schema_ref"}
PLACEHOLDER = re.compile(r"<[^<>]+>|\b(?:TBD|TODO)\b")
INSIDE = "внутри"


def filled(value):
    if isinstance(value, str):
        return bool(value.strip()) and not PLACEHOLDER.search(value)
    if isinstance(value, dict):
        return bool(value) and all(filled(item) for item in value.values())
    if isinstance(value, list):
        return bool(value) and all(filled(item) for item in value)
    return value is not None


def load_units(folder):
    return [yaml.safe_load(read(path)) for path in sorted(folder.glob("*.yaml"))] if folder.exists() else []


def listed_tasks(arch):
    """Задачи вне файлов историй: проект может вести их отдельным реестром."""
    path = arch / "tasks.yaml"
    return {str(item) for item in yaml.safe_load(read(path))["tasks"]} if path.exists() else set()


def registry(project):
    """Всё, на что карточка может сослаться. Отсутствующий список значит, что ссылка никуда не ведёт."""
    arch = project.architecture
    prd = read(project.prd) if project.prd else ""
    epics = read(project.epics) if project.epics else ""
    params = yaml.safe_load(read(arch / "params.yaml"))["params"] if (arch / "params.yaml").exists() else []
    stack = yaml.safe_load(read(arch / "stack.yaml"))["rows"] if (arch / "stack.yaml").exists() else []
    return {
        "reqs": {f"FR-{n}" for n in re.findall(r"^#### FR-(\d+):", prd, re.M)} | set(re.findall(r"\*\*(NFR-\d+)\b", prd)),
        "stories": set(re.findall(r"^### Story (\d+\.\d+):", epics, re.M)),
        "tasks": {".".join(re.match(r"(\d+)-(\d+)-", p.name).groups()) for p in project.stories() if re.match(r"\d+-\d+-", p.name)} | listed_tasks(arch),
        "interfaces": {unit["id"] for unit in load_units(arch / "integrations")},
        "tables": {table for unit in load_units(arch / "stores") for table in unit.get("tables", [])},
        "params": {item["name"] for item in params},
        "tech": {row["name"] for row in stack},
    }


def cards(project):
    root = project.architecture / "blocks"
    return [yaml.safe_load(read(path)) for path in sorted(root.rglob("*.yaml"))] if root.exists() else []


def audit_links(card, known):
    problems = []
    for field, label in (("reqs", "требование"), ("stories", "история"), ("tasks", "задача")):
        problems += [f"Нет: {label} {item}" for item in card.get(field) or [] if filled(item) and item not in known[field]]
    if filled(card.get("tech")) and not any(re.search(rf"\b{re.escape(name)}\b", card["tech"]) for name in known["tech"]):
        problems.append(f"Нет в списке технологий: {card['tech']}")
    calls = [*(card.get("io") or []), *(card.get("operations") or [])]
    for item in calls:
        via = item.get("via")
        if via and via != INSIDE and via not in known["interfaces"]:
            problems.append(f"Нет интерфейса {via}")
    if isinstance(card.get("data"), list):
        for row in card["data"]:
            table = row.get("table", "")
            if re.fullmatch(r"S\d+", table):
                problems.append(f"{table}: нужно имя таблицы, а не код хранилища")
            elif filled(table) and table not in known["tables"]:
                problems.append(f"Нет таблицы {table}")
    if isinstance(card.get("params"), list):
        problems += [f"Нет параметра {name}" for name in card["params"] if filled(name) and name not in known["params"]]
    for screen in card.get("screens") or []:
        if screen.get("status") != "есть" and not screen.get("operation"):
            problems.append(f"Экран {screen.get('path')}: у действия нет операции API")
    text = yaml.safe_dump({k: v for k, v in card.items() if k != "reqs"}, allow_unicode=True)
    named = set(re.findall(r"\b(?:NFR|FR)-\d+\b", text))
    problems += [f"{req} упомянуто в карточке, но его нет в reqs" for req in sorted(named - set(card.get("reqs") or []))]
    return problems


def audit_card(card, known):
    """Возвращает заполненность 0–100, незаполненные поля и битые ссылки."""
    names = [*FIELDS, BY_KIND[card["kind"]]]
    missing = [name for name in names if not filled(card.get(name))]
    return round(100 * (len(names) - len(missing)) / len(names)), missing, audit_links(card, known)
