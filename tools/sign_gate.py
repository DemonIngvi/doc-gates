#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Записывает решение человека по результату гейта.

Запуск: uv run sign_gate.py <файл результата> --by <имя> --accept 1,3 --reject 2 --sign
Находки нумеруются с единицы. Подпись ставится, только когда разобраны все находки.
"""
import argparse
import pathlib

import yaml


def numbers(value):
    return {int(item) for item in value.split(",") if item}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=pathlib.Path)
    parser.add_argument("--by", required=True)
    parser.add_argument("--accept", default="", type=numbers)
    parser.add_argument("--reject", default="", type=numbers)
    parser.add_argument("--sign", action="store_true")
    args = parser.parse_args()
    run = yaml.safe_load(args.file.read_text(encoding="utf-8"))
    for index, item in enumerate(run["findings"], 1):
        if index in (args.accept or set()):
            item.update(decision="accepted", decided_by=args.by)
        elif index in (args.reject or set()):
            item.update(decision="rejected", decided_by=args.by)
    pending = [i for i, item in enumerate(run["findings"], 1) if item["decision"] == "pending"]
    if args.sign:
        if pending:
            raise SystemExit(f"Не разобраны находки: {pending}")
        run["signed_by"] = args.by
    args.file.write_text(yaml.safe_dump(run, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"Осталось разобрать: {len(pending)}")


if __name__ == "__main__":
    main()
