"""Модель системы: объекты ссылаются друг на друга, а данные доходят до тех, кто их использует."""
import re

import yaml

from blocks import load_units
from project import read

FOLDERS = ("actors", "processes", "services", "systems", "functions", "components", "data", "stores", "flows", "integrations", "nodes")
TYPED = (("systems", "kind", "system_kind"), ("data", "class", "data_class"), ("data", "sensitivity", "sensitivity"),
         ("flows", "flow_type", "flow_type"), ("integrations", "integration_type", "integration_type"))


def load(project):
    return {name: {unit["id"]: unit for unit in load_units(project.architecture, name)} for name in FOLDERS}


def present(project):
    return bool(load_units(project.architecture, "functions"))


def owner_system(name, units):
    """Система участника: компонент относится к своей системе, а встроенный компонент к системе хоста."""
    if name in units["components"]:
        component = units["components"][name]
        return owner_system(component["host"], units) if component.get("host") else component["system"]
    return name


def missing(items, known, label):
    return [f"Нет: {label} {item}" for item in items if item not in known]


def check_types(units, types):
    found = []
    for folder, field, dictionary in TYPED:
        for key, unit in units[folder].items():
            if unit[field] not in types.get(dictionary, []):
                found.append((key, f"{field}: значения {unit[field]} нет в types.yaml"))
    return found


def check_functions(units, known_reqs, in_processes):
    found = []
    for key, unit in units["functions"].items():
        problems = missing([unit["system"]], units["systems"], "система")
        problems += missing(unit["reqs"], known_reqs, "требование")
        problems += missing([*unit["reads"], *unit["writes"]], units["data"], "объект данных")
        if not unit["reqs"] and key not in in_processes:
            problems.append("Функция не относится ни к требованию, ни к процессу")
        found += [(key, problem) for problem in problems]
    return found


def reachable(function, data, units):
    """Объект лежит в хранилище системы либо приходит в систему потоком."""
    system = function["system"]
    stored = any(data in store["objects"] and owner_system(store["owner"], units) == system for store in units["stores"].values())
    received = any(data in flow["objects"] and owner_system(flow["to"], units) == system for flow in units["flows"].values())
    return stored or received


def check_reachability(units):
    found = []
    for key, unit in units["functions"].items():
        for data in (*unit["reads"], *unit["writes"]):
            if data in units["data"] and unit["system"] in units["systems"] and not reachable(unit, data, units):
                found.append((key, f"Объект {data} не доходит до системы {unit['system']}"))
    return found


def check_stores(units):
    found = []
    for key, unit in units["stores"].items():
        found += [(key, problem) for problem in missing(unit["objects"], units["data"], "объект данных")]
        found += [(key, problem) for problem in missing([unit["owner"]], {**units["components"], **units["systems"]}, "владелец")]
    return found


def check_integrations(units):
    known = {**units["systems"], **units["components"]}
    found = []
    for key, unit in units["integrations"].items():
        found += [(key, problem) for problem in missing([unit["from"], unit["to"]], known, "участник")]
    return found


def check_flows(units):
    known = {**units["systems"], **units["components"], **units["actors"]}
    found = []
    for key, unit in units["flows"].items():
        problems = missing([unit["from"], unit["to"]], known, "участник")
        problems += missing(unit["objects"], units["data"], "объект данных")
        ends = {owner_system(unit["from"], units), owner_system(unit["to"], units)}
        channel = units["integrations"].get(unit.get("over"))
        if unit.get("over") and not channel:
            problems.append(f"Нет интеграции {unit['over']}")
        elif len(ends) > 1 and not channel:
            problems.append("Поток между системами без интеграции")
        elif channel and not ends & {owner_system(channel["from"], units), owner_system(channel["to"], units)}:
            problems.append(f"Интеграция {channel['id']} не связана с участниками потока")
        found += [(key, problem) for problem in problems]
    return found


def check_process(key, unit, units):
    """Шаг получает данные из входа процесса или из выхода предыдущего шага."""
    problems = missing(unit["actors"], units["actors"], "участник")
    problems += missing([*unit["inputs"], *unit["outputs"]], units["data"], "объект данных")
    available = set(unit["inputs"])
    for step in unit["steps"]:
        problems += missing([step["actor"]], {**units["actors"], **units["systems"]}, "участник")
        problems += missing([step["function"]] if step.get("function") else [], units["functions"], "функция")
        problems += missing([*step["inputs"], *step["outputs"]], units["data"], "объект данных")
        problems += [f"Шаг «{step['title']}»: вход {item} ниоткуда не приходит" for item in step["inputs"] if item not in available]
        available |= set(step["outputs"])
    problems += [f"Выход {item} не создан ни одним шагом" for item in unit["outputs"] if item not in available]
    return [(key, problem) for problem in problems]


def check_services(units, quality):
    found = []
    for key, unit in units["services"].items():
        problems = missing(unit["functions"], units["functions"], "функция")
        problems += missing([unit["provider"]], units["systems"], "система")
        problems += missing(unit["consumers"], {**units["actors"], **units["systems"]}, "потребитель")
        problems += missing([item["quality"] for item in unit["objectives"]], quality, "сценарий качества")
        found += [(key, problem) for problem in problems]
    return found


def check_fmea(units, rows):
    """Строка отказа на каждый канал и хранилище: иначе поведение при сбое никто не решал."""
    known = {**units["integrations"], **units["stores"], **units["components"]}
    targets = {row["target"] for row in rows}
    channels = {key for key, unit in units["integrations"].items() if targets & {key, unit["from"], unit["to"]}}
    stores = {key for key, unit in units["stores"].items() if targets & {key, unit["owner"]}}
    missing_rows = sorted((set(units["integrations"]) | set(units["stores"])) - channels - stores)
    found = [(key, "Нет строки в fmea.yaml") for key in missing_rows]
    return found + [(key, "Строка fmea.yaml ссылается на несуществующий объект") for key in sorted(targets - set(known))]


def known_requirements(project):
    prd = read(project.prd) if project.prd else ""
    return {f"FR-{n}" for n in re.findall(r"^#### FR-(\d+):", prd, re.M)} | set(re.findall(r"\*\*(NFR-\d+)\b", prd))


def audit(project):
    """Возвращает блокеры и список требований без функции."""
    units = load(project)
    reqs = known_requirements(project)
    types_file = project.architecture / "types.yaml"
    types = yaml.safe_load(read(types_file)) if types_file.exists() else {}
    quality_file = project.architecture / "quality.yaml"
    quality = {item["id"] for item in yaml.safe_load(read(quality_file))["scenarios"]} if quality_file.exists() else set()
    used = {step.get("function") for unit in units["processes"].values() for step in unit["steps"]}
    found = check_types(units, types) + check_functions(units, reqs, used) + check_reachability(units)
    found += check_stores(units) + check_integrations(units) + check_flows(units) + check_services(units, quality)
    fmea_file = project.architecture / "fmea.yaml"
    if fmea_file.exists():
        found += check_fmea(units, yaml.safe_load(read(fmea_file))["rows"])
    for key, unit in units["processes"].items():
        found += check_process(key, unit, units)
    covered = {req for unit in units["functions"].values() for req in unit["reqs"]}
    return found, sorted(req for req in reqs - covered if req.startswith("FR-"))


def undecided(project):
    """Канал, у которого записано, что решения ещё нет."""
    return sorted(key for key, unit in load(project)["integrations"].items()
                  if unit.get("idempotent") is None or unit.get("timeout") == "не задан")


def summary(project):
    return {name: len(items) for name, items in load(project).items()}
