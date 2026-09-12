#!/usr/bin/env python3
"""Mineração preliminar e retomável de 20 edições (nov/1970–set/1976)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "99-FERRAMENTAS" / "minerar_lote_20_1954_1958.py"
SPEC = importlib.util.spec_from_file_location("fgmbv_mining_engine_1970_1976", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Não foi possível carregar {ENGINE_PATH}")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
Config = ENGINE.Config


BATCH = [
    Config(1970, "11", "Novembro de 1970", 18, 9, "Voice-1970-11.pdf"),
    Config(1971, "04", "Abril de 1971", 19, 3, "Voice-1971-04.pdf"),
    Config(1971, "09", "Setembro de 1971", 19, 7, "Voice-1971-09.pdf"),
    Config(1971, "10", "Outubro de 1971", 19, 8, "Voice-1971-10.pdf"),
    Config(1972, "03", "Março de 1972", 20, 3, "Voice-1972-03.pdf"),
    Config(1972, "06", "Junho de 1972", 20, 6, "Voice-1972-06.pdf"),
    Config(1972, "10", "Outubro de 1972", 20, 9, "Voice-1972-10.pdf"),
    Config(1973, "04", "Abril de 1973", 21, 4, "Voice-1973-04.pdf"),
    Config(1973, "07-08", "Julho–agosto de 1973", 21, 7, "Voice-1973-07-08.pdf"),
    Config(1973, "12", "Dezembro de 1973", 21, 11, "Voice-1973-12.pdf"),
    Config(1974, "02", "Fevereiro de 1974", 22, 2, "Voice-1974-02.pdf"),
    Config(1974, "03", "Março de 1974", 22, 3, "Voice-1974-03.pdf"),
    Config(1975, "01", "Janeiro de 1975", 23, 1, "Voice-1975-01.pdf"),
    Config(1975, "02", "Fevereiro de 1975", 23, 2, "Voice-1975-02.pdf"),
    Config(1975, "03", "Março de 1975", 23, 3, "Voice-1975-03.pdf"),
    Config(1975, "04", "Abril de 1975", 23, 4, "Voice-1975-04.pdf"),
    Config(1975, "07-08", "Julho–agosto de 1975", 23, 7, "Voice-1975-07-08.pdf"),
    Config(1975, "09", "Setembro de 1975", 23, 8, "Voice-1975-09.pdf"),
    Config(1976, "06", "Junho de 1976", 24, 6, "Voice-1976-06.pdf"),
    Config(1976, "09", "Setembro de 1976", 24, 8, "Voice-1976-09.pdf"),
]


OVERRIDES = {
    (1970, "11"): [
        (2, "Washington's Thanksgiving Proclamation", "George Washington"),
        (4, "The Voice of Thanksgiving", "Art Nersasian"),
        (8, "Making the Scene", "David Rothschild"),
        (11, "Out of Darkness", "Hal Glover"),
        (14, "What Did We Have?", "Karl Bujok"),
        (19, "Blacklist!", "Equipe editorial"),
        (23, "Possessed!", "Equipe editorial"),
        (29, "God's Hotline", "Equipe editorial"),
    ],
    (1971, "04"): [
        (3, "Easter: Door of Hope", "Demos Shakarian"),
        (4, "The Scandinavian Story", "Raymond W. Becker"),
        (12, "The Story of U WIN", "Winto Roy"),
        (15, "God Gave Us a Miracle!", "Irv Kessler"),
        (18, "Life's Only Necessity", "Equipe editorial"),
        (36, "The Reason Why", "Equipe editorial"),
    ],
    (1971, "09"): [
        (3, "Gentle Revolution", "James J. Cavnar"),
        (9, "Seek Me!", "James Byrne"),
        (15, "Power and Perfection", "Don Schmit"),
        (18, "A Letter to God", "Joseph M. O'Meara"),
        (28, "Contrasting Conventions", "Edward D. O'Connor"),
        (31, "A Fire Is Lighted", "Equipe editorial"),
        (43, "Bearers of His Peace", "Equipe editorial"),
    ],
    (1971, "10"): [
        (3, "Not by Bread Alone", "Art Forrester"),
        (8, "The Oil of Joy", "William J. Samarin"),
        (13, "What's in a Word?", "Ruth Burke Hill"),
        (15, "From Jazz to Jesus", "Jeanne e Ralph Leibig"),
        (19, "Spiritual Safari", "Equipe editorial"),
        (35, "Outasight!", "Equipe editorial"),
    ],
    (1972, "03"): [
        (3, "High Adventure", "Douglas Roberts"),
        (8, "Prescription for Prosperity", "Equipe editorial"),
        (13, "Aglow with the Spirit", "Equipe editorial"),
        (16, "Unity in the Holy Spirit", "John J. Hinkle"),
        (20, "Bettering Our Best", "Equipe editorial"),
        (32, "FGBMFI-TV Good News", "Equipe editorial"),
    ],
    (1972, "06"): [
        (3, "A New Dimension", "Warren Black"),
        (8, "Contact!", "Willie Bell"),
        (12, "Personal Pentecost", "Gilbert L. Dilley"),
        (16, "Free Spirit", "E. F. Drum"),
        (20, "Without Fear", "Gus Rydell"),
        (22, "The Heart of Things", "Adrian Sivinski"),
        (36, "I Will—or Will I?", "Max E. Campbell"),
    ],
    (1972, "10"): [
        (2, "New York Times Report", "Equipe editorial"),
        (4, "Wings of the Wind", "Raymond W. Becker"),
        (15, "Land of No Memory", "Carl Mandal Hansen"),
        (27, "A Life Loved Back", "John Foreman"),
        (34, "$70,000 for Soul Winning", "Equipe editorial"),
        (39, "Adventure into Faith", "Equipe editorial"),
    ],
    (1973, "04"): [
        (2, "Lazarus, Come Forth!", "Ray Charles Jarman"),
        (8, "Laugh, Clown, Laugh", "Jim “Rusty Nails” Allen"),
        (13, "Supernaturally Natural", "Humphrey Whistler"),
        (16, "Pollution", "Russell J. Fornwalt"),
        (18, "A Pardoned Parolee", "Equipe editorial"),
        (20, "Closing Time, Gentlemen", "Demos Shakarian"),
        (32, "Such Wondrous Love!", "Raymond A. Neill"),
    ],
    (1973, "07-08"): [
        (2, "A Marine's Hymn", "Speed Wilson"),
        (8, "Geronimo!", "Robert Crick"),
        (12, "Retreat to Advance", "Demos Shakarian"),
        (16, "Alaskan Adventure", "Duane Olson"),
        (18, "A Lesson I'll Never Forget", "James E. Johnson"),
        (22, "Anchors Aweigh!", "Bill Ward"),
        (28, "God in Government", "Bob Jones"),
        (32, "Telephone to Glory", "John H. Garraghan"),
    ],
    (1973, "12"): [
        (2, "Home for Christmas", "Equipe editorial"),
        (4, "Winter Wonderland", "Glenn O. Randall"),
        (8, "The Gift", "Roland Capps"),
        (14, "Out of the Shadows", "Henry W. Baxter Jr."),
        (20, "Christmas, Plus", "Joseph Bohanon"),
        (22, "Operation 1207", "Equipe editorial"),
        (36, "Release!", "Equipe editorial"),
    ],
    (1974, "02"): [
        (2, "The Word and the Spirit", "Equipe editorial"),
        (4, "The Great Physician", "Lloyd W. Huneryager"),
        (8, "Hand on My Shoulder", "Demos Shakarian"),
        (14, "Prayer for a Wayward Nation", "Fred Kehoe"),
        (16, "Goal to Go!", "Russ Bixler"),
        (20, "It Can Happen to Anybody!", "David Clark"),
        (35, "From Death unto Life", "Equipe editorial"),
    ],
    (1974, "03"): [
        (2, "Prosperity Is a Product", "Angelo C. Ferri"),
        (8, "The Big Time", "Equipe editorial"),
        (14, "Chain Reaction", "Equipe editorial"),
        (17, "Up a Tree", "John Nordman"),
        (28, "Jesus Gets Top Billing", "William R. Wineke"),
        (32, "In Touch with God", "Equipe editorial"),
    ],
    (1975, "01"): [
        (2, "Challenged!", "Elmer Lewis"),
        (9, "Wright Was Wrong", "Tom Wright"),
        (15, "God Sent a Lawyer", "Bill Allen"),
        (20, "The Now of the Harvest", "Demos Shakarian"),
        (22, "Observation Sundays", "James Clayton Pippin"),
        (28, "The Why of Tongues", "J. Robert Ashcroft"),
        (31, "Who Could Ask for More?", "Equipe editorial"),
    ],
    (1975, "02"): [
        (2, "God's Ballroom Saints", "Equipe editorial"),
        (8, "Delivered from Demons", "Sherwin B. McCurdy"),
        (15, "On the Trail of Truth", "Archie C. Fries Jr."),
        (20, "The Eight Memorable Days", "Demos Shakarian"),
        (22, "Neutral or Natural?", "Roy Howes"),
        (34, "Chapters and Conventions", "Equipe editorial"),
    ],
    (1975, "03"): [
        (2, "The Open Window", "Fred Ladenius"),
        (7, "The Influence of a Testimony", "Jerry L. Duncan"),
        (9, "My Senior Partner", "Demos Shakarian"),
        (16, "Springtime in Italy", "Richard Arndt"),
        (30, "We Came to Share Jesus", "Sebastiano Paparo"),
        (31, "You Are Dedicated", "Jerry R. Curry"),
        (35, "Rebuilding the Walls", "Equipe editorial"),
    ],
    (1975, "04"): [
        (2, "The Lift of Love", "Norman Norwood"),
        (10, "Reaper of Souls", "Jim Madden"),
        (13, "The Third Time Around", "George Whitten"),
        (17, "We Prayed for a Miracle", "Roy Hitchcock"),
        (22, "Windows of Heaven", "Demos Shakarian"),
        (24, "A Prisoner's Prayer", "J. Robert Ashcroft"),
        (33, "What About Prophetic Utterances?", "Equipe editorial"),
    ],
    (1975, "07-08"): [
        (2, "Broad Stripes and Bright Stars", "Equipe editorial"),
        (7, "The Lord's Ecumenism", "John Patrick Bertolucci"),
        (14, "Putting It All Together", "James Ammerman"),
        (16, "Proper Priorities", "Demos Shakarian"),
        (20, "For Such a Time as This", "Norbert Selking"),
        (28, "The Stranger", "Rudolph R. Hahn"),
        (32, "Two Weeks in Eternity", "Equipe editorial"),
    ],
    (1975, "09"): [
        (2, "Certified", "Equipe editorial"),
        (8, "A Walking Miracle", "Gene E. Evans"),
        (12, "The Cows Accepted It!", "Marcus Nissley"),
        (16, "Wings of Protection", "Demos Shakarian"),
        (21, "The Arena of Faith", "Frank Foglio"),
        (22, "Dear Angelo", "Equipe editorial"),
        (27, "Blessed Are the Obedient", "Frederick K. Price"),
    ],
    (1976, "06"): [
        (2, "Timber-r-r!", "Jerry Lausmann"),
        (8, "When Jesus Ran the Mill", "Fred Brown"),
        (15, "Stand, Don't Waver!", "Kathy Leese"),
        (17, "The Full Gospel", "William Brafford"),
        (20, "His Ability Through Me", "John Conlan"),
        (22, "Our Obligation: Occupy", "Equipe editorial"),
        (35, "Something Special", "Equipe editorial"),
    ],
    (1976, "09"): [
        (2, "Signs and Wonders", "Richard C. Minasian"),
        (9, "My Greatest Reward", "Demos Shakarian"),
        (12, "Restoration", "Claude A. Frazier"),
        (16, "Voice and Good News", "Equipe editorial"),
        (17, "Brussels Convention", "Fred Ladenius"),
        (20, "The Language of Love", "Equipe editorial"),
        (22, "Credits God with Healing", "Equipe editorial"),
        (24, "From Trauma to Triumph", "Equipe editorial"),
    ],
}

ENGINE.ARTICLE_OVERRIDES.update(OVERRIDES)


def update_index(summaries: list[dict], targets: list[Path], rebuild: bool) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-NOV1970-SET1976-INICIO -->"
    end = "<!-- LOTE-NOV1970-SET1976-FIM -->"
    if start in content and not rebuild:
        print("ÍNDICE PRESERVADO: bloco do lote já existe")
        return

    rows = []
    for summary, target in zip(summaries, targets):
        people = "; ".join(summary["authors"][:5])
        topics = "; ".join(summary["topics"][:5])
        decisions = "; ".join(summary["decisions"][:4])
        link = f"../02-MINERACAO/{target.parent.name}/{target.name}"
        rows.append(
            f"| {summary['date']} | {summary['edition']} | {summary['pages']} | "
            f"≥ {len(summary['authors'])} | {people} | {topics} | {decisions} | "
            f"[Ficha]({link}) |"
        )
    block = start + "\n" + "\n".join(rows) + "\n" + end
    if start in content:
        content = re.sub(
            re.escape(start) + r".*?" + re.escape(end),
            block,
            content,
            count=1,
            flags=re.DOTALL,
        )
    else:
        anchor = "<!-- LOTE-JAN1961-SET1967-FIM -->"
        if anchor not in content:
            raise RuntimeError("Bloco cronológico anterior não encontrado")
        content = content.replace(anchor, anchor + "\n" + block, 1)

    map_heading = "## Mapa temático do lote novembro de 1970–setembro de 1976"
    map_block = f"""## Mapa temático do lote novembro de 1970–setembro de 1976

