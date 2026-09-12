#!/usr/bin/env python3
"""Mineração preliminar e retomável das 37 publicações finais (1993–2016)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "99-FERRAMENTAS" / "minerar_lote_20_1954_1958.py"
SPEC = importlib.util.spec_from_file_location("fgmbv_mining_engine_final", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Não foi possível carregar {ENGINE_PATH}")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
Config = ENGINE.Config


BATCH = [
    Config(1993, "01", "Janeiro de 1993", 41, 1, "Voice-1993-01.pdf"),
    Config(1993, "02", "Fevereiro de 1993", 41, 2, "Voice-1993-02.pdf"),
    Config(1993, "08", "Agosto de 1993", 41, 8, "Voice-1993-08.pdf"),
    Config(1993, "10", "Outubro de 1993", 41, 10, "Voice-1993-10.pdf"),
    Config(1993, "11", "Novembro de 1993", 41, 11, "Voice-1993-11.pdf"),
    Config(1994, "10", "Outubro de 1994", 42, 10, "Voice-1994-10.pdf"),
    Config(1994, "11", "Novembro de 1994", 42, 11, "Voice-1994-11.pdf"),
    Config(1994, "99", "Relatório Global de 1994", 42, "Relatório Global", "Voice-1994-global-report.pdf"),
    Config(1995, "01", "Janeiro de 1995", 43, 1, "Voice-1995-01.pdf"),
    Config(1995, "02", "Fevereiro de 1995", 43, 2, "Voice-1995-02.pdf"),
    Config(1996, "06", "Junho de 1996", 44, 6, "Voice-1996-06.pdf"),
    Config(1997, "10", "Outubro de 1997", 45, 10, "Voice-1997-10.pdf"),
    Config(1998, "07", "Julho de 1998", 46, 7, "Voice-1998-07.pdf"),
    Config(1998, "09", "Setembro de 1998", 46, 9, "Voice-1998-09.pdf"),
    Config(1999, "01", "Janeiro de 1999", 47, 1, "Voice-1999-01.pdf"),
    Config(1999, "02", "Fevereiro de 1999", 47, 2, "Voice-1999-02.pdf"),
    Config(1999, "03", "Março de 1999", 47, 3, "Voice-1999-03.pdf"),
    Config(1999, "04", "Abril de 1999", 47, 4, "Voice-1999-04.pdf"),
    Config(1999, "07", "Julho de 1999", 47, 7, "Voice-1999-07.pdf"),
    Config(1999, "08", "Agosto de 1999", 47, 8, "Voice-1999-08.pdf"),
    Config(1999, "09", "Setembro de 1999", 47, 9, "Voice-1999-09.pdf"),
    Config(1999, "10", "Outubro de 1999", 47, 10, "Voice-1999-10.pdf"),
    Config(2000, "03", "Março de 2000", 48, 3, "Voice-2000-03.pdf"),
    Config(2000, "04", "Abril de 2000", 48, 4, "Voice-2000-04.pdf"),
    Config(2000, "10", "Outubro de 2000", 48, 10, "Voice-2000-10.pdf"),
    Config(2001, "02", "Fevereiro de 2001", 49, 2, "Voice-2001-02.pdf"),
    Config(2002, "07", "Julho de 2002", 50, 7, "Voice-2002-07.pdf"),
    Config(2003, "01", "Janeiro de 2003", 51, 1, "Voice-2003-01.pdf"),
    Config(2003, "06", "Junho de 2003", 51, 6, "Voice-2003-06.pdf"),
    Config(2003, "07", "Julho de 2003", 51, 7, "Voice-2003-07.pdf"),
    Config(2006, "01", "Janeiro de 2006", 54, 1, "Voice-2006-01.pdf"),
    Config(2006, "03", "Março de 2006", 54, 3, "Voice-2006-03.pdf"),
    Config(2006, "12", "Dezembro de 2006", 54, 12, "Voice-2006-12.pdf"),
    Config(2007, "01-02", "Janeiro–fevereiro de 2007", 55, "1-2", "Voice-2007-01-02.pdf"),
    Config(2007, "11-12", "Novembro–dezembro de 2007", 55, "11-12", "Voice-2007-11-12.pdf"),
    Config(2008, "01-02", "Janeiro–fevereiro de 2008", 56, "1-2", "Voice-2008-01-02.pdf"),
    Config(2016, "99", "Convenção Mundial de 2016", 64, "Convenção Mundial", "Voice-2016-world-convention.pdf"),
]

NUMBER_SLUG = {
    (1994, "99"): "relatorio-global",
    (2016, "99"): "convencao-mundial",
}

READINGS = [
    (2, "Leitura dirigida — testemunho principal e trajetória pessoal"),
    (5, "Leitura dirigida — fé, família e transformação de vida"),
    (8, "Leitura dirigida — profissão, negócios e serviço"),
    (11, "Leitura dirigida — comunicação e testemunho público"),
    (14, "Leitura dirigida — capítulos, convenções e alcance internacional"),
]

AUTHOR_NOISE = (
    "full gospel", "voice", "convention", "international", "chapter",
    "volume", "number", "p.o. box", "fellowship", "editorial",
)


def page_author(page: str) -> str:
    """Obtém apenas nomes claramente acompanhados de localidade/cargo."""
    for raw in page.splitlines()[:28]:
        line = re.sub(r"\s+", " ", raw).strip(" |_-")
        if any(noise in line.lower() for noise in AUTHOR_NOISE):
            continue
        match = re.match(
            r"^([A-Z][A-Za-zÀ-ÿ .’'“”-]{2,48}),\s*"
            r"(?:[A-Z][A-Za-zÀ-ÿ .'-]+|[A-Z]{2})(?:,|$)",
            line,
        )
        if match:
            return match.group(1).strip()
    return "Equipe editorial da VOICE"


for config in BATCH:
    text_path = ROOT / "02-MINERACAO" / str(config.year) / f"{Path(config.pdf_name).stem}.txt"
    pages = [page for page in text_path.read_text(encoding="utf-8", errors="replace").split("\f") if page.strip()]
    if len(pages) < READINGS[-1][0]:
        raise RuntimeError(f"OCR curto demais para mineração: {text_path}")
    ENGINE.ARTICLE_OVERRIDES[(config.year, config.month)] = [
        (page_number, title, page_author(pages[page_number - 1]))
        for page_number, title in READINGS
    ]


def update_index(summaries: list[dict], targets: list[Path], rebuild: bool) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-FINAL-JAN1993-2016-INICIO -->"
    end = "<!-- LOTE-FINAL-JAN1993-2016-FIM -->"
    if start in content and not rebuild:
        print("ÍNDICE PRESERVADO: bloco do lote já existe")
        return
    rows = []
    for summary, target in zip(summaries, targets):
        link = f"../02-MINERACAO/{target.parent.name}/{target.name}"
        rows.append(
            f"| {summary['date']} | {summary['edition']} | {summary['pages']} | "
            f"≥ {len(summary['authors'])} | {'; '.join(summary['authors'][:5])} | "
            f"{'; '.join(summary['topics'][:5])} | {'; '.join(summary['decisions'][:4])} | "
            f"[Ficha]({link}) |"
        )
    block = start + "\n" + "\n".join(rows) + "\n" + end
    if start in content:
        content = re.sub(
            re.escape(start) + r".*?" + re.escape(end),
            block, content, count=1, flags=re.DOTALL,
        )
    else:
        anchor = "<!-- LOTE-FEV1985-DEZ1992-FIM -->"
        if anchor not in content:
            raise RuntimeError("Bloco cronológico anterior não encontrado")
        content = content.replace(anchor, anchor + "\n" + block, 1)

    heading = "## Mapa temático do lote final janeiro de 1993–2016"
    map_block = f"""## Mapa temático do lote final janeiro de 1993–2016

