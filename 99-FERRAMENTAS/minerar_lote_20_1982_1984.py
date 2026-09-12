#!/usr/bin/env python3
"""Mineração preliminar e retomável de 20 edições (mai/1982–nov/1984)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "99-FERRAMENTAS" / "minerar_lote_20_1954_1958.py"
SPEC = importlib.util.spec_from_file_location("fgmbv_mining_engine_1982_1984", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Não foi possível carregar {ENGINE_PATH}")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
Config = ENGINE.Config


BATCH = [
    Config(1982, "05", "Maio de 1982", 30, 5, "Voice-1982-05.pdf"),
    Config(1982, "06", "Junho de 1982", 30, 6, "Voice-1982-06.pdf"),
    Config(1982, "07-08", "Julho–agosto de 1982", 30, 7, "Voice-1982-07-08.pdf"),
    Config(1982, "09", "Setembro de 1982", 30, 8, "Voice-1982-09.pdf"),
    Config(1982, "12", "Dezembro de 1982", 30, 11, "Voice-1982-12.pdf"),
    Config(1983, "01", "Janeiro de 1983", 31, 1, "Voice-1983-01.pdf"),
    Config(1983, "02", "Fevereiro de 1983", 31, 2, "Voice-1983-02.pdf"),
    Config(1983, "04", "Abril de 1983", 31, 4, "Voice-1983-04.pdf"),
    Config(1983, "07-08", "Julho–agosto de 1983", 31, 7, "Voice-1983-07-08.pdf"),
    Config(1983, "09", "Setembro de 1983", 31, 8, "Voice-1983-09.pdf"),
    Config(1983, "10", "Outubro de 1983", 31, 9, "Voice-1983-10.pdf"),
    Config(1983, "11", "Novembro de 1983", 31, 10, "Voice-1983-11.pdf"),
    Config(1984, "02", "Fevereiro de 1984", 32, 2, "Voice-1984-02.pdf"),
    Config(1984, "03", "Março de 1984", 32, 3, "Voice-1984-03.pdf"),
    Config(1984, "04", "Abril de 1984", 32, 4, "Voice-1984-04.pdf"),
    Config(1984, "05", "Maio de 1984", 32, 5, "Voice-1984-05.pdf"),
    Config(1984, "08", "Agosto de 1984", 32, 7, "Voice-1984-08.pdf"),
    Config(1984, "09", "Setembro de 1984", 32, 8, "Voice-1984-09.pdf"),
    Config(1984, "10", "Outubro de 1984", 32, 9, "Voice-1984-10.pdf"),
    Config(1984, "11", "Novembro de 1984", 32, 10, "Voice-1984-11.pdf"),
]


OVERRIDES = {
    (1982, "05"): [
        (2, "Adventure in the South Seas", "Al Enderle"),
        (5, "How Can God Possibly Exist?", "Khoo Kay Peng"),
        (8, "A Bridge to Faith", "Wayne Gillie"),
        (13, "The Bridge", "Equipe editorial"),
        (14, "Voice as a Witnessing Instrument", "Equipe editorial"),
    ],
    (1982, "06"): [
        (2, "The Man Who Wouldn't Die", "Cecil Jeffries"),
        (5, "Abused", "Equipe editorial"),
        (8, "Lifetime Commitment", "Equipe editorial"),
        (15, "Unemployed", "John M. Packer"),
        (19, "Singapore and Corpus Christi Outreach", "Equipe editorial"),
    ],
    (1982, "07-08"): [
        (2, "Charlie Watson's Story", "Charlie Watson"),
        (6, "A World at the Nuclear Crossroads", "Demos Shakarian"),
        (8, "A Call to India", "Terry D'Souza"),
        (10, "Four Generations", "Ed Longshore"),
        (16, "No Money Left to Print Voice", "Earl Draper"),
    ],
    (1982, "09"): [
        (2, "The Brave Get Braver", "Bob Wieland"),
        (6, "A Marriage Restored", "Russell Linenkohl"),
        (8, "Faith on the Family Farm", "Ogburn Yates Jr."),
        (13, "Triumph in Tragedy", "Equipe editorial"),
        (16, "Coming Together", "Demos Shakarian"),
    ],
    (1982, "12"): [
        (2, "The Missing Ingredient", "Norman Frost"),
        (6, "The Alfalfa Fields", "Bob Jorgensen"),
        (8, "Dare the Devil", "Henry F. Lackey"),
        (13, "Seeking First the Kingdom", "Allen D. Hanson"),
        (19, "A Call to Honduras", "Oscar Pinto Rossell"),
    ],
    (1983, "01"): [
        (2, "The Enforcer", "Jack Burbridge"),
        (8, "Success and Surrender", "James Thorsen"),
        (14, "A Life Revolutionized", "Ian Smith"),
        (20, "International Fellowship", "Equipe editorial"),
        (22, "From Crime to a New Life", "Equipe editorial"),
    ],
    (1983, "02"): [
        (2, "Stronger Than Steel", "Wayne Alderson"),
        (6, "A Path Through the Snow", "Dick Bonson"),
        (13, "Called from the Patrol Car", "Paul Backlund"),
        (16, "Fellowship Update", "Equipe editorial"),
        (24, "Just Leave Me Alone", "Fred Lawrence"),
    ],
    (1983, "04"): [
        (2, "Behind the Bars", "Equipe editorial"),
        (6, "The Fastest Man Alive", "Jim Ryun"),
        (10, "Faith Under Fire", "Henry L. Ingram Jr."),
        (14, "Being Right", "Heinrich Hartmann"),
        (18, "Regional Conventions", "Equipe editorial"),
    ],
    (1983, "07-08"): [
        (2, "An Astronaut's Decision", "Robert C. Springer"),
        (7, "Somebody Do Something!", "Tommy Ashcraft"),
        (14, "The Case for Faith", "Lionel A. Luckhoo"),
        (20, "Three Decades of Conventions", "Equipe editorial"),
        (22, "From Bank Robbery to Service", "Tom Coleman"),
    ],
    (1983, "09"): [
        (2, "A Life Changed in the Shop", "Equipe editorial"),
        (6, "Freedom from Alcohol", "Equipe editorial"),
        (9, "A Company in Crisis", "Equipe editorial"),
        (15, "The Bible Meeting", "Equipe editorial"),
        (18, "Motor City Renewal", "Equipe editorial"),
    ],
    (1983, "10"): [
        (2, "Ambition and a New Direction", "Frank Heaston"),
        (7, "Fellowship News Around the World", "Equipe editorial"),
        (9, "A Physician's Personal Struggle", "Lance B. Johnson"),
        (16, "I Gave My Heart to Hitler", "Equipe editorial"),
        (19, "Echoes of the World Convention", "Equipe editorial"),
    ],
    (1983, "11"): [
        (2, "Battle for America", "James G. Watt"),
        (8, "The Outlaw", "Paul Hughes"),
        (14, "What a Miracle", "Equipe editorial"),
        (17, "A Rescue Under Fire", "Equipe editorial"),
        (19, "Ministry in Australia", "Equipe editorial"),
    ],
    (1984, "02"): [
        (2, "Believed", "Fred Ferrari"),
        (4, "Ministry Behind Bars", "Equipe editorial"),
        (8, "Meeting in Miami", "Equipe editorial"),
        (16, "A Physician Faces His Own Crisis", "Russell Lambert"),
        (20, "Leadership and Convention Ministry", "Equipe editorial"),
    ],
    (1984, "03"): [
        (2, "The Plastic Surgeon", "Equipe editorial"),
        (8, "The Competitor", "Robert Horton"),
        (12, "Saved by a Voice", "Bill Street Jr."),
        (18, "Fellowship News Around the World", "Equipe editorial"),
        (20, "Convention Ministry", "Equipe editorial"),
    ],
    (1984, "04"): [
        (2, "The Life of a Governor", "Julian M. Carroll"),
        (7, "The Final Rescue", "Ray Duerre"),
        (12, "From the Cotton Fields", "Cleve Howard"),
        (17, "Delivered and Set Free", "Equipe editorial"),
        (19, "Regional Convention Report", "Equipe editorial"),
    ],
    (1984, "05"): [
        (3, "Faith in the Rodeo", "Phil Doan"),
        (6, "Top Ten", "Gene Brock"),
        (10, "A New Goal for Life", "Manfred Ohmes"),
        (19, "An Olympic Challenge", "Equipe editorial"),
        (26, "Fellowship News Around the World", "Equipe editorial"),
    ],
    (1984, "08"): [
        (2, "The Road from Success to Faith", "Lee Buck"),
        (7, "Arm Wrestling and Witness", "David Story"),
        (14, "A Dream and a New Life", "Jacob H. Eckert"),
        (21, "Faith on the Power Pole", "Orville Yates"),
        (24, "Voice for Everyone", "Albert G. Pool"),
    ],
    (1984, "09"): [
        (2, "The World Convention and Its Vision", "Equipe editorial"),
        (3, "One of Us Was Flying Upside Down", "Robert Snyder"),
        (9, "Is Life a Gamble?", "John D'Amico"),
        (14, "When Thoughts Turn to Christmas", "Equipe editorial"),
        (17, "Three Years of Ministry", "Equipe editorial"),
    ],
    (1984, "10"): [
        (2, "When Everything Started Going Wrong", "Ed McGlasson"),
        (6, "When Thoughts Turn to Christmas", "Equipe editorial"),
        (7, "Too Big to Be Put Out of Business", "Dennis Marshall"),
        (13, "Was the Meeting a Failure?", "Ron Hurst"),
        (17, "The Coffee Miracle", "Equipe editorial"),
    ],
    (1984, "11"): [
        (2, "From Death Came Life", "Otis Wilson"),
        (7, "Ministry in Yugoslavia", "Equipe editorial"),
        (11, "I Want to Grow Up Like My Dad", "Paul Gatewood"),
        (17, "Command Under Fire", "Equipe editorial"),
        (19, "Lift Jesus Up in the Down Under", "Equipe editorial"),
    ],
}

ENGINE.ARTICLE_OVERRIDES.update(OVERRIDES)


def update_index(summaries: list[dict], targets: list[Path], rebuild: bool) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-MAI1982-NOV1984-INICIO -->"
    end = "<!-- LOTE-MAI1982-NOV1984-FIM -->"
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
        anchor = "<!-- LOTE-JAN1977-FEV1982-FIM -->"
        if anchor not in content:
            raise RuntimeError("Bloco cronológico anterior não encontrado")
        content = content.replace(anchor, anchor + "\n" + block, 1)

    heading = "## Mapa temático do lote maio de 1982–novembro de 1984"
    map_block = f"""## Mapa temático do lote maio de 1982–novembro de 1984

