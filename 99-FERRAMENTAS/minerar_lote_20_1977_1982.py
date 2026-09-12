#!/usr/bin/env python3
"""Mineração preliminar e retomável de 20 edições (jan/1977–fev/1982)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "99-FERRAMENTAS" / "minerar_lote_20_1954_1958.py"
SPEC = importlib.util.spec_from_file_location("fgmbv_mining_engine_1977_1982", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Não foi possível carregar {ENGINE_PATH}")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
Config = ENGINE.Config


BATCH = [
    Config(1977, "01", "Janeiro de 1977", 25, 1, "Voice-1977-01.pdf"),
    Config(1977, "02", "Fevereiro de 1977", 25, 2, "Voice-1977-02.pdf"),
    Config(1977, "03", "Março de 1977", 25, 3, "Voice-1977-03.pdf"),
    Config(1977, "04", "Abril de 1977", 25, 4, "Voice-1977-04.pdf"),
    Config(1977, "12", "Dezembro de 1977", 25, 11, "Voice-1977-12.pdf"),
    Config(1978, "01", "Janeiro de 1978", 26, 1, "Voice-1978-01.pdf"),
    Config(1978, "03", "Março de 1978", 26, 3, "Voice-1978-03.pdf"),
    Config(1978, "06", "Junho de 1978", 26, 6, "Voice-1978-06.pdf"),
    Config(1980, "03", "Março de 1980", 28, 3, "Voice-1980-03.pdf"),
    Config(1980, "04", "Abril de 1980", 28, 4, "Voice-1980-04.pdf"),
    Config(1980, "05", "Maio de 1980", 28, 5, "Voice-1980-05.pdf"),
    Config(1980, "06", "Junho de 1980", 28, 6, "Voice-1980-06.pdf"),
    Config(1981, "03", "Março de 1981", 29, 3, "Voice-1981-03.pdf"),
    Config(1981, "04", "Abril de 1981", 29, 4, "Voice-1981-04.pdf"),
    Config(1981, "05", "Maio de 1981", 29, 5, "Voice-1981-05.pdf"),
    Config(1981, "06", "Junho de 1981", 29, 6, "Voice-1981-06.pdf"),
    Config(1981, "10", "Outubro de 1981", 29, 9, "Voice-1981-10.pdf"),
    Config(1981, "11", "Novembro de 1981", 29, 10, "Voice-1981-11.pdf"),
    Config(1981, "12", "Dezembro de 1981", 29, 11, "Voice-1981-12.pdf"),
    Config(1982, "02", "Fevereiro de 1982", 30, 2, "Voice-1982-02.pdf"),
]


OVERRIDES = {
    (1977, "01"): [
        (2, "Reborn", "Joe Pinto"),
        (4, "The Tongue of the Learned", "Ray Bullard"),
        (9, "Cease Fire!", "J. Ray Gschwend"),
        (17, "God Is Never Static", "Demos Shakarian"),
        (18, "God's Coffee Cabinet", "Willard R. Fox Jr."),
        (22, "Christian?", "Rex F. Masters"),
        (32, "The Cable of His Love", "Jakob Wyssen"),
    ],
    (1977, "02"): [
        (2, "Towering Inferno", "William E. Peters"),
        (6, "The Peak of Perfection", "John Decker"),
        (8, "Power and Light", "A. J. “Dusty” Rhodes"),
        (16, "Light in the Doorway", "Otis G. Jones"),
        (18, "Our Cross Is Bare", "Jack Coleman"),
        (21, "A Pastor Speaks Out", "W. M. Horton"),
    ],
    (1977, "03"): [
        (2, "Revelation", "Jim Rumph"),
        (4, "From Frogtown to Freedom", "James Williams"),
        (8, "Walking Tall", "Jimmy Maynor"),
        (14, "What's Happened to Daddy?", "Dan Wesley Smith"),
        (18, "The Bad News First", "Paul Spitz"),
        (33, "God's Greatest Need", "Demos Shakarian"),
    ],
    (1977, "04"): [
        (2, "Tuned In and Turned On", "David W. Martin"),
        (6, "Flying High", "Dennis H. Wills"),
        (8, "Detour", "Trevor Gunston"),
        (16, "Infiltration", "Victor Munyer"),
        (18, "Rendezvous in the Sky", "Fred Lawrence"),
        (20, "A Beam, a Nail, and Blood", "Demos Shakarian"),
        (32, "Apostles and the Resurrection", "Howard Ervin"),
    ],
    (1977, "12"): [
        (3, "We've Already Had Our Christmas!", "A. B. “Bun” Stubbs"),
        (6, "The Morning After", "Cecil Spruill"),
        (12, "Divine Direction", "James F. Gamble Jr."),
        (13, "Million Dollar Miracle", "Aiko Hormann"),
        (20, "No Generation Gap", "Demos Shakarian"),
        (28, "God's Christmas Message", "Everett Fullam"),
        (31, "Spiritual Phenomena", "Ed Hutka"),
    ],
    (1978, "01"): [
        (2, "Unshackled—Indeed!", "A. J. Vander Meulen"),
        (6, "Fire and Snow", "Max P. Gassman"),
        (14, "A Lesson from Lottie", "Schoel Hammer"),
        (20, "Silver Jubilee", "Demos Shakarian"),
        (25, "God Is Big Enough!", "Ira T. Vincent"),
        (28, "The Shepherd Psalm", "James Hester"),
        (31, "Miracle on 42nd Street", "Robert W. Steinmetz"),
    ],
    (1978, "03"): [
        (3, "The Bottom Line", "Wendell Watkins"),
        (7, "An Open Invitation", "Demos Shakarian"),
        (8, "I Didn't Have To", "Henrik Friis Larsen"),
        (9, "A Deeper Experience", "Bernhard R. Tynes"),
        (15, "How Sweet It Is!", "C. C. Cribb"),
        (20, "A Royal Heir", "Dick Mills"),
        (24, "Can Christians Handle Prosperity?", "Otis G. Jones"),
    ],
    (1978, "06"): [
        (3, "Before the Bar", "Lynwood Maddox"),
        (9, "Why Didn't I Die?", "R. Ben Tandy"),
        (12, "Caramuta", "Jean Leibig"),
        (16, "25th Anniversary Convention", "Herb Daletti"),
        (18, "Happiness Is", "Paul Dennis Newsom"),
        (20, "No Bars on Our Souls", "Albert E. Purviance"),
        (24, "The Heritage of John Foreman", "Equipe editorial"),
    ],
    (1980, "03"): [
        (2, "To Make a Million", "Equipe editorial"),
        (6, "Where There Is Darkness, Light Is Needed", "Equipe editorial"),
        (13, "A Ministry in the Marketplace", "Wayne Shabaz"),
        (17, "The Happiest People on Earth", "Equipe editorial"),
        (20, "A Testimony to All Nations", "Equipe editorial"),
        (26, "Juicy Life", "David Molyneux"),
    ],
    (1980, "04"): [
        (2, "Houston, We've Got a Problem", "Jerry Woodfill"),
        (5, "Prayer Encircled the Earth", "Equipe editorial"),
        (15, "A Special Night of Ministry", "Demos Shakarian"),
        (16, "Love Has No Rank", "Mike Emmett"),
        (18, "A Contemporary Easter Message", "Equipe editorial"),
        (26, "Stranger in My House", "Joseph P. Dallanegra Jr."),
    ],
    (1980, "05"): [
        (2, "World Changers", "Equipe editorial"),
        (4, "Africa Harvest", "Equipe editorial"),
        (7, "Catapulted into Ministry", "Equipe editorial"),
        (10, "Sweden", "Equipe editorial"),
        (20, "Businessmen—Fishers of Men", "Equipe editorial"),
        (27, "Lionel Luckhoo: A Life Transformed", "Lionel Luckhoo"),
    ],
    (1980, "06"): [
        (2, "Two Minutes in a Crippled Jet Fighter", "William R. Cranshaw"),
        (9, "A Different Kind of Race", "Bill Ross"),
        (12, "The Call to Battle", "Equipe editorial"),
        (17, "Drinking Lost Me 23 Jobs", "Jim McDonald"),
        (27, "From Familiar Spirits to Freedom", "Equipe editorial"),
        (26, "A New Life in Christ", "Equipe editorial"),
    ],
    (1981, "03"): [
        (2, "Space Shuttle", "George Metcalf"),
        (8, "Two Men—One Goal", "Equipe editorial"),
        (9, "Wycliffe Bible Translators", "W. Cameron Townsend"),
        (16, "Faith and the Scientific Mind", "Clark T. Bowman"),
        (26, "The Pending Paycheck", "Paul Brenneman"),
    ],
    (1981, "04"): [
        (2, "From Stunts to Faith", "Gene Sullivan"),
        (6, "A Testimony with Humor", "Paul Yarbrough"),
        (12, "Faith on the Ranch", "Harold “Hayseed” Stevens"),
        (16, "Back to Indy", "Equipe editorial"),
        (20, "A Jockey's Covenant", "Equipe editorial"),
    ],
    (1981, "05"): [
        (2, "Time Stopped", "Don Bounds"),
        (7, "Guatemala: Grace in a Trouble Spot", "John Curretta"),
        (12, "From Combat to Christian Service", "Roger L. Helle"),
        (17, "On Course", "Equipe editorial"),
        (24, "A Faith to Broadcast", "Equipe editorial"),
        (27, "Hotel Happening", "Dave Malkin"),
    ],
    (1981, "06"): [
        (2, "Breakthrough", "Larry D. Samuels"),
        (8, "Through the Fire", "Equipe editorial"),
        (12, "Reaping the Harvest", "Equipe editorial"),
        (16, "The Ziglar Testimony", "Zig Ziglar"),
        (22, "Minister in the Marketplace", "Peter Butt"),
        (28, "Philippines Outreach", "Narciso Padilla"),
    ],
    (1981, "10"): [
        (2, "Sleeping, Scraping, Flying Glass", "Equipe editorial"),
        (7, "A Voice at the Truck Stop", "Max Call"),
        (12, "The Impossible Convert", "Equipe editorial"),
        (16, "A Carouser Encounters Grace", "Bunk Busch"),
        (21, "Safety Is of the Lord", "Jim W. Keys"),
        (25, "A Price to Pay", "Paul Christensen"),
    ],
    (1981, "11"): [
        (3, "Prescription for Life", "Equipe editorial"),
        (7, "A Physician's Changed Practice", "Gil Maulsby"),
        (11, "Change", "Curly Brehm"),
        (14, "From Death's Shadows", "Glenn O. Randall"),
        (18, "Time Was Running Out", "Raymond L. Millsaps"),
        (26, "Voice as a Witnessing Tool", "Charles Carney"),
    ],
    (1981, "12"): [
        (3, "White House Santa", "Equipe editorial"),
        (7, "Forgiveness in the Workplace", "Rey Soto"),
        (10, "Christmas and the Language of Love", "Anthony Dibiase"),
        (14, "A Way to Go", "Wayne P. Grimme"),
        (17, "Christmas—A Reminder", "Equipe editorial"),
        (19, "Crisis at Christmas", "Howard Jameson"),
        (23, "Rescue in Yosemite", "Bruce L. Fincham"),
    ],
    (1982, "02"): [
        (3, "The General", "Jerry R. Curry"),
        (7, "No More Excuses", "William T. Morris"),
        (10, "Learning to Accept God's Love", "Ron Jesser"),
        (18, "Freedom", "Ed Hutka"),
        (24, "Running Away—and Back", "Dana Hartong"),
        (28, "Conventions and Fellowship", "Equipe editorial"),
    ],
}

ENGINE.ARTICLE_OVERRIDES.update(OVERRIDES)


def update_index(summaries: list[dict], targets: list[Path], rebuild: bool) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-JAN1977-FEV1982-INICIO -->"
    end = "<!-- LOTE-JAN1977-FEV1982-FIM -->"
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
        anchor = "<!-- LOTE-NOV1970-SET1976-FIM -->"
        if anchor not in content:
            raise RuntimeError("Bloco cronológico anterior não encontrado")
        content = content.replace(anchor, anchor + "\n" + block, 1)

    heading = "## Mapa temático do lote janeiro de 1977–fevereiro de 1982"
    map_block = f"""## Mapa temático do lote janeiro de 1977–fevereiro de 1982

