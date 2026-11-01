"""Классы сценариев S1–S12. В файле истории класс ставит автор, в эпиках он только угадывается по словам."""
import re

NAMES = {
    "S1": "основной путь", "S2": "альтернативный путь", "S3": "неверный вход", "S4": "границы и лимиты",
    "S5": "права и безопасность", "S6": "сбой зависимости", "S7": "параллельность", "S8": "повтор и идемпотентность",
    "S9": "конфигурация", "S10": "состояние и восстановление", "S11": "данные и хранение", "S12": "наблюдаемость и аудит",
}
ORDER = list(NAMES)
NEGATIVE = {"S3", "S4", "S5", "S6"}
MIN_ROWS = 3
MIN_REASON = 15
GENERIC = re.compile(r"не\s*применим\w*|не\s+требуется|не\s+нужн\w*|нет\s+необходимости|n/?a|нет", re.I)
ROW_TAGS = re.compile(r"^(S\d+(?:\s*,\s*S\d+)*)\s+\S")
ABSENT_LINE = re.compile(r"^\*\*Not applicable:\*\*(.*)$", re.M)
ABSENT_ITEM = re.compile(r"(S\d+(?:\s*,\s*S\d+)*)\s*[—–-]\s*(.+?)(?=;\s*S\d+|$)")
HINTS = {
    "S2": r"альтернатив|вместо|иначе|либо",
    "S3": r"отклон|запрещ|не создаётся|\b4(00|13|15|22)\b|неверн|невозможн|нельзя",
    "S4": r"лимит|порог|превыш|не более|не менее|максимум|минимум|квот",
    "S5": r"\bRole\b|\b40[134]\b|\bправ(а|ам|ами|ах)?\b|секрет|токен|подпис|чуж\w+|шифр|\bключ|доступны\w* (ему|пользовател)",
    "S6": r"недоступ|таймаут|сбо[йя]|отказ|\b50\d\b",
    "S7": r"параллел|одновременн|конфликт|\b409\b|гонк",
    "S8": r"идемпотент|повтор|дважды",
    "S9": r"выключ|отключ|\bвключ[её]н|настро|конфигур",
    "S10": r"восстанов|падени|перезапуск|возобнов|откат|отмен",
    "S11": r"удал|срок хранения|хранит|архив|приват|экспорт",
    "S12": r"журнал|аудит|\bлог(и|ов|ах|ируе\w*)\b|метрик",
}


def matrix_rows(text):
    """Строки таблицы случаев без заголовка и разделителя."""
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if line.startswith("| Scenario | Input")), None)
    if start is None:
        return None
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        rows.append(line.strip("|").split("|")[0].strip())
    return rows


def split_tags(value):
    return re.findall(r"S\d+", value)


def absent_classes(text):
    """Строка вида: **Not applicable:** S6 — причина; S7, S8 — причина."""
    found = {}
    match = ABSENT_LINE.search(text)
    if match:
        for tags, reason in ABSENT_ITEM.findall(match.group(1).strip()):
            found.update({tag: reason.strip() for tag in split_tags(tags)})
    return found


def weak_reason(reason):
    return len(GENERIC.sub("", reason).strip(" .,:;—-")) < MIN_REASON


def audit_story(text):
    """Возвращает покрытие истории и список проблем. Без таблицы случаев проверять нечего."""
    rows = matrix_rows(text)
    if rows is None:
        return None, []
    tagged = [ROW_TAGS.match(row) for row in rows]
    untagged = [row for row, match in zip(rows, tagged) if not match]
    if untagged:
        return None, ["Строки без класса S1–S12: " + "; ".join(untagged)]
    covered = {tag for match in tagged for tag in split_tags(match.group(1))}
    absent = absent_classes(text)
    problems = [f"Неизвестный класс {tag}" for tag in sorted((covered | set(absent)) - set(NAMES))]
    problems += [f"{tag}: причина неприменимости не объяснена: «{reason}»" for tag, reason in absent.items() if weak_reason(reason)]
    if len(rows) < MIN_ROWS:
        problems.append(f"Сценариев {len(rows)}, нужно не меньше {MIN_ROWS}")
    if "S1" not in covered:
        problems.append("Нет основного пути S1")
    if not covered & NEGATIVE:
        problems.append("Нет негативного сценария S3–S6")
    missing = [tag for tag in ORDER if tag not in covered and tag not in absent]
    if missing:
        problems.append("Класс не покрыт и не объяснён: " + ", ".join(missing))
    return {"covered": sorted(covered & set(NAMES), key=ORDER.index), "not_applicable": absent}, problems


def guess_classes(criteria):
    """Подсказка для эпиков: слово говорит об упоминании класса, а не о качестве сценария."""
    found = {tag for tag, pattern in HINTS.items() if re.search(pattern, criteria, re.I)}
    return sorted(found | {"S1"}, key=ORDER.index)
