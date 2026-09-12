#!/usr/bin/env python3
"""Mineração preliminar e retomável de 20 edições (jan/1961–set/1967)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "99-FERRAMENTAS" / "minerar_lote_20_1954_1958.py"
SPEC = importlib.util.spec_from_file_location("fgmbv_mining_engine_1961_1967", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Não foi possível carregar {ENGINE_PATH}")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
Config = ENGINE.Config


BATCH = [
    Config(1961, "01", "Janeiro de 1961", 8, 12, "Voice - FGBMFI - 8.12 (January 1961),.pdf"),
    Config(1961, "02", "Fevereiro de 1961", 9, 1, "Voice - FGBMFI - 9.1 (February 1961).pdf"),
    Config(1961, "03", "Março de 1961", 9, 2, "Voice - FGBMFI - 9.2 (March 1961).pdf"),
    Config(1961, "04", "Abril de 1961", 9, 3, "Voice - FGBMFI - 9.3 (April 1961),.pdf"),
    Config(1961, "05", "Maio de 1961", 9, 4, "Voice - FGBMFI - 9.4 (May 1961).pdf"),
    Config(1961, "07-08", "Julho–agosto de 1961", 9, "6-7", "Voice-1961-07.pdf"),
    Config(1961, "09", "Setembro de 1961", 9, 8, "Voice-1961-09.pdf"),
    Config(1962, "11", "Novembro de 1962", 10, 11, "Voice-1962-11.pdf"),
    Config(1963, "01", "Janeiro de 1963", 11, 12, "Voice-1963-01.pdf"),
    Config(1963, "02", "Fevereiro de 1963", 11, 1, "Voice-1963-02.pdf"),
    Config(1963, "04", "Abril de 1963", 11, 3, "Voice-1963-04.pdf"),
    Config(1964, "12", "Dezembro de 1964", 12, 11, "Voice-1964-12.pdf"),
    Config(1965, "01", "Janeiro de 1965", 12, 12, "Voice-1965-01.pdf"),
    Config(1965, "05", "Maio de 1965", 13, 4, "Voice-1965-05.pdf"),
    Config(1965, "10", "Outubro de 1965", 13, 9, "Voice-1965-10.pdf"),
    Config(1966, "05", "Maio de 1966", 14, 4, "Voice-1966-05.pdf"),
    Config(1967, "03", "Março de 1967", 15, 2, "Voice-1967-03.pdf"),
    Config(1967, "04", "Abril de 1967", 15, 3, "Voice-1967-04.pdf"),
    Config(1967, "06", "Junho de 1967", 15, 6, "Voice-1967-06.pdf"),
    Config(1967, "09", "Setembro de 1967", 15, 8, "Voice-1967-09.pdf"),
]


OVERRIDES = {
    (1961, "01"): [
        (2, "In the Beginning God Created", "Ulric Jelinek"),
        (6, "And the Last Shall Be First!", "Thomas R. Nickel"),
        (9, "When Episcopalians Start Speaking in Tongues", "Dennis J. Bennett"),
        (15, "Win Eternity-Bound Men to the Saviour", "D. N. Buntain"),
        (18, "Have You Seen Jesus?", "Charles S. Price"),
        (22, "Visitation of God to the Mennonites", "Gerald Derstine"),
        (26, "Converted, but Lost", "Clifford Ford"),
        (28, "What Christ Means to a Teen-Ager", "Cheryl McSpadden"),
    ],
    (1961, "02"): [
        (3, "Beyond the Curtain of Time!", "William Branham"),
        (6, "God Plans to Move Four Times Faster!", "Thomas R. Nickel"),
        (7, "Report of Atlantic City Regional Convention", "Joseph Priore"),
        (12, "President Kennedy Takes Oath on Catholic Bible", "Jules Loh"),
        (13, "Awake Thou That Sleepest, Arise from the Dead!", "C. Calvin Herriott"),
        (16, "A Lot of Faith: A Lot of Cows", "Ed Ainsworth"),
        (20, "Latin America Has Become a Vast Religion Vacuum", "United Press International"),
        (24, "What Has Happened to the Trinity?", "Jean Stone"),
        (27, "He That Dwelleth in Love Dwelleth in God", "Charles S. Price"),
    ],
    (1961, "03"): [
        (3, "God Spoke to Me in French!", "John P. Wildrianne"),
        (9, "I Spent a Glorious Week-End with Jesus!", "Lowell Sisson"),
        (16, "God Undertakes Healing for a Curved Spine", "Robert D. Conkling"),
        (17, "Run Through the Land with an Inkhorn!", "LaRue Oberlander"),
        (25, "God Spoke to Nigerian Princess Through a Tom-Tom", "Fred Squire"),
        (27, "Come Over to Macedonia and Help Us!", "Isaac B. Akinyele"),
    ],
    (1961, "04"): [
        (2, "Jesus Was Filled with the Spirit, Without Measure!", "Keith Ruegsegger"),
        (6, "The Day of the Lord Is Upon Us Now!", "Gerald Derstine"),
        (9, "A Great Convention in the Nation's Capital", "Thomas R. Nickel"),
        (24, "Pentecost Is Not a Denomination: It Is an Experience", "John H. Osteen"),
        (30, "Be Baptized with the Holy Spirit!", "Billy Graham"),
    ],
    (1961, "05"): [
        (3, "The Lord Who Healeth All Thy Diseases!", "Harald Bredesen"),
        (12, "Speaking in Tongues Awes Dutch Reformed Church", "Ruth Weber"),
        (14, "He Specializes in Doing the Impossible", "Harry A. Reed"),
        (16, "I Also Am an Ambassador for the King of Kings!", "Adolf “Bob” Guggenbuhl"),
        (28, "Pentecost: The Forgotten Festival", "John Garrett"),
        (30, "God Created Mothers as the Teachers of Children", "U. L. Hudlow"),
    ],
    (1961, "07-08"): [
        (2, "God Moved Mightily in European Convention!", "Equipe editorial"),
        (14, "God Performed a Miracle Behind the Iron Curtain!", "Samuel Doctorian"),
        (17, "God Spoke Greek Through My Armenian Mother", "Mike Terzian"),
        (20, "Jesus Healed a Crippled Hebrew in Jerusalem!", "Thomas R. Nickel"),
        (25, "Every Christian Must Become a Pentecostal!", "James H. Brown"),
        (30, "Modesto-Turlock Stirred by Regional Convention!", "Robert Langley"),
    ],
    (1961, "09"): [
        (2, "Jesus Christ Will Overcome Communism!", "Walter Judd"),
        (8, "The Holy Spirit Poured Out Among the Children", "Terry Byars"),
        (11, "I Saw Jesus Manifest in Youth!", "Cheryl McSpadden"),
        (14, "The Power of God Fell in the Ladies' Meeting!", "Maxine Sorelle"),
        (17, "We Know That Indeed This Is the Christ!", "Doyle F. Holsing"),
        (28, "They That Do Business in Great Waters!", "A. C. Sorelle Jr."),
        (30, "Let Christ Bear Our Every Burden", "Lloyd Hamill"),
        (31, "World Pentecostal Conference Held in Israel", "Donald Gee"),
    ],
    (1962, "11"): [
        (2, "God Moves at Denver Meeting", "Hugh E. Graham"),
        (7, "God Has a Plan for His People", "Kash Amburgy"),
        (9, "There Is Power in the Old-Fashioned Gospel", "Equipe editorial"),
        (11, "How the Holy Spirit Transforms Lives", "Equipe editorial"),
        (14, "Testimony of Ted Whitesell", "Ted Whitesell"),
        (20, "From Your President", "Demos Shakarian"),
    ],
    (1963, "01"): [
        (2, "Frank Foglio: A Testimony of Healing and Restoration", "Frank Foglio"),
        (10, "We Knew Frank Was Healed", "Equipe editorial"),
        (13, "A Testimony from Carl Williams", "Carl Williams"),
        (16, "Plans Being Completed for Big Phoenix Meeting", "Equipe editorial"),
        (20, "Timely Testimonies", "Equipe editorial"),
        (28, "Legal Investigation of Frank's Healing", "Paul Henry"),
    ],
    (1963, "02"): [
        (3, "Can Man Conquer Space?", "Rodney W. Johnson"),
        (7, "George Otis II: Southern California Missile Manufacturer", "George Otis II"),
        (10, "It Must Start Now!", "William Sherwood"),
        (18, "Timely Testimonies", "Wayne McClain"),
        (22, "Why Go to Church", "Julian Lane"),
        (25, "For This Hour", "Bennie Triplett"),
    ],
    (1963, "04"): [
        (2, "God's Plowman", "Henry Krause"),
        (6, "Enlarge the Place of Our Habitation", "J. V. Madden"),
        (9, "Winning One Thousand Teenagers", "Richard Shakarian"),
        (11, "A New Dimension Has Been Added to My Life", "Ray Bringham"),
        (21, "Pastors Tell of Speaking in Tongues", "Willmar Thorkelson"),
        (22, "I Found the Dynamic I Needed", "John L. Peters"),
        (25, "Full Gospel Business Men's Supper—London", "Selwyn Hughes"),
    ],
    (1964, "12"): [
        (2, "Christmas Message", "Demos e Rose Shakarian"),
        (3, "The Price of the Gift", "Don Huckeba"),
        (8, "Room 405", "John Sherrill"),
        (14, "My Business Is God's Business", "Ed Matthews"),
        (16, "New York Convention", "Equipe editorial"),
        (22, "FGBMFI Team Travels", "Jerry Jensen"),
        (24, "Minute Messages", "Equipe editorial"),
    ],
    (1965, "01"): [
        (2, "With the Lord", "Eunice Klassen"),
        (3, "Son of Promise", "Jerry Jensen"),
        (8, "Go Over Jordan", "Edna Shakarian"),
        (13, "His Works Do Follow Him", "Oral Roberts"),
        (17, "Tributes", "Equipe editorial"),
        (24, "A Peculiar History", "Morton T. Kelsey"),
    ],
    (1965, "05"): [
        (3, "Pentecost", "The Bible"),
        (4, "Pentecost in Perspective", "Ralph Mahoney"),
        (8, "Heavenly Love", "Bill Freeman"),
        (12, "A New Dimension in My Life", "Fred G. Walker"),
        (16, "Pentecost in the Philippines", "Simeon J. Lepasana"),
        (25, "Lifeline", "Bill Bowling"),
    ],
    (1965, "10"): [
        (3, "Charisma on Campus", "Dan Malachuk"),
        (4, "Campus Witness", "Vince Eareckson"),
        (8, "The Moving Horizon", "Haynes Fraser"),
        (10, "My Introduction to Life in the Spirit", "Robert V. Finley"),
        (13, "Campus Conflict", "Barbara Tengan"),
        (18, "Life with a Meaning", "Ginger Mulliner"),
        (21, "Campus Misfit", "Penny Morgan"),
        (25, "Campus Ministry", "John Acton Jr."),
    ],
    (1966, "05"): [
        (3, "With One Accord!", "Equipe editorial"),
        (4, "I Was There", "Arthur G. Osterberg"),
        (8, "Doorway into a New Spiritual Life", "Jay Dalton"),
        (16, "FGBMFI Spiritual Airlifts", "Equipe editorial"),
        (23, "Voices for Vietnam", "Equipe editorial"),
        (25, "Steps to the Upper Room", "Leonard Evans"),
    ],
    (1967, "03"): [
        (4, "A Breath of Fresh Air", "Equipe editorial"),
        (6, "A Spiritual Refreshing", "Equipe editorial"),
        (8, "I Met the Creator", "Equipe editorial"),
        (16, "In Memoriam", "Equipe editorial"),
        (18, "His Final Journey", "Equipe editorial"),
        (20, "Take as Directed", "Equipe editorial"),
        (25, "Steps to the Upper Room", "Benjamin Hendrickson"),
        (26, "A Revitalized Episcopalian", "Equipe editorial"),
    ],
    (1967, "04"): [
        (4, "Vietnam: You Were There", "Equipe editorial"),
        (17, "FGBMFI Convention Report", "Equipe editorial"),
        (19, "And Underneath Are the Everlasting Arms", "Equipe editorial"),
        (22, "A Ministry to Servicemen", "Bill Wade"),
        (25, "What About the Other Twelve?", "Equipe editorial"),
    ],
    (1967, "06"): [
        (4, "Search in Space", "Equipe editorial"),
        (5, "The Scientific Spirit", "Aron Abrahamsen"),
        (8, "Launched into Orbit", "Equipe editorial"),
        (13, "Canaveral Captain", "M. D. Brinn"),
        (17, "I'm Going to Miami", "Equipe editorial"),
        (24, "Man on the Moon", "Rodney W. Johnson"),
    ],
    (1967, "09"): [
        (4, "The Eye of the Storm", "Equipe editorial"),
        (6, "What Happened at Bayview?", "Charles Simpson"),
        (8, "Impressions of Miami Convention", "Equipe editorial"),
        (14, "The Priest of Skidrow", "Jerry Schindler"),
        (17, "I Am Beginning to Live", "William D. Shepherd"),
        (25, "The “Long” Road", "Jack Long"),
    ],
}

ENGINE.ARTICLE_OVERRIDES.update(OVERRIDES)


def update_index(summaries: list[dict], targets: list[Path], rebuild: bool) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-JAN1961-SET1967-INICIO -->"
    end = "<!-- LOTE-JAN1961-SET1967-FIM -->"
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
        anchor = "<!-- LOTE-MAI1958-DEZ1960-FIM -->"
        if anchor not in content:
            raise RuntimeError("Bloco cronológico anterior não encontrado")
        content = content.replace(anchor, anchor + "\n" + block, 1)

    map_heading = "## Mapa temático do lote janeiro de 1961–setembro de 1967"
    map_block = f"""## Mapa temático do lote janeiro de 1961–setembro de 1967

