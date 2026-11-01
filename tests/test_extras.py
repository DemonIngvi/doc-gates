"""Запуск: uv run --with pytest --with pyyaml pytest tests"""
import pathlib
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import extras  # noqa: E402
from check import consistency  # noqa: E402
from project import Project  # noqa: E402


def make(tmp_path, domains=None, prd="#### FR-1: Первое\n\n- **NFR-1 Скорость:** быстро\n"):
    folder = tmp_path / "_bmad-output" / "planning-artifacts" / "prds" / "p"
    folder.mkdir(parents=True)
    (folder / "prd.md").write_text(prd, encoding="utf-8")
    arch = tmp_path / "docs" / "architecture"
    (arch / "decisions").mkdir(parents=True)
    (arch / "_order.yaml").write_text("sections: []\n", encoding="utf-8")
    (arch / "decisions" / "AD-1.yaml").write_text("id: AD-1\nbinds: [FR-1]\n", encoding="utf-8")
    rows = domains if domains is not None else [{"domain": name, "status": "deferred"} for name in extras.DOMAINS]
    (arch / "domains.yaml").write_text(yaml.safe_dump({"domains": rows}, allow_unicode=True), encoding="utf-8")
    return Project(tmp_path)


def problems(project):
    return [(f["level"], f["problem"]) for f in consistency(project)]


def test_clean(tmp_path):
    assert problems(make(tmp_path)) == []


def test_decision_binds_missing_requirement(tmp_path):
    project = make(tmp_path)
    (project.architecture / "decisions" / "AD-1.yaml").write_text("id: AD-1\nbinds: [FR-9, all]\n", encoding="utf-8")
    assert ("blocker", "Нет: требование FR-9") in problems(project)


def test_decision_replaces_missing(tmp_path):
    project = make(tmp_path)
    (project.architecture / "decisions" / "AD-1.yaml").write_text("id: AD-1\nbinds: [FR-1]\nreplaces: AD-7\n", encoding="utf-8")
    assert ("blocker", "Заменяет несуществующее решение AD-7") in problems(project)


def test_silent_domain(tmp_path):
    project = make(tmp_path, [{"domain": "права", "status": "deferred"}])
    assert ("blocker", "Домен молчит, нужен статус") in problems(project)


def test_decided_domain_needs_rule(tmp_path):
    rows = [{"domain": name, "status": "deferred"} for name in extras.DOMAINS if name != "логи"]
    project = make(tmp_path, rows + [{"domain": "логи", "status": "decided", "rule": "AD-9"}])
    assert ("blocker", "Статус decided без существующего правила: AD-9") in problems(project)


def test_question_domain_warns(tmp_path):
    rows = [{"domain": name, "status": "question" if name == "логи" else "deferred"} for name in extras.DOMAINS]
    assert ("warning", "Домен ждёт решения человека") in problems(make(tmp_path, rows))


def test_param_value_conflict(tmp_path):
    prd = "#### FR-1: Первое\n\nЗначение `a.b` = 5.\n\n- **NFR-1 Скорость:** быстро\n"
    project = make(tmp_path, prd=prd)
    (project.architecture / "params.yaml").write_text("params:\n- {name: a.b, default: 3}\n", encoding="utf-8")
    assert ("blocker", "a.b: написано 5, в params.yaml 3") in problems(project)


def test_quality_points_to_missing_nfr(tmp_path):
    project = make(tmp_path)
    (project.architecture / "quality.yaml").write_text("scenarios:\n- {id: Q-1, nfr: NFR-9}\n", encoding="utf-8")
    assert ("blocker", "Нет: требование NFR-9") in problems(project)


def test_reply_with_text_after_json():
    from run_gate import parse

    assert parse('Вот ответ: {"verdict": "pass", "findings": []}\n\nПояснение {не JSON}') == {"verdict": "pass", "findings": []}


def test_readiness_ceiling(tmp_path):
    project = make(tmp_path)
    cover = {"scenario_classes": {"stories": {}}, "model": {"a": 1}, "blocks": {"b": {"filled": 100}}}
    report = {"findings": [{"gate": "G07", "level": "blocker", "where": "x", "problem": "y"}], "blockers": 1}
    result = extras.readiness(project, report, cover)
    assert result["score"] <= 89


def test_open_questions_lower_score(tmp_path):
    prd = "#### FR-1: Первое\n\n## 9. Open Questions\n\n1. Какой порог?\n2. Нужен ли экспорт?\n\n## 10. Другое\n\n- **NFR-1 Скорость:** быстро\n"
    assert extras.open_questions(make(tmp_path, prd=prd)) == 2
