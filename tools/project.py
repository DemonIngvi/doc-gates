"""Находит документы проекта BMAD: папки запусков содержат дату, поэтому берётся самая новая."""
import pathlib
import re


class Project:
    def __init__(self, root):
        self.root = pathlib.Path(root).resolve()
        self.output = self.root / "_bmad-output"
        self.plan = self.output / "planning-artifacts"
        self.impl = self.output / "implementation-artifacts"
        self.quality = self.root / "_quality"
        self.architecture = self.root / "docs" / "architecture"

    def latest(self, pattern):
        found = sorted(self.plan.glob(pattern))
        return found[-1] if found else None

    @property
    def prd(self):
        return self.latest("prds/*/prd.md")

    @property
    def spine(self):
        return self.latest("architecture/*/ARCHITECTURE-SPINE.md")

    @property
    def experience(self):
        return self.latest("ux-designs/*/EXPERIENCE.md")

    @property
    def epics(self):
        path = self.plan / "epics.md"
        return path if path.exists() else None

    def stories(self):
        """Файлы историй: у спецификации bmad-build всегда есть поле route."""
        found = []
        for path in sorted(self.impl.glob("*.md")):
            if re.search(r"^route:", read(path)[:1000], re.M):
                found.append(path)
        return found


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def section(text, start, stop=None):
    """Возвращает часть документа от заголовка start до заголовка stop."""
    begin = text.index(start)
    end = text.index(stop, begin + 1) if stop and stop in text[begin + 1:] else len(text)
    return text[begin:end].strip()


def glossary(prd_text):
    return section(prd_text, "Glossary", "## 4. Features")