| Assunto | Edições e veios promissores |
|---|---|
| Renovação carismática | 1961–1967 — experiências pentecostais em igrejas históricas, universidades e comunidades locais |
| Expansão internacional | 1961–1967 — Europa, Oriente Médio, África, Ásia, Caribe e América Latina |
| Fé, ciência e tecnologia | 1963 e 1967 — espaço, mísseis, ciência e testemunho profissional |
| Juventude e formação | 1961 e out. 1965 — adolescentes, estudantes, campus e continuidade geracional |
| Guerra Fria e vida pública | 1961–1967 — comunismo, presidência, Vietnã, Israel e responsabilidade pública |
| Fé e negócios | Todo o lote — profissão, empresa, liderança, recursos e serviço |
| Conversão e vocação | Todo o lote — testemunhos, chamado, consagração e mudança de vida |
| Oração e curas alegadas | Presente em várias edições — exigir linguagem clínica cautelosa e confirmação externa |

| Decisão potencial | Aplicação no lote |
|---|---|
| Cooperar entre tradições cristãs | Renovação carismática e encontros interdenominacionais |
| Investir na próxima geração | Juventude, campus, educação e mentoria |
| Integrar fé, profissão e conhecimento | Empresários, cientistas, militares e comunicadores |
| Servir em contextos de crise | Vietnã, Guerra Fria, conflitos e sofrimento pessoal |
| Fortalecer redes locais e internacionais | Capítulos, convenções, missões e equipes itinerantes |
| Submeter alegações à verificação | Relatos médicos, números de campanhas, política e ciência |

"""
    previous_heading = "## Mapa temático do lote maio de 1958–dezembro de 1960"
    if map_heading not in content:
        if previous_heading not in content:
            raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
        content = content.replace(previous_heading, map_block + previous_heading, 1)

    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote janeiro/1961–setembro/1967")


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