| Assunto | Edições e veios promissores |
|---|---|
| Renovação carismática e ecumenismo | 1971–1976 — católicos, protestantes históricos, pentecostais e testemunhos de unidade |
| Fé, profissão e negócios | Todo o lote — empresários, profissionais liberais, militares, governo e administração |
| Comunicação e mídia | 1971–1976 — VOICE, televisão GOOD NEWS, gravações e circulação internacional |
| Vida pública e serviço militar | 1970–1975 — governo, Forças Armadas, Vietnã e testemunho público |
| Expansão internacional | Todo o lote — Escandinávia, Europa, Oriente Médio e redes mundiais da FGBMFI |
| Conversão e vocação | Todo o lote — mudança de vida, discipulado, testemunho e serviço |
| Oração e curas alegadas | Presente em várias edições — exigir linguagem clínica cautelosa e confirmação externa |
| Formação de lideranças | 1972–1976 — capítulos, convenções, prioridades e responsabilidade institucional |

| Decisão potencial | Aplicação no lote |
|---|---|
| Integrar fé e atuação profissional | Negócios, governo, ciência, mídia e Forças Armadas |
| Cooperar entre tradições cristãs | Renovação carismática e encontros ecumênicos |
| Usar comunicação com responsabilidade | Revista, televisão, áudio e testemunho público |
| Formar e fortalecer lideranças locais | Capítulos, convenções e redes internacionais |
| Servir pessoas em crise | Guerra, prisão, doença, trauma e dificuldades familiares |
| Submeter alegações à verificação | Relatos médicos, números institucionais e acontecimentos históricos |