| Assunto | Edições e veios promissores |
|---|---|
| Continuidade e transformação institucional | 1993–2016 — capítulos, relatórios globais, convenções e novas gerações |
| Fé, profissão e negócios | Todo o lote — liderança, trabalho, empreendedorismo e serviço |
| Comunicação e cultura pública | Todo o lote — revista, mídia, eventos, música e testemunho |
| Expansão internacional | Todo o lote — redes globais da FGBMFI e convenções mundiais |
| Família, conversão e reconciliação | Todo o lote — trajetórias pessoais, restauração e formação |
| Oração e curas alegadas | Presente em várias publicações — exigir cautela clínica e confirmação externa |

| Decisão potencial | Aplicação no lote |
|---|---|
| Preservar memória institucional verificável | Relatórios, convenções, números e mudanças organizacionais |
| Integrar fé e profissão | Empresas, liderança, mídia e serviço comunitário |
| Fortalecer redes internacionais | Capítulos, eventos e cooperação transcultural |
| Usar comunicação com responsabilidade | Revista, testemunhos e materiais de convenção |
| Submeter alegações à verificação | Relatos médicos, números institucionais e fatos históricos |

"""
    previous = "## Mapa temático do lote fevereiro de 1985–dezembro de 1992"
    if heading not in content:
        if previous not in content:
            raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
        content = content.replace(previous, map_block + previous, 1)
    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote final janeiro/1993–2016")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconstruir", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    created = 0
    summaries = []
    targets = []
    for config in BATCH:
        pdf = ROOT / "01-EDICOES-PDF" / str(config.year) / config.pdf_name
        text_path = ROOT / "02-MINERACAO" / str(config.year) / f"{Path(config.pdf_name).stem}.txt"
        number_slug = NUMBER_SLUG.get((config.year, config.month), str(config.number))
        target = ROOT / "02-MINERACAO" / str(config.year) / (
            f"FGMBV-{config.year}-{config.month}-v{config.volume}-n{number_slug}.md"
        )
        if not pdf.exists() or not text_path.exists():
            raise FileNotFoundError(f"Fonte ausente: {pdf} ou {text_path}")
        markdown, summary = ENGINE.render(
            config, pdf, text_path, text_path.read_text(encoding="utf-8", errors="replace")
        )
        markdown = markdown.replace(
            "| Editor | Thomas R. Nickel |", "| Editor | Equipe editorial da VOICE |", 1
        )
        existed = target.exists()
        if existed and not args.reconstruir:
            print(f"PRESERVADA: {target.relative_to(ROOT)}")
        else:
            temporary = target.with_suffix(".md.part")
            temporary.write_text(markdown, encoding="utf-8")
            temporary.replace(target)
            print(f"{'RECONSTRUÍDA' if existed else 'CRIADA'}: {target.relative_to(ROOT)}")
            created += not existed
        summaries.append(summary)
        targets.append(target)
    update_index(summaries, targets, args.reconstruir)
    print(f"Novas fichas: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
