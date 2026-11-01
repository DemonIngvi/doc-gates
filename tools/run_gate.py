#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Запускает LLM-гейт в минимальном контексте: без инструментов, настроек, памяти и MCP.

Запуск: uv run run_gate.py G01 --root <проект> --target <файл истории>
Перед тратой токенов проверяет: скрипты зелёные, вход изменился, бюджет задан.
Коды выхода: 0 готово, 1 ошибка, 2 запуск не разрешён, 3 факт превысил оценку вдвое.
Путь к Claude Code задаётся переменной CLAUDE_BIN.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from build_packet import build  # noqa: E402
from project import Project  # noqa: E402

SYSTEM = "Ты независимый ревьюер документации. Выполни инструкцию из начала сообщения. Отвечай на русском."
ESTIMATES = {"G01": 7700, "G02": 6300, "G08": 3300, "G11": 20800}
TEMPLATE_SHARE = 0.1


def ask(packet, model):
    command = [
        os.environ.get("CLAUDE_BIN", "claude"), "-p",
        "--model", model,
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
        "--system-prompt", SYSTEM,
        "--output-format", "json",
    ]
    done = subprocess.run(command, input=packet, capture_output=True, encoding="utf-8", timeout=600)
    if done.returncode:
        raise SystemExit(done.stdout[-800:] + done.stderr[-800:])
    return json.loads(done.stdout)


def parse(reply):
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        raise SystemExit("Ответ не содержит JSON:\n" + reply[:500])
    return json.loads(match.group(0))


def squeeze(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def verify(findings, packet):
    """Оставляет находки с дословной цитатой и отклоняет шаблонные ответы."""
    source = squeeze(packet)
    kept, dropped = [], []
    for item in findings:
        (kept if squeeze(item.get("quote", "")) in source and item.get("quote") else dropped).append(item)
    if len(kept) >= 5:
        common = max((sum(f["problem"] == g["problem"] for g in kept) for f in kept), default=0)
        if common / len(kept) > TEMPLATE_SHARE and common > 1:
            raise SystemExit("Находки шаблонные: один текст у нескольких, результат отклонён")
    return kept, dropped


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gate", choices=sorted(ESTIMATES))
    parser.add_argument("--root", default=".")
    parser.add_argument("--target", help="Файл истории для G01")
    parser.add_argument("--format", choices=["yaml", "md"], default=None, help="Откуда брать архитектуру")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--author", default="unknown", help="Кто писал документ")
    parser.add_argument("--run-id", default="", help="Метка повтора при калибровке")
    parser.add_argument("--force", action="store_true", help="Обойти проверку скриптов и повтора")
    args = parser.parse_args()

    project = Project(args.root)
    run_by = f"run_gate.py {args.model}"
    if args.author == run_by:
        sys.exit("Автор и проверяющий совпадают, вердикт был бы недействителен")

    report = project.quality / "check-report.yaml"
    if not args.force:
        state = yaml.safe_load(report.read_text(encoding="utf-8")) if report.exists() else None
        if not state:
            print("Сначала запустите check.py", file=sys.stderr)
            sys.exit(2)
        if not state["ok"]:
            print(f"LLM не запущен: блокеров у скриптов {state['blockers']}. Они дешевле, сначала их.", file=sys.stderr)
            sys.exit(2)

    packet = build(args.gate, project, args.target, args.format)
    digest = hashlib.sha256(packet.encode("utf-8")).hexdigest()
    slug = pathlib.Path(args.target).stem if args.target else "project"
    suffix = f"-{args.run_id}" if args.run_id else ""
    out = project.quality / args.gate / f"{slug}{suffix}.yaml"
    if out.exists() and not args.force and yaml.safe_load(out.read_text(encoding="utf-8"))["input_hash"] == digest:
        print("Вход не изменился, повторный запуск не нужен", file=sys.stderr)
        sys.exit(2)

    reply = ask(packet, args.model)
    usage = reply.get("usage", {})
    fresh = usage.get("input_tokens", 0) + usage.get("cache_creation_input_tokens", 0)
    tokens = fresh + usage.get("cache_read_input_tokens", 0) + usage.get("output_tokens", 0)
    answer = parse(reply.get("result", ""))
    kept, dropped = verify(answer.get("findings", []), packet)
    estimate = ESTIMATES[args.gate]
    result = {
        "gate": args.gate,
        "target": slug,
        "input_hash": digest,
        "run_by": run_by,
        "author": args.author,
        "verdict": answer.get("verdict"),
        "tokens": tokens,
        "estimate": estimate,
        "cost_usd": reply.get("total_cost_usd"),
        "not_checked": "Один запуск не доказывает полноту, разные запуски находят разное",
        "findings": [{**item, "decision": "pending", "decided_by": "pending"} for item in kept],
        "dropped_without_quote": dropped,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
    log = project.quality / "cost-log.yaml"
    entry = {"date": datetime.date.today().isoformat(), "gate": args.gate, "target": slug, "model": args.model,
             "tokens": tokens, "estimate": estimate, "ratio": round(tokens / estimate, 2)}
    with log.open("a", encoding="utf-8") as handle:
        handle.write(yaml.safe_dump([entry], allow_unicode=True, sort_keys=False))
    print(json.dumps({k: entry[k] for k in ("gate", "tokens", "estimate", "ratio")} | {
        "verdict": result["verdict"], "kept": len(kept), "dropped": len(dropped)}, ensure_ascii=False))
    if tokens > estimate * 2:
        print("Факт превысил оценку вдвое: остановитесь и найдите причину", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