| Assunto | Edições e veios promissores |
|---|---|
| Fé, profissão e negócios | Todo o lote — empresários, médicos, cientistas, militares, transportadores e comunicadores |
| Ciência, aviação e espaço | 1980–1982 — Apollo 13, ônibus espacial, aviação naval e tecnologia |
| Comunicação e testemunho | Todo o lote — VOICE, rádio, televisão, literatura e encontros públicos |
| Expansão internacional | 1977–1982 — Europa, África, América Latina e Ásia |
| Conversão, recuperação e vocação | Todo o lote — dependência química, prisão, trauma e mudança de vida |
| Família e reconciliação | 1977–1982 — casamento, gerações, perdão e restauração de vínculos |
| Oração e curas alegadas | Presente em várias edições — exigir cautela clínica e confirmação externa |

| Decisão potencial | Aplicação no lote |
|---|---|
| Integrar fé e atuação profissional | Ciência, saúde, negócios, mídia, governo e Forças Armadas |
| Usar comunicação com responsabilidade | Revista, rádio, televisão e testemunho público |
| Apoiar recuperação e reconciliação | Dependência, prisão, trauma e conflitos familiares |
| Formar lideranças locais | Capítulos, convenções e ministério no mercado |
| Submeter alegações à verificação | Relatos médicos, números institucionais e fatos históricos |

"""
    previous = "## Mapa temático do lote novembro de 1970–setembro de 1976"
    if heading not in content:
        if previous not in content:
            raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
        content = content.replace(previous, map_block + previous, 1)
    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote janeiro/1977–fevereiro/1982")


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
        editor = "Raymond W. Becker" if config.year <= 1978 else "Nelson B. Melvin"
        markdown = markdown.replace(
            "| Editor | Thomas R. Nickel |", f"| Editor | {editor} |", 1
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
