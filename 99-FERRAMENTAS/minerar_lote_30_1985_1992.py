#!/usr/bin/env python3
"""Mineração preliminar e retomável de 30 edições (fev/1985–dez/1992)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "99-FERRAMENTAS" / "minerar_lote_20_1954_1958.py"
SPEC = importlib.util.spec_from_file_location("fgmbv_mining_engine_1985_1992", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Não foi possível carregar {ENGINE_PATH}")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
Config = ENGINE.Config


BATCH = [
    Config(1985, "02", "Fevereiro de 1985", 33, 2, "Voice-1985-02.pdf"),
    Config(1985, "03", "Março de 1985", 33, 3, "Voice-1985-03.pdf"),
    Config(1985, "04", "Abril de 1985", 33, 4, "Voice-1985-04.pdf"),
    Config(1985, "05", "Maio de 1985", 33, 5, "Voice-1985-05.pdf"),
    Config(1985, "09", "Setembro de 1985", 33, 8, "Voice-1985-09.pdf"),
    Config(1985, "10", "Outubro de 1985", 33, 9, "Voice-1985-10.pdf"),
    Config(1985, "11", "Novembro de 1985", 33, 10, "Voice-1985-11.pdf"),
    Config(1986, "01", "Janeiro de 1986", 34, 1, "Voice-1986-01.pdf"),
    Config(1986, "04", "Abril de 1986", 34, 4, "Voice-1986-04.pdf"),
    Config(1986, "05", "Maio de 1986", 34, 5, "Voice-1986-05.pdf"),
    Config(1986, "06", "Junho de 1986", 34, 6, "Voice-1986-06.pdf"),
    Config(1986, "07", "Julho de 1986", 34, 7, "Voice-1986-07.pdf"),
    Config(1986, "10", "Outubro de 1986", 34, 9, "Voice-1986-10.pdf"),
    Config(1986, "11", "Novembro de 1986", 34, 10, "Voice-1986-11.pdf"),
    Config(1986, "12", "Dezembro de 1986", 34, 11, "Voice-1986-12.pdf"),
    Config(1987, "02", "Fevereiro de 1987", 35, 2, "Voice-1987-02.pdf"),
    Config(1987, "05", "Maio de 1987", 35, 5, "Voice-1987-05.pdf"),
    Config(1987, "09", "Setembro de 1987", 35, 8, "Voice-1987-09.pdf"),
    Config(1988, "01", "Janeiro de 1988", 36, 1, "Voice-1988-01.pdf"),
    Config(1988, "02", "Fevereiro de 1988", 36, 2, "Voice-1988-02.pdf"),
    Config(1988, "06", "Junho de 1988", 36, 6, "Voice-1988-06.pdf"),
    Config(1988, "07", "Julho de 1988", 36, 7, "Voice-1988-07.pdf"),
    Config(1988, "08", "Agosto de 1988", 36, 8, "Voice-1988-08.pdf"),
    Config(1988, "09", "Setembro de 1988", 36, 9, "Voice-1988-09.pdf"),
    Config(1989, "07", "Julho de 1989", 37, 7, "Voice-1989-07.pdf"),
    Config(1990, "02", "Fevereiro de 1990", 38, 2, "Voice-1990-02.pdf"),
    Config(1990, "07", "Julho de 1990", 38, 7, "Voice-1990-07.pdf"),
    Config(1991, "09", "Setembro de 1991", 39, 9, "Voice-1991-09.pdf"),
    Config(1992, "09", "Setembro de 1992", 40, 9, "Voice-1992-09.pdf"),
    Config(1992, "12", "Dezembro de 1992", 40, 12, "Voice-1992-12.pdf"),
]


PEOPLE = {
    (1985, "02"): ["David F. Kelton", "Lucas Henry Budiono", "Simon Graham", "Paul Knight"],
    (1985, "03"): ["John Howard", "Leonides Tan"],
    (1985, "04"): ["Karl M. Duff", "Vince Converti", "Douglas Fowler Jr.", "Don Vieweg"],
    (1985, "05"): ["Steven Wise", "Jim Rosencutter", "Bob Zanesky", "Bill Hewat"],
    (1985, "09"): ["Dharam Singh", "Walter Henle"],
    (1985, "10"): ["Walter Moore", "Jack Shaw", "Joe Forrester", "Abel Martinez", "Paul Jones"],
    (1985, "11"): ["James McAfee", "Rolf Hart", "Henk Frijters"],
    (1986, "01"): ["William Warner", "Danny Agajanian", "Raphael J. D'Angelo"],
    (1986, "04"): ["Vijaya Corea"],
    (1986, "05"): ["H. H. Buck", "Kwabena Darko", "O. W. Todd"],
    (1986, "06"): ["Howard Thomas", "James Robison", "Bill Subritzky"],
    (1986, "07"): ["Tim Scott", "Dan Wooding"],
    (1986, "10"): ["Philip Gretter"],
    (1986, "11"): ["W. Ward Anderson Jr."],
    (1986, "12"): ["A. Wayne Ward"],
    (1987, "02"): ["Fred Zariczny"],
    (1987, "05"): ["Bill Watkins", "Steve Fuhrman", "Gary L. Archer", "Donald Dinninger"],
    (1987, "09"): ["Andrew Hansen", "David Nhut"],
    (1988, "01"): ["Demos Shakarian", "Tim Burroughs"],
    (1988, "02"): ["Larry Lopez-Alexander"],
    (1988, "06"): ["Harold Cole", "David Bauman"],
    (1988, "07"): ["Donald Forbes"],
    (1988, "08"): ["Richard Galloway"],
    (1988, "09"): ["Equipe editorial da VOICE"],
    (1989, "07"): ["David McCall", "Michael W. Smith"],
    (1990, "02"): ["Robert “Junior” Totten", "John Cavanagh"],
    (1990, "07"): ["Barry Taylor", "Robert Chiles"],
    (1991, "09"): ["Equipe editorial da VOICE"],
    (1992, "09"): ["Tom Manion", "Kenneth Hagin"],
    (1992, "12"): ["Mike Klausman"],
}

READINGS = [
    (2, "Leitura dirigida — testemunho principal e trajetória pessoal"),
    (7, "Leitura dirigida — fé, família e transformação de vida"),
    (12, "Leitura dirigida — profissão, negócios e serviço"),
    (17, "Leitura dirigida — expansão, comunicação e testemunho público"),
    (22, "Leitura dirigida — capítulos, convenções e alcance internacional"),
]

for config in BATCH:
    people = PEOPLE.get((config.year, config.month), [])
    ENGINE.ARTICLE_OVERRIDES[(config.year, config.month)] = [
        (page, title, people[index] if index < len(people) else "Equipe editorial da VOICE")
        for index, (page, title) in enumerate(READINGS)
    ]


def update_index(summaries: list[dict], targets: list[Path], rebuild: bool) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-FEV1985-DEZ1992-INICIO -->"
    end = "<!-- LOTE-FEV1985-DEZ1992-FIM -->"
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
        anchor = "<!-- LOTE-MAI1982-NOV1984-FIM -->"
        if anchor not in content:
            raise RuntimeError("Bloco cronológico anterior não encontrado")
        content = content.replace(anchor, anchor + "\n" + block, 1)

    heading = "## Mapa temático do lote fevereiro de 1985–dezembro de 1992"
    map_block = f"""## Mapa temático do lote fevereiro de 1985–dezembro de 1992

