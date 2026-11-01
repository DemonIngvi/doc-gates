"""Запуск: uv run --with pytest --with pyyaml pytest tests"""
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from check import system_model  # noqa: E402
from project import Project  # noqa: E402

COMMON = {"title": "Объект", "owner": "команда", "lifecycle": "active", "criticality": "low"}
TYPES = {"system_kind": ["own", "external"], "integration_type": ["webhook"], "flow_type": ["event"],
         "data_class": ["master"], "sensitivity": ["internal"]}


def base():
    return {
        "actors/lead.yaml": {"id": "lead", "kind": "role"},
        "systems/app.yaml": {"id": "app", "kind": "own"},
        "systems/ext.yaml": {"id": "ext", "kind": "external"},
        "data/item.yaml": {"id": "item", "class": "master", "sensitivity": "internal"},
        "data/note.yaml": {"id": "note", "class": "master", "sensitivity": "internal"},
        "functions/read-item.yaml": {"id": "read-item", "system": "app", "reqs": ["FR-1"], "reads": ["item"], "writes": []},
        "functions/ext-get.yaml": {"id": "ext-get", "system": "ext", "reqs": [], "reads": ["item"], "writes": []},
        "components/api.yaml": {"id": "api", "system": "app", "responsibility": "сервер"},
        "stores/S1.yaml": {"id": "S1", "owner": "api", "objects": ["item"], "tables": ["item"]},
        "integrations/I1.yaml": {"id": "I1", "from": "api", "to": "ext", "integration_type": "webhook", "timeout": "5 с", "idempotent": True},
        "flows/F1.yaml": {"id": "F1", "from": "api", "to": "ext", "objects": ["item"], "flow_type": "event", "over": "I1"},
        "processes/p.yaml": {"id": "p", "actors": ["lead"], "inputs": ["item"], "outputs": ["note"], "steps": [
            {"title": "Шаг один", "actor": "lead", "function": "ext-get", "inputs": ["item"], "outputs": ["note"]}]},
        "services/s.yaml": {"id": "s", "consumers": ["lead"], "provider": "app", "functions": ["read-item"],
                            "objectives": [{"text": "быстро", "quality": "Q-1"}]},
    }


def build(tmp_path, units):
    plan = tmp_path / "_bmad-output" / "planning-artifacts" / "prds" / "p"
    plan.mkdir(parents=True)
    (plan / "prd.md").write_text("#### FR-1: Первое\n\n#### FR-2: Второе\n", encoding="utf-8")
    arch = tmp_path / "docs" / "architecture"
    arch.mkdir(parents=True)
    (arch / "types.yaml").write_text(yaml.safe_dump(TYPES), encoding="utf-8")
    (arch / "quality.yaml").write_text(yaml.safe_dump({"scenarios": [{"id": "Q-1"}]}), encoding="utf-8")
    for rel, unit in units.items():
        path = arch / rel
        path.parent.mkdir(exist_ok=True)
        path.write_text(yaml.safe_dump({**COMMON, **unit}, allow_unicode=True), encoding="utf-8")
    return Project(tmp_path)


def blockers(project):
    return [f["problem"] for f in system_model(project) if f["level"] == "blocker"]


def test_valid_model(tmp_path):
    found = system_model(build(tmp_path, base()))
    assert [(f["level"], f["where"]) for f in found] == [("warning", "FR-2")]


def test_undecided_channel_warns(tmp_path):
    units = base()
    units["integrations/I1.yaml"]["idempotent"] = None
    found = system_model(build(tmp_path, units))
    assert ("warning", "I1") in [(f["level"], f["where"]) for f in found]


def test_fmea_covers_channels_and_stores(tmp_path):
    project = build(tmp_path, base())
    rows = [{"target": "I1"}, {"target": "I9"}]
    (project.architecture / "fmea.yaml").write_text(yaml.safe_dump({"rows": rows}), encoding="utf-8")
    found = blockers(project)
    assert "Нет строки в fmea.yaml" in found
    assert "Строка fmea.yaml ссылается на несуществующий объект" in found


def test_project_without_model(tmp_path):
    assert system_model(Project(tmp_path))[0]["problem"] == "Модель системы не заполнена"


@pytest.mark.parametrize("rel, field, value, expected", [
    ("systems/ext.yaml", "kind", "vendor", "kind: значения vendor нет в types.yaml"),
    ("functions/read-item.yaml", "system", "ghost", "Нет: система ghost"),
    ("functions/read-item.yaml", "reqs", ["FR-9"], "Нет: требование FR-9"),
    ("functions/read-item.yaml", "reads", ["ghost"], "Нет: объект данных ghost"),
    ("stores/S1.yaml", "objects", ["ghost"], "Нет: объект данных ghost"),
    ("stores/S1.yaml", "owner", "ghost", "Нет: владелец ghost"),
    ("integrations/I1.yaml", "to", "ghost", "Нет: участник ghost"),
    ("flows/F1.yaml", "over", "I9", "Нет интеграции I9"),
    ("services/s.yaml", "objectives", [{"text": "x", "quality": "Q-9"}], "Нет: сценарий качества Q-9"),
    ("services/s.yaml", "functions", ["ghost"], "Нет: функция ghost"),
    ("services/s.yaml", "provider", "ghost", "Нет: система ghost"),
])
def test_broken_reference(tmp_path, rel, field, value, expected):
    units = base()
    units[rel][field] = value
    assert expected in blockers(build(tmp_path, units))


def test_function_without_reason(tmp_path):
    units = base()
    units["functions/orphan.yaml"] = {"id": "orphan", "system": "app", "reqs": [], "reads": [], "writes": []}
    assert "Функция не относится ни к требованию, ни к процессу" in blockers(build(tmp_path, units))


def test_data_does_not_reach_system(tmp_path):
    units = base()
    units["functions/read-item.yaml"]["reads"] = ["note"]
    assert "Объект note не доходит до системы app" in blockers(build(tmp_path, units))


def test_flow_delivers_data(tmp_path):
    units = base()
    del units["flows/F1.yaml"]
    assert "Объект item не доходит до системы ext" in blockers(build(tmp_path, units))


def test_flow_between_systems_needs_integration(tmp_path):
    units = base()
    del units["flows/F1.yaml"]["over"]
    assert "Поток между системами без интеграции" in blockers(build(tmp_path, units))


def test_flow_on_foreign_integration(tmp_path):
    units = base()
    units["systems/third.yaml"] = {"id": "third", "kind": "external"}
    units["flows/F2.yaml"] = {"id": "F2", "from": "third", "to": "lead", "objects": ["item"], "flow_type": "event", "over": "I1"}
    assert "Интеграция I1 не связана с участниками потока" in blockers(build(tmp_path, units))


def test_step_input_comes_from_nowhere(tmp_path):
    units = base()
    units["processes/p.yaml"]["inputs"] = []
    assert "Шаг «Шаг один»: вход item ниоткуда не приходит" in blockers(build(tmp_path, units))


def test_step_order_matters(tmp_path):
    units = base()
    step = units["processes/p.yaml"]["steps"][0]
    units["processes/p.yaml"]["steps"] = [{**step, "title": "Рано", "inputs": ["note"], "outputs": []}, step]
    assert "Шаг «Рано»: вход note ниоткуда не приходит" in blockers(build(tmp_path, units))


def test_output_not_created(tmp_path):
    units = base()
    units["processes/p.yaml"]["steps"][0]["outputs"] = []
    assert "Выход note не создан ни одним шагом" in blockers(build(tmp_path, units))