"""
    previous_heading = "## Mapa temático do lote janeiro de 1961–setembro de 1967"
    if map_heading not in content:
        if previous_heading not in content:
            raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
        content = content.replace(previous_heading, map_block + previous_heading, 1)

    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote novembro/1970–setembro/1976")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reconstruir",
        action="store_true",
        help="Reconstrói apenas as 20 fichas pertencentes a este lote.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    created = 0
    summaries = []
    targets = []
    for config in BATCH:
        pdf = ROOT / "01-EDICOES-PDF" / str(config.year) / config.pdf_name
        text_path = ROOT / "02-MINERACAO" / str(config.year) / (
            f"{Path(config.pdf_name).stem}.txt"
        )
        target = ROOT / "02-MINERACAO" / str(config.year) / (
            f"FGMBV-{config.year}-{config.month}-v{config.volume}-n{config.number}.md"
        )
        if not pdf.exists() or not text_path.exists():
            raise FileNotFoundError(f"Fonte ausente: {pdf} ou {text_path}")
        markdown, summary = ENGINE.render(
            config,
            pdf,
            text_path,
            text_path.read_text(encoding="utf-8", errors="replace"),
        )
        markdown = markdown.replace(
            "| Editor | Thomas R. Nickel |", "| Editor | Raymond W. Becker |", 1
        )
        existed = target.exists()
        if existed and not args.reconstruir:
            print(f"PRESERVADA: {target.relative_to(ROOT)}")
        else:
            temporary = target.with_suffix(".md.part")
            temporary.write_text(markdown, encoding="utf-8")
            temporary.replace(target)
            print(
                f"{'RECONSTRUÍDA' if existed else 'CRIADA'}: "
                f"{target.relative_to(ROOT)}"
            )
            created += not existed
        summaries.append(summary)
        targets.append(target)
    update_index(summaries, targets, rebuild=args.reconstruir)
    print(f"Novas fichas: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
