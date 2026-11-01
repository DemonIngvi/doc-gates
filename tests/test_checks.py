"""Запуск: uv run --with pytest --with pyyaml pytest tests"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
import blocks  # noqa: E402
import scenarios  # noqa: E402
from check import block_cards, g03_story_ready, g08_acceptance, g08_story_classes  # noqa: E402
from project import Project  # noqa: E402

ABSENT = "**Not applicable:** S2 — у операции одна ветка выполнения; S4 — поля без числовых ограничений; S6 — внешних зависимостей у операции нет; S7, S8 — запись одна и защищена уникальным ключом; S9 — у истории нет настроек поведения; S10 — операция выполняется одной транзакцией; S11 — срок хранения задан в истории про удаление; S12 — аудит покрыт сквозным решением AD-3"
ROWS = "| S1 Создание | вход | ок | N/A |\n| S3 Нет данных | вход | отказ | 422 |\n| S5 Чужой | вход | отказ | 404 |"


def story(rows=ROWS, absent=ABSENT):
    return f"---\nroute: 'dispatch'\n---\n## Intent\n\n| Scenario | Input / State | Expected | Error Handling |\n|---|---|---|---|\n{rows}\n\n{absent}\n"


def problems(text):
    return scenarios.audit_story(text)[1]


def test_full_story_passes():
    coverage, found = scenarios.audit_story(story())
    assert found == []
    assert coverage["covered"] == ["S1", "S3", "S5"]
    assert set(coverage["not_applicable"]) == {"S2", "S4", "S6", "S7", "S8", "S9", "S10", "S11", "S12"}


def test_story_without_matrix_is_skipped():
    assert scenarios.audit_story("## Intent\n") == (None, [])


def test_row_without_class_gives_one_finding():
    assert problems(story(ROWS.replace("S3 Нет", "Нет"))) == ["Строки без класса S1–S12: Нет данных"]


def test_unknown_class():
    assert any("Неизвестный класс S13" in p for p in problems(story(ROWS.replace("S3 Нет", "S13 Нет"))))


def test_class_neither_covered_nor_explained():
    found = problems(story(absent=ABSENT.replace("S6 — внешних зависимостей у операции нет; ", "")))
    assert found == ["Класс не покрыт и не объяснён: S6"]


@pytest.mark.parametrize("reason", ["не применимо", "N/A", "нет", "не требуется."])
def test_template_reason_is_rejected(reason):
    found = problems(story(absent=ABSENT.replace("у операции одна ветка выполнения", reason)))
    assert any(p.startswith("S2: причина") for p in found)


def test_needs_three_rows():
    rows = "| S1 Создание | вход | ок | N/A |\n| S3 Нет данных | вход | отказ | 422 |"
    assert any("нужно не меньше 3" in p for p in problems(story(rows, ABSENT + "; S5 — вход открыт для всех пользователей")))


def test_needs_main_path():
    assert "Нет основного пути S1" in problems(story(ROWS.replace("S1 Создание", "S2 Создание")))


def test_needs_negative():
    rows = "| S1 А | в | о | N/A |\n| S2 Б | в | о | N/A |\n| S9 В | в | о | N/A |"
    assert "Нет негативного сценария S3–S6" in problems(story(rows))


def test_several_classes_in_one_row():
    rows = ROWS.replace("S3 Нет", "S3, S4 Нет")
    coverage, _ = scenarios.audit_story(story(rows))
    assert "S4" in coverage["covered"]


def test_guess_finds_classes():
    assert scenarios.guess_classes("**Then** API возвращает 403") == ["S1", "S5"]
    assert scenarios.guess_classes("**Then** карточка появилась") == ["S1"]


@pytest.mark.parametrize("text", [
    "запрос отправлен", "несколько правил", "версия промпта", "Request связан как дубль",
    "видят его без перезагрузки", "получить черновики", "цвет дублируется значком",
])
def test_guess_ignores_ordinary_words(text):
    assert scenarios.guess_classes(text) == ["S1"]


@pytest.mark.parametrize("text, tag", [
    ("ключ не возвращается", "S5"), ("изменение невозможно", "S3"), ("элементов, доступных пользователю", "S5"),
    ("пользователь с меньшими правами", "S5"), ("запрос нельзя выразить", "S3"), ("колонка с превышенным WIP-лимитом", "S4"),
])
def test_guess_finds_negative_wording(text, tag):
    assert tag in scenarios.guess_classes(text)


def make_project(tmp_path, card=None, story_text=None):
    plan = tmp_path / "_bmad-output" / "planning-artifacts"
    (plan / "prds" / "p").mkdir(parents=True)
    (plan / "prds" / "p" / "prd.md").write_text("#### FR-1: Первое\n\n- **NFR-1 Скорость:** быстро\n", encoding="utf-8")
    (plan / "epics.md").write_text("### Story 1.1: Первая\n\n**Acceptance Criteria:**\n\n**Given** а\n**When** б\n**Then** карточка появилась\n", encoding="utf-8")
    impl = tmp_path / "_bmad-output" / "implementation-artifacts"
    impl.mkdir(parents=True)
    (impl / "1-1-first.md").write_text(story_text or story(), encoding="utf-8")
    arch = tmp_path / "docs" / "architecture"
    (arch / "blocks" / "api").mkdir(parents=True)
    (arch / "integrations").mkdir()
    (arch / "stores").mkdir()
    (arch / "integrations" / "I1.yaml").write_text("id: I1\n", encoding="utf-8")
    (arch / "stores" / "S1.yaml").write_text("id: S1\ntables: [project]\n", encoding="utf-8")
    (arch / "params.yaml").write_text("params:\n- {name: a.b, default: 1, min: 0, max: 2, why: x}\n", encoding="utf-8")
    (arch / "stack.yaml").write_text("rows:\n- {name: NestJS, version: 12.3.2}\n", encoding="utf-8")
    if card:
        (arch / "blocks" / "api" / "card.yaml").write_text(card, encoding="utf-8")
    return Project(tmp_path)


CARD = """id: api-access
title: Доступ
kind: service
does: [проверяет Role]
tech: NestJS 12.3.2
stories: ['1.1']
io:
- {dir: in, with: work, what: запрос, via: I1}
data:
- {table: project, access: read}
params: [a.b]
reqs: [FR-1]
tasks: ['1.1']
on_failure: отказ в доступе
why: права проверяются в одном месте
operations:
- {name: canRead, caller: work, via: внутри}
"""


def blockers(project):
    return [f["problem"] for f in block_cards(project) if f["level"] == "blocker"]


def test_full_card(tmp_path):
    project = make_project(tmp_path, CARD)
    assert block_cards(project) == []
    assert blocks.audit_card(blocks.cards(project)[0], blocks.registry(project))[0] == 100


@pytest.mark.parametrize("old, new, expected", [
    ("[FR-1]", "[FR-9]", "Нет: требование FR-9"),
    ("stories: ['1.1']", "stories: ['9.9']", "Нет: история 9.9"),
    ("tasks: ['1.1']", "tasks: ['1.2']", "Нет: задача 1.2"),
    ("via: I1", "via: I2", "Нет интерфейса I2"),
    ("table: project", "table: ghost", "Нет таблицы ghost"),
    ("table: project", "table: S1", "S1: нужно имя таблицы, а не код хранилища"),
    ("[a.b]", "[a.c]", "Нет параметра a.c"),
    ("NestJS 12.3.2", "Express 5", "Нет в списке технологий: Express 5"),
    ("отказ в доступе", "отказ по NFR-1", "NFR-1 упомянуто в карточке, но его нет в reqs"),
])
def test_broken_link(tmp_path, old, new, expected):
    assert expected in blockers(make_project(tmp_path, CARD.replace(old, new)))


def test_placeholder_is_not_filled(tmp_path):
    project = make_project(tmp_path, CARD.replace("права проверяются в одном месте", "<1–2 предложения>"))
    found = block_cards(project)
    assert [f["level"] for f in found] == ["warning"]
    assert "нет: why" in found[0]["problem"]


def test_screen_without_operation(tmp_path):
    card = CARD.replace("kind: service", "kind: ui").split("operations:")[0] + "screens:\n- {path: /board, status: новое}\n"
    assert "Экран /board: у действия нет операции API" in blockers(make_project(tmp_path, card))


def test_project_without_blocks(tmp_path):
    assert block_cards(make_project(tmp_path)) == []


def test_story_file_problem_blocks(tmp_path):
    found = g08_story_classes(make_project(tmp_path, story_text=story(ROWS.replace("S3 Нет", "Нет"))))
    assert found[0]["level"] == "blocker"


def test_template_text_blocks_story(tmp_path):
    text = story(absent=ABSENT.replace("у операции одна ветка выполнения", "WHY_THIS_CLASS_CANNOT_HAPPEN_HERE"))
    assert any("WHY_THIS_CLASS" in f["problem"] for f in g03_story_ready(make_project(tmp_path, story_text=text)))


def test_epic_without_negative_warns(tmp_path):
    assert g08_acceptance(make_project(tmp_path))[0]["problem"] == "Нет негативного сценария S3–S6"


def test_requirement_texts():
    from build_packet import requirement_texts

    prd = "#### FR-1: Первое\n\nТекст.\n\n#### FR-2: Второе\n\nДругой.\n\n- **NFR-1 Скорость:** быстро\n- **NFR-2 Отклик:** сразу\n"
    text = requirement_texts(prd, ["FR-1", "NFR-1"])
    assert "Текст." in text and "быстро" in text
    assert "Другой." not in text and "сразу" not in text


def test_measured_speed_is_not_vague():
    from check import VAGUE

    assert not VAGUE.search("открывается быстрее 1,5 с")
    assert VAGUE.search("открывается быстро")


def test_task_from_registry(tmp_path):
    project = make_project(tmp_path, CARD.replace("tasks: ['1.1']", "tasks: ['7.7']"))
    (project.architecture / "tasks.yaml").write_text("tasks: ['7.7']\n", encoding="utf-8")
    assert blockers(project) == []
