#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Сравнивает повторные запуски гейта по заранее заданным признакам известных дефектов.

Запуск: uv run compare_runs.py <папка результатов> --expect name=регулярное_выражение ...
"""
import argparse
import pathlib
import re

import yaml

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("folder", type=pathlib.Path)
parser.add_argument("--expect", action="append", default=[])
parser.add_argument("--show", action="store_true")
args = parser.parse_args()
expected = dict(item.split("=", 1) for item in args.expect)

for path in sorted(args.folder.glob("*.yaml")):
    run = yaml.safe_load(path.read_text(encoding="utf-8"))
    findings = run["findings"]
    text = " ".join(f"{f.get('quote', '')} {f['problem']}" for f in findings)
    hits = {name: bool(re.search(pattern, text, re.I)) for name, pattern in expected.items()}
    blockers = sum(f["level"] == "blocker" for f in findings)
    marks = " ".join(f"{name}={'да' if hit else 'НЕТ'}" for name, hit in hits.items())
    print(f"{path.stem[-6:]:8} токенов {run['tokens']:6} вердикт {run['verdict']:9} блокеров {blockers} {marks}")
    if args.show:
        for item in findings:
            print(f"   [{item['level']}] {item['problem'][:150]}")
