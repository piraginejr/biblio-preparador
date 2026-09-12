#!/usr/bin/env python3
"""Extrai, sem sobrescrever, o texto já embutido nos PDFs do acervo.

O programa prepara 02-MINERACAO para a mineração editorial. Ele não altera
nenhum PDF e não tenta OCR: arquivos sem texto suficiente são apenas
registrados como pendentes para tratamento separado.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


MIN_WORDS = 50


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÿ]{3,}", text))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raiz",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Raiz do projeto (padrão: detectada a partir deste programa).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.raiz.resolve()
    pdf_root = root / "01-EDICOES-PDF"
    text_root = root / "02-MINERACAO"
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        print("ERRO: pdftotext não encontrado.", file=sys.stderr)
        return 2

    created = 0
    existing = 0
    pending: list[tuple[Path, int]] = []

    for pdf in sorted(pdf_root.rglob("*.pdf")):
        year = pdf.parent.name
        target_dir = text_root / year
        target = target_dir / f"{pdf.stem}.txt"
        if target.exists():
            existing += 1
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".txt.part")
        result = subprocess.run(
            [pdftotext, "-layout", str(pdf), str(temporary)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            temporary.unlink(missing_ok=True)
            pending.append((pdf, 0))
            continue

        text = temporary.read_text(encoding="utf-8", errors="replace")
        words = word_count(text)
        if words < MIN_WORDS:
            temporary.unlink(missing_ok=True)
            pending.append((pdf, words))
            continue

        temporary.replace(target)
        created += 1
        print(f"CRIADO: {target.relative_to(root)} ({words} palavras)")

    print()
    print(f"Textos já existentes: {existing}")
    print(f"Textos extraídos agora: {created}")
    print(f"Pendentes de OCR: {len(pending)}")
    for pdf, words in pending:
        print(f"PENDENTE: {pdf.relative_to(root)} ({words} palavras extraídas)")
    return 1 if pending else 0


if __name__ == "__main__":
    raise SystemExit(main())