| Assunto | Edições e veios promissores |
|---|---|
| Fé, profissão e liderança | Todo o lote — empresários, governantes, médicos, militares e profissionais |
| Expansão internacional | 1982–1984 — Ásia, África, Europa, Oceania e América Latina |
| Comunicação e testemunho | Todo o lote — VOICE, convenções, televisão e relatos públicos |
| Família, perdão e reconciliação | 1982–1984 — casamento, paternidade, gerações e restauração |
| Ciência, esporte e aviação | 1983–1984 — astronauta, aviação militar, Olimpíadas e esporte profissional |
| Conversão e recuperação | Todo o lote — prisão, álcool, crime, trauma e mudança de vida |
| Oração e curas alegadas | Presente em várias edições — exigir cautela clínica e confirmação externa |

| Decisão potencial | Aplicação no lote |
|---|---|
| Integrar fé e profissão | Governo, empresas, saúde, esporte e Forças Armadas |
| Apoiar reconciliação e recuperação | Família, dependência, prisão e trauma |
| Fortalecer redes internacionais | Capítulos, convenções e missões |
| Usar comunicação com responsabilidade | Revista, televisão e testemunho público |
| Submeter alegações à verificação | Relatos médicos, números institucionais e fatos históricos |

"""
    previous = "## Mapa temático do lote janeiro de 1977–fevereiro de 1982"
    if heading not in content:
        if previous not in content:
            raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
        content = content.replace(previous, map_block + previous, 1)
    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote maio/1982–novembro/1984")


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
            "| Editor | Thomas R. Nickel |", "| Editor | Nelson B. Melvin |", 1
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
