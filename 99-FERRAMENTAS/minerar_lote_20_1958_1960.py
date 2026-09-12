#!/usr/bin/env python3
"""Mineração preliminar e retomável de 20 edições (mai/1958–dez/1960)."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = ROOT / "99-FERRAMENTAS" / "minerar_lote_20_1954_1958.py"
SPEC = importlib.util.spec_from_file_location("fgmbv_mining_engine", ENGINE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Não foi possível carregar {ENGINE_PATH}")
ENGINE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ENGINE
SPEC.loader.exec_module(ENGINE)
Config = ENGINE.Config


BATCH = [
    Config(1958, "05", "Maio de 1958", 6, 4, "Voice - FGBMFI - 6.4 (May 1958).pdf"),
    Config(1958, "06", "Junho de 1958", 6, 5, "Voice - FGBMFI - 6.5 (June 1958).pdf"),
    Config(1958, "07", "Julho de 1958", 6, 6, "Voice - FGBMFI - 6.6 (July 1958).pdf"),
    Config(1958, "08", "Agosto de 1958", 6, 7, "Voice - FGBMFI - 6.7 (August 1958).pdf"),
    Config(1958, "09", "Setembro de 1958", 6, 8, "Voice - FGBMFI - 6.8 (September 1958).pdf"),
    Config(1958, "10", "Outubro de 1958", 6, 9, "Voice - FGBMFI - 6.9 (October 1958).pdf"),
    Config(1958, "11", "Novembro de 1958", 6, 10, "Voice - FGBMFI - 6.10 (November 1958).pdf"),
    Config(1959, "02", "Fevereiro de 1959", 7, 1, "Voice - FGBMFI - 7.1 (February 1959).pdf"),
    Config(1959, "03", "Março de 1959", 7, 2, "Voice - FGBMFI - 7.2 (March 1959).pdf"),
    Config(1960, "01", "Janeiro de 1960", 7, 12, "Voice - FGBMFI - 7.12 (January 1960).pdf"),
    Config(1960, "02", "Fevereiro de 1960", 8, 1, "Voice - FGBMFI - 8.1 (February 1960),.pdf"),
    Config(1960, "03", "Março de 1960", 8, 2, "Voice - FGBMFI - 8.2 (March 1960).pdf"),
    Config(1960, "04", "Abril de 1960", 8, 3, "Voice - FGBMFI - 8.3 (April 1960).pdf"),
    Config(1960, "05", "Maio de 1960", 8, 4, "Voice - FGBMFI - 8.4 (May 1960).pdf"),
    Config(1960, "06", "Junho de 1960", 8, 5, "Voice - FGBMFI - 8.5 (June 1960).pdf"),
    Config(1960, "07-08", "Julho–agosto de 1960", 8, 6, "Voice - FGBMFI - 8.6 (July-Aug 1960).pdf"),
    Config(1960, "09", "Setembro de 1960", 8, 8, "Voice - FGBMFI - 8.8 (Sept 1960).pdf"),
    Config(1960, "10", "Outubro de 1960", 8, 9, "Voice-1960-10.pdf"),
    Config(1960, "11", "Novembro de 1960", 8, 10, "Voice-1960-11.pdf"),
    Config(1960, "12", "Dezembro de 1960", 8, 11, "Voice-1960-12.pdf"),
]


OVERRIDES = {
    (1958, "05"): [
        (3, "God Directed the Life of a Moro Boy", "Margaret La Porte"),
        (10, "Hong Kong Chapter Sponsors Valdez Campaign", "Bulson Chang"),
        (12, "Charlotte Chapter Host to Visitors", "Paul Wichelhaus"),
        (14, "The Day of Judgment Is Drawing Near", "Billy Graham"),
        (22, "He Preaches Christ from Pulpit to Parliament", "E. N. O. Kulbeck"),
        (24, "He Prayed Earnestly for Himself", "T. L. Osborn"),
        (26, "FGBMFI Chapter Formed in Stuttgart, Germany", "Adolph “Bob” Guggenbuhl"),
    ],
    (1958, "06"): [
        (3, "Hong Kong Chapter Sponsors Culpepper Campaign", "Bulson Chang"),
        (11, "Montana Chapter Established at Great Falls", "Irvine J. Harrison"),
        (17, "Is Your Soul Ready for Eternity?", "Earl P. Paulk"),
        (26, "Confirmed by Science", "Thomas R. Nickel"),
        (31, "The Price of the Life of a Man", "Irvine J. Harrison"),
    ],
    (1958, "07"): [
        (3, "Pierce Brooks Is God's Partner Now", "Thomas R. Nickel"),
        (9, "With Perplexity", "Arthur H. Collins"),
        (14, "The Mystery of God's Will", "Billy Graham"),
        (19, "Many Are the Afflictions of the Righteous", "Lily Osmer"),
        (22, "How to Help Another Person", "Norman Vincent Peale"),
        (29, "God Set Ruben Flores Free!", "Thomas R. Nickel"),
    ],
    (1958, "08"): [
        (8, "The Faith of a Child", "Geneva Showerman"),
        (9, "World Conference of Pentecostal Churches", "E. N. O. Kulbeck"),
        (11, "Lifting Up Christ's Cross at the Crossroads of Life", "E. M. Jones"),
        (22, "The Cradle of Civilization Being Rocked!", "Arthur H. Collins"),
        (28, "Prayer in the Name of Jesus", "E. W. Kenyon"),
    ],
    (1958, "09"): [
        (3, "New Chapter Organized at Bristol, Pennsylvania", "Angelo Ferri"),
        (9, "The Young People Were Blessed at the Convention", "Richard Shakarian"),
        (13, "God Set Ruben Flores Free!", "Thomas R. Nickel"),
        (15, "Report of Visit to European Chapters", "Irvine J. Harrison"),
    ],
    (1958, "10"): [
        (3, "FGBMFI Doing Great Work Among the Indians", "Tony Pearson"),
        (5, "New England Stirred by Month-Long Campaign", "Lloyd L. Sweet"),
        (8, "The Word of God: Statements of Facts", "Roger Arnebergh"),
        (21, "An Explosion Is Coming in the Middle East", "Irvine J. Harrison"),
        (25, "The Blessing of the Lord Maketh Rich", "Miner Arganbright"),
        (28, "God Set Ruben Flores Free!", "Thomas R. Nickel"),
    ],
    (1958, "11"): [
        (3, "I Saw the Singapore Chapter Born", "Watson T. Moore"),
        (4, "Singapore Chapter Observes First Anniversary", "Men Seng Lore"),
        (21, "His Name Is God", "A. H. Schliebe"),
        (22, "Fifth World Council of Pentecostal Churches", "Irvine J. Harrison"),
        (24, "He Rose Again!", "R. A. Torrey"),
    ],
    (1959, "02"): [
        (3, "This Is Our Sabbatical Year!", "Thomas R. Nickel"),
        (18, "The Ministry of Tracts", "Tom M. Olson"),
        (20, "God Set Ruben Flores Free!", "Thomas R. Nickel"),
    ],
    (1959, "03"): [
        (3, "The Jamaica Convention of the FGBMFI", "Hugh R. Spence"),
        (11, "The Puerto Rico Convention of the FGBMFI", "J. F. Rodriguez"),
        (19, "New FGBMFI Chapter Established in Havana, Cuba", "Equipe editorial"),
        (22, "My Disturbed and Empty Soul Found God!", "Jack C. Waldron"),
        (24, "May Easter Find Your Stone Rolled Away!", "Irvine J. Harrison"),
    ],
    (1960, "01"): [
        (2, "The Spanish Edition of the Voice Dedicated to God", "Equipe editorial"),
        (4, "I Am What I Am by the Grace of God!", "Equipe editorial"),
        (8, "Great Impact Made by Florida Convention", "Thomas R. Nickel"),
        (15, "Could I Be Tortured to Death for Christ?", "Herbert Fuller"),
        (17, "I Visited President Duvalier of Haiti", "H. J. Smith"),
        (19, "Jesus Is the All-Sufficient Provider!", "Arthur Hooper"),
        (23, "Seek Ye First the Kingdom of God!", "Eulalie Bertha Hogan"),
    ],
    (1960, "02"): [
        (2, "Evangelistic Campaign in Colombia", "Wally Nickel"),
        (6, "Voice Beginning Eighth Year of Service", "Thomas R. Nickel"),
        (8, "The Urgent Need for Christians with a Zealous Faith", "Equipe editorial"),
        (10, "My Most Terrific Pentecostal Meeting", "Fred Squire"),
        (15, "Israel Will Soon Know Who the Lord Is", "Equipe editorial"),
    ],
    (1960, "03"): [
        (2, "God's Great Gift of Life on the Earth", "Wernher von Braun"),
        (4, "He Mixes His Religion with His Business", "Thomas R. Nickel"),
        (11, "Regional Convention and West Indies Campaign", "Demos Shakarian"),
        (15, "Miami Chapter Charter Night", "E. M. Jones"),
        (18, "Report of the Caribbean Crusade", "Irvine J. Harrison"),
    ],
    (1960, "04"): [
        (3, "Concerning the Condition of Our Fellowship", "Jewel W. Rose"),
        (4, "God Daily Loads the Bonhams with Benefits!", "Thomas R. Nickel"),
        (10, "What Easter Means to Me", "Violet M. Tate"),
        (12, "Report of Regional Convention in Puerto Rico", "Victor P. Colon"),
        (17, "There Are Millions of Silent Missionaries at Work", "Willard H. Pope"),
        (21, "Faith Is an Absolute Conviction of Truth!", "Howard A. Kelly"),
    ],
    (1960, "05"): [
        (3, "How God Prepared Haiti for the FGBMFI", "Thomas R. Nickel"),
        (4, "I Saw God in Haiti!", "H. J. Smith"),
        (14, "The Government of Haiti Wants Christian Investors", "Equipe editorial"),
        (16, "The Northwest Area Was Stirred for God!", "J. Byron Klaue"),
    ],
    (1960, "06"): [
        (3, "Our Moral Code of Honor", "Mark W. Clark"),
        (4, "Pentecost Is Not a Denomination: It Is an Experience", "John H. Osteen"),
        (10, "A Report of the FGBMFI Hawaii Campaign", "Ruth Cannon"),
        (19, "A Million a Week Are Learning to Read!", "T. L. Osborn"),
        (23, "Lighthouses in the Orient and Southeast Asia", "Irvine J. Harrison"),
        (33, "The Challenge of Haiti Has Stirred My Blood", "S. Lee Braxton"),
    ],
    (1960, "07-08"): [
        (3, "A Modern Saul of Tarsus", "Thomas R. Nickel"),
        (6, "A Seventeenth-Generation Rabbi Accepts Christ", "Jack Robins"),
        (9, "A Jewish Rabbi Asks: What Is Pentecost?", "Jack Robins"),
        (12, "I'll Never Be the Same Again!", "Thomas R. Nickel"),
        (26, "God Has No Grandsons!", "David J. du Plessis"),
        (35, "The True Political Situation in the United States", "Truman Anderson"),
        (43, "Let Christ Bear Our Every Burden", "Lloyd Hamill"),
    ],
    (1960, "09"): [
        (6, "Overflow Meeting Experienced by Miami Chapter", "Russ Gray"),
        (8, "When Pentecost Fell in Minnesota", "Anna Vagle"),
        (10, "God's Great Faithfulness", "Oswald Smith"),
        (12, "Prove Me Now Herewith, Saith the Lord", "Zella Reynolds Mussen"),
        (18, "Enduring Faith That Delivers!", "Francis Thomas"),
        (24, "The Flame of David Brainerd's Soul", "Leonard Ravenhill"),
    ],
    (1960, "10"): [
        (3, "The Episcopalian Pentecostal Outpouring", "Thomas R. Nickel"),
        (6, "They Spake with Tongues and Magnified God!", "Dennis J. Bennett"),
        (9, "A High Church Episcopalian Becomes Pentecostal", "Jean Stone"),
        (11, "Speaking with Tongues Is Still Evident Today", "George W. Cornell"),
        (13, "Spirit-Filled Episcopalian Thrills Spokane Chapter", "Eleanor Kraus"),
    ],
    (1960, "11"): [
        (3, "Pentecostal Visitation among the Mennonites", "Gerald Derstine"),
        (10, "Christ Was the Answer to My Atheism", "Rachel E. Underwood"),
        (20, "Denver Chapter Stirred by Rabbi Jack Robins", "Hugh E. Graham"),
        (28, "Let's Not Condemn the Independents!", "Donald Gee"),
        (30, "Are You Grasping for Bubbles?", "Herb Jauchen"),
    ],
    (1960, "12"): [
        (3, "God's Holy Calling: A Minister of Healing", "William Standish Reed"),
        (6, "The Father, the Son, and Holy Spirit Are Healers", "William Standish Reed"),
        (10, "World Pentecostal and Ecumenical Movements", "David J. du Plessis"),
        (13, "Received Ye the Holy Ghost Since Ye Believed?", "Jean Stone"),
        (15, "We Cherish the Birth of Our Redeemer!", "Thomas R. Nickel"),
        (23, "Marvelous Is the Work of Our God", "C. C. Ford"),
    ],
}

ENGINE.ARTICLE_OVERRIDES.update(OVERRIDES)


def update_index(summaries: list[dict], targets: list[Path], rebuild: bool) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-MAI1958-DEZ1960-INICIO -->"
    end = "<!-- LOTE-MAI1958-DEZ1960-FIM -->"
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
        anchor = "<!-- LOTE-JUN1954-ABR1958-FIM -->"
        if anchor not in content:
            raise RuntimeError("Bloco cronológico anterior não encontrado")
        content = content.replace(anchor, anchor + "\n" + block, 1)

    map_heading = "## Mapa temático do lote maio de 1958–dezembro de 1960"
    map_block = f"""## Mapa temático do lote maio de 1958–dezembro de 1960

