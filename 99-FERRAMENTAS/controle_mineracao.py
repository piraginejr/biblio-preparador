#!/usr/bin/env python3
"""Gera o controle cronológico e retomável da mineração do acervo FGMBV."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "aug": 8,
    "august": 8,
    "september": 9,
    "sept": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
MONTH_LABELS = {
    1: "jan.",
    2: "fev.",
    3: "mar.",
    4: "abr.",
    5: "mai.",
    6: "jun.",
    7: "jul.",
    8: "ago.",
    9: "set.",
    10: "out.",
    11: "nov.",
    12: "dez.",
}


@dataclass(frozen=True)
class Issue:
    year: int
    month: int
    end_month: int | None
    pdf: Path
    text: Path
    label: str

    @property
    def key(self) -> tuple[int, int]:
        return self.year, self.month

    @property
    def date_label(self) -> str:
        if self.month == 99:
            return str(self.year)
        start = MONTH_LABELS[self.month]
        if self.end_month and self.end_month != self.month:
            return f"{start}-{MONTH_LABELS[self.end_month]} {self.year}"
        return f"{start} {self.year}"


def parse_issue(root: Path, pdf: Path) -> Issue:
    year = int(pdf.parent.name)
    stem = pdf.stem
    month = 99
    end_month = None

    compact = re.search(r"Voice-(\d{4})-(\d{2})(?:-(\d{2}))?", stem)
    curated = re.search(r"FGMBV-(\d{4})-(\d{2})", stem)
    if compact:
        month = int(compact.group(2))
        end_month = int(compact.group(3)) if compact.group(3) else None
    elif curated:
        month = int(curated.group(2))
    else:
        parenthetical = re.search(r"\(([^)]*)\)", stem)
        if parenthetical:
            words = re.findall(r"[A-Za-z]+", parenthetical.group(1))
            parsed_months = [MONTHS[w.lower()] for w in words if w.lower() in MONTHS]
            if parsed_months:
                month = parsed_months[0]
                if len(parsed_months) > 1:
                    end_month = parsed_months[1]

    volume = re.search(r"FGBMFI - ([0-9]+\.[0-9]+)", stem)
    if volume:
        label = f"Vol. {volume.group(1).replace('.', ', nº ', 1)}"
    elif curated:
        volume_number = re.search(r"-v(\d+)-n([0-9-]+)", stem)
        label = (
            f"Vol. {volume_number.group(1)}, nº {volume_number.group(2)}"
            if volume_number
            else stem
        )
    else:
        ficha_pattern = f"FGMBV-{year}-{month:02d}*-v*-n*.md"
        fichas = sorted((root / "02-MINERACAO" / str(year)).glob(ficha_pattern))
        volume_number = (
            re.search(r"-v(\d+)-n([0-9-]+)", fichas[0].stem) if fichas else None
        )
        if fichas:
            date_range = re.search(
                rf"FGMBV-{year}-{month:02d}-(\d{{2}})-v", fichas[0].stem
            )
            if date_range:
                end_month = int(date_range.group(1))
        label = (
            f"Vol. {volume_number.group(1)}, nº {volume_number.group(2)}"
            if volume_number
            else stem.removeprefix("Voice-").replace("-", " ")
        )

    text = root / "02-MINERACAO" / str(year) / f"{stem}.txt"
    return Issue(year, month, end_month, pdf, text, label)


def markdown_link(label: str, target: Path, base: Path) -> str:
    relative = os.path.relpath(target, start=base.parent)
    encoded = quote(relative, safe="/._-")
    return f"[{label}]({encoded})"


def ficha_map(root: Path) -> dict[tuple[int, int], Path]:
    result: dict[tuple[int, int], Path] = {}
    for ficha in sorted((root / "02-MINERACAO").rglob("*.md")):
        match = re.search(r"(?:FGMBV|Voice)-(\d{4})-(\d{2})", ficha.stem)
        if match:
            result[(int(match.group(1)), int(match.group(2)))] = ficha
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raiz",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Raiz do projeto.",
    )
    return parser.parse_args()


def main() -> int:
    root = parse_args().raiz.resolve()
    output = root / "00-INDICE" / "FGMBV-PROGRESSO.md"
    issues = sorted(
        (parse_issue(root, pdf) for pdf in (root / "01-EDICOES-PDF").rglob("*.pdf")),
        key=lambda issue: (issue.year, issue.month, issue.pdf.name),
    )
    fichas = ficha_map(root)

    completed = [issue for issue in issues if issue.key in fichas]
    waiting = [issue for issue in issues if issue.key not in fichas and issue.text.exists()]
    missing_text = [issue for issue in issues if not issue.text.exists()]
    next_issue = waiting[0] if waiting else None

    lines = [
        "# Controle cronológico da mineração FGMBV",
        "",
        "Este arquivo é gerado a partir dos PDFs, textos pesquisáveis e fichas",
        "existentes. Cada edição só é marcada como concluída depois que sua ficha",
        "individual foi salva. A próxima edição é sempre a primeira pendência na",
        "ordem cronológica.",
        "",
        f"- Atualizado em: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')}",
        f"- Acervo: {len(issues)} edições",
        f"- Fichas concluídas: {len(completed)}",
        f"- Aguardando mineração: {len(waiting)}",
        f"- Sem texto pesquisável: {len(missing_text)}",
    ]
    if completed:
        last = completed[-1]
        lines.append(f"- Última edição concluída: {last.date_label} — {last.label}")
    if next_issue:
        lines.append(f"- Próxima edição: **{next_issue.date_label} — {next_issue.label}**")

    lines.extend(
        [
            "",
            "## Fila completa",
            "",
            "| Ordem | Data | Edição | Estado | PDF | Texto | Ficha |",
            "|---:|---|---|---|---|---|---|",
        ]
    )
    for number, issue in enumerate(issues, 1):
        ficha = fichas.get(issue.key)
        if ficha:
            state = "Concluída"
        elif issue.text.exists():
            state = "Aguardando mineração"
        else:
            state = "Sem texto"
        pdf_link = markdown_link("PDF", issue.pdf, output)
        text_link = (
            markdown_link("TXT", issue.text, output) if issue.text.exists() else "—"
        )
        ficha_link = markdown_link("Ficha", ficha, output) if ficha else "—"
        lines.append(
            f"| {number} | {issue.date_label} | {issue.label} | {state} | "
            f"{pdf_link} | {text_link} | {ficha_link} |"
        )

    temporary = output.with_suffix(".md.part")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temporary.replace(output)
    print(f"Controle atualizado: {output.relative_to(root)}")
    print(
        f"{len(completed)} concluídas; {len(waiting)} aguardando; "
        f"{len(missing_text)} sem texto."
    )
    if next_issue:
        print(f"Próxima: {next_issue.date_label} — {next_issue.label}")
    return 1 if missing_text else 0


if __name__ == "__main__":
    raise SystemExit(main())