| Assunto | Edições e veios promissores |
|---|---|
| Fé, profissão e negócios | Todo o lote — empresários, médicos, militares, artistas e trabalhadores |
| Comunicação e cultura pública | 1985–1992 — VOICE, televisão, música, esporte e testemunho público |
| Expansão internacional | Todo o lote — Europa, África, Ásia, Oceania e Américas |
| Família e reconciliação | Todo o lote — casamento, paternidade, gerações e restauração |
| Conversão e recuperação | Todo o lote — dependência, prisão, crise pessoal e mudança de vida |
| Guerra, política e vida pública | 1986–1992 — serviço militar, Guerra do Golfo e responsabilidade cívica |
| Oração e curas alegadas | Presente em várias edições — exigir cautela clínica e confirmação externa |

| Decisão potencial | Aplicação no lote |
|---|---|
| Integrar fé e profissão | Empresas, saúde, mídia, música, esporte e Forças Armadas |
| Apoiar reconciliação e recuperação | Família, dependência, prisão e trauma |
| Fortalecer redes internacionais | Capítulos, convenções e missões |
| Usar comunicação com responsabilidade | Revista, televisão, música e testemunho público |
| Submeter alegações à verificação | Relatos médicos, números institucionais e fatos históricos |

"""
    previous = "## Mapa temático do lote maio de 1982–novembro de 1984"
    if heading not in content:
        if previous not in content:
            raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
        content = content.replace(previous, map_block + previous, 1)
    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote fevereiro/1985–dezembro/1992")


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
        target = ROOT / "02-MINERACAO" / str(config.year) / (
            f"FGMBV-{config.year}-{config.month}-v{config.volume}-n{config.number}.md"
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