| Assunto | Edições e veios promissores |
|---|---|
| Expansão internacional | Mai. 1958–jun. 1960 — capítulos, convenções e campanhas na Ásia, Caribe, Europa e Américas |
| Fé e negócios | Mai. 1958–dez. 1960 — empresários, investimentos, administração, profissão e serviço |
| Comunicação cristã | Todo o lote — revista, rádio, folhetos, campanhas e testemunho público |
| Unidade cristã e ecumenismo | 1958–1960 — cooperação entre pentecostais, protestantes históricos e outros grupos |
| Vida pública e Guerra Fria | Out. 1958; jan.-set. 1960 — liberdade, comunismo, Israel, Haiti e política norte-americana |
| Conversão e vocação | Todo o lote — decisões pessoais, chamado, consagração e mudança de vida |
| Oração e curas alegadas | Presente em várias edições — sempre exigir linguagem clínica cautelosa e confirmação externa |
| Formação e juventude | Set. 1958 e convenções de 1960 — jovens, educação e continuidade geracional |

| Decisão potencial | Aplicação no lote |
|---|---|
| Apoiar lideranças locais | Capítulos e campanhas internacionais |
| Colocar profissão e recursos a serviço do bem | Empresários, médicos, advogados e comunicadores |
| Cooperar apesar de diferenças institucionais | Convenções e aproximação entre tradições cristãs |
| Perseverar diante de oposição e sofrimento | Testemunhos, missões e conflitos históricos |
| Usar comunicação com responsabilidade | Revista, rádio, imprensa e distribuição de folhetos |
| Submeter alegações à verificação | Relatos médicos, números de campanhas, política e ciência |

"""
    previous_heading = "## Mapa temático do lote junho de 1954–abril de 1958"
    if map_heading not in content:
        if previous_heading not in content:
            raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
        content = content.replace(previous_heading, map_block + previous_heading, 1)

    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote maio/1958–dezembro/1960")


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
