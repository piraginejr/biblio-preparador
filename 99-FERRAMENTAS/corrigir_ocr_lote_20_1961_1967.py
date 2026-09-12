#!/usr/bin/env python3
"""Refaz o OCR das 20 edições de jan/1961 a set/1967 sem alterar os PDFs.

Por padrão apenas lista o lote. Com --aplicar, cria um PDF temporário com OCR
integral e substitui atomicamente somente o TXT correspondente, após validar
páginas, quantidade mínima de palavras e ausência de caracteres corrompidos.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OCR = Path("/opt/homebrew/bin/ocrmypdf")
PDFINFO = Path("/opt/homebrew/bin/pdfinfo")
PDFTOTEXT = Path("/opt/homebrew/bin/pdftotext")
PDFTOPPM = Path("/opt/homebrew/bin/pdftoppm")
TESSERACT = Path("/opt/homebrew/bin/tesseract")


@dataclass(frozen=True)
class Issue:
    year: int
    pdf_name: str


BATCH = [
    Issue(1961, "Voice - FGBMFI - 8.12 (January 1961),.pdf"),
    Issue(1961, "Voice - FGBMFI - 9.1 (February 1961).pdf"),
    Issue(1961, "Voice - FGBMFI - 9.2 (March 1961).pdf"),
    Issue(1961, "Voice - FGBMFI - 9.3 (April 1961),.pdf"),
    Issue(1961, "Voice - FGBMFI - 9.4 (May 1961).pdf"),
    Issue(1961, "Voice-1961-07.pdf"),
    Issue(1961, "Voice-1961-09.pdf"),
    Issue(1962, "Voice-1962-11.pdf"),
    Issue(1963, "Voice-1963-01.pdf"),
    Issue(1963, "Voice-1963-02.pdf"),
    Issue(1963, "Voice-1963-04.pdf"),
    Issue(1964, "Voice-1964-12.pdf"),
    Issue(1965, "Voice-1965-01.pdf"),
    Issue(1965, "Voice-1965-05.pdf"),
    Issue(1965, "Voice-1965-10.pdf"),
    Issue(1966, "Voice-1966-05.pdf"),
    Issue(1967, "Voice-1967-03.pdf"),
    Issue(1967, "Voice-1967-04.pdf"),
    Issue(1967, "Voice-1967-06.pdf"),
    Issue(1967, "Voice-1967-09.pdf"),
]


def word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z]{3,}", text))


def page_count(pdf: Path) -> int:
    result = subprocess.run(
        [PDFINFO, pdf], capture_output=True, text=True, check=True
    )
    match = re.search(r"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(f"Número de páginas não identificado em {pdf}")
    return int(match.group(1))


def correct(issue: Issue) -> str:
    pdf = ROOT / "01-EDICOES-PDF" / str(issue.year) / issue.pdf_name
    target = ROOT / "02-MINERACAO" / str(issue.year) / (
        f"{Path(issue.pdf_name).stem}.txt"
    )
    if not pdf.exists() or not target.exists():
        raise FileNotFoundError(f"Fonte ausente: {pdf} ou {target}")

    old_text = target.read_text(encoding="utf-8", errors="replace")
    old_words = word_count(old_text)
    source_pages = page_count(pdf)

    with tempfile.TemporaryDirectory(prefix=f"fgmbv-ocr-{issue.year}-") as work:
        workdir = Path(work)
        temporary_pdf = workdir / "ocr.pdf"
        temporary_txt = workdir / "ocr.txt"
        result = subprocess.run(
            [
                OCR,
                "--language",
                "eng",
                "--rotate-pages",
                "--deskew",
                "--force-ocr",
                "--output-type",
                "pdf",
                "--optimize",
                "0",
                "--jobs",
                "2",
                "--quiet",
                pdf,
                temporary_pdf,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()[-1200:]
            raise RuntimeError(f"OCR falhou em {pdf.name}: {detail}")
        if page_count(temporary_pdf) != source_pages:
            raise RuntimeError(f"OCR alterou o total de páginas de {pdf.name}")

        subprocess.run(
            [PDFTOTEXT, "-layout", temporary_pdf, temporary_txt],
            capture_output=True,
            text=True,
            check=True,
        )
        new_text = temporary_txt.read_text(encoding="utf-8", errors="replace")
        new_words = word_count(new_text)
        minimum = max(100, int(old_words * 0.75))
        if new_words < minimum:
            raise RuntimeError(
                f"OCR insuficiente em {pdf.name}: {new_words} palavras; "
                f"mínimo {minimum}"
            )
        if new_text.count("\ufffd") > old_text.count("\ufffd"):
            raise RuntimeError(f"OCR aumentou caracteres corrompidos em {pdf.name}")

        part = target.with_suffix(".txt.part")
        try:
            part.write_text(new_text, encoding="utf-8")
            part.replace(target)
        finally:
            part.unlink(missing_ok=True)

    delta = new_words - old_words
    return (
        f"CORRIGIDO: {target.relative_to(ROOT)} — {source_pages} páginas; "
        f"{new_words} palavras ({delta:+d})"
    )


def correct_pagewise(issue: Issue) -> str:
    """Alternativa controlada para PDFs que travam no OCR integral."""
    pdf = ROOT / "01-EDICOES-PDF" / str(issue.year) / issue.pdf_name
    target = ROOT / "02-MINERACAO" / str(issue.year) / (
        f"{Path(issue.pdf_name).stem}.txt"
    )
    old_text = target.read_text(encoding="utf-8", errors="replace")
    old_words = word_count(old_text)
    source_pages = page_count(pdf)
    pages = []

    with tempfile.TemporaryDirectory(prefix=f"fgmbv-pagewise-{issue.year}-") as work:
        workdir = Path(work)
        for number in range(1, source_pages + 1):
            image_base = workdir / "page"
            image = workdir / "page.png"
            subprocess.run(
                [
                    PDFTOPPM,
                    "-f",
                    str(number),
                    "-l",
                    str(number),
                    "-r",
                    "300",
                    "-gray",
                    "-singlefile",
                    "-png",
                    pdf,
                    image_base,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=90,
            )
            result = subprocess.run(
                [
                    TESSERACT,
                    image,
                    "stdout",
                    "-l",
                    "eng",
                    "--psm",
                    "1",
                    "-c",
                    "preserve_interword_spaces=1",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=90,
            )
            pages.append(result.stdout.rstrip())
            image.unlink(missing_ok=True)
            if number % 4 == 0 or number == source_pages:
                print(f"PÁGINAS OCR: {number}/{source_pages}", flush=True)

    new_text = "\n\f".join(pages) + "\n\f"
    new_words = word_count(new_text)
    minimum = max(100, int(old_words * 0.75))
    if new_words < minimum:
        raise RuntimeError(
            f"OCR página a página insuficiente: {new_words}; mínimo {minimum}"
        )
    if new_text.count("\ufffd") > old_text.count("\ufffd"):
        raise RuntimeError("OCR página a página aumentou caracteres corrompidos")
    part = target.with_suffix(".txt.part")
    try:
        part.write_text(new_text, encoding="utf-8")
        part.replace(target)
    finally:
        part.unlink(missing_ok=True)
    return (
        f"CORRIGIDO PÁGINA A PÁGINA: {target.relative_to(ROOT)} — "
        f"{source_pages} páginas; {new_words} palavras ({new_words - old_words:+d})"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Refaz o OCR e substitui os TXT validados.",
    )
    parser.add_argument(
        "--processos",
        type=int,
        default=2,
        choices=range(1, 5),
        metavar="1-4",
        help="Edições processadas simultaneamente (padrão: 2).",
    )
    parser.add_argument(
        "--somente",
        type=int,
        choices=range(1, len(BATCH) + 1),
        metavar=f"1-{len(BATCH)}",
        help="Processa somente a edição desta posição no lote.",
    )
    parser.add_argument(
        "--pagina-a-pagina",
        action="store_true",
        help="Usa OCR controlado por página; requer --somente.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not all(
        tool.exists() for tool in (OCR, PDFINFO, PDFTOTEXT, PDFTOPPM, TESSERACT)
    ):
        raise FileNotFoundError("Ferramenta de PDF/OCR não encontrada")
    if args.pagina_a_pagina and not args.somente:
        raise ValueError("--pagina-a-pagina requer --somente")
    selected = [BATCH[args.somente - 1]] if args.somente else BATCH
    if not args.aplicar:
        print("SIMULAÇÃO: nenhum TXT será modificado")
        for issue in selected:
            print(f"- {issue.year}/{issue.pdf_name}")
        return 0

    if args.pagina_a_pagina:
        print(correct_pagewise(selected[0]))
        return 0

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.processos) as pool:
        future_map = {pool.submit(correct, issue): issue for issue in selected}
        for future in concurrent.futures.as_completed(future_map):
            issue = future_map[future]
            try:
                print(future.result(), flush=True)
            except Exception as error:
                failures.append((issue, error))
                print(f"FALHOU: {issue.pdf_name} — {error}", flush=True)
    print(f"Corrigidos: {len(selected) - len(failures)}; falhas: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
