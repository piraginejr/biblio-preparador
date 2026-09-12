#!/usr/bin/env python3
"""Mineração preliminar e retomável de 20 edições (jun/1954–abr/1958).

Extrai matérias e autores do OCR página a página, classifica assuntos por uma
taxonomia controlada e produz fichas que nunca substituem arquivos existentes.
O índice vivo recebe um bloco delimitado, também protegido contra duplicação.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    year: int
    month: str
    date: str
    volume: int
    number: int
    pdf_name: str


BATCH = [
    Config(1954, "06", "Junho de 1954", 2, 4, "Voice - FGBMFI - 2.4 (June 1954).pdf"),
    Config(1954, "07-08", "Julho–agosto de 1954", 2, 5, "Voice - FGBMFI - 2.5 (July-August 1954).pdf"),
    Config(1954, "09", "Setembro de 1954", 2, 6, "Voice-1954-09.pdf"),
    Config(1954, "10", "Outubro de 1954", 2, 7, "Voice - FGBMFI - 2.7 (October 1954).pdf"),
    Config(1954, "11", "Novembro de 1954", 2, 8, "Voice - FGBMFI - 2.8 (November 1954).pdf"),
    Config(1954, "12", "Dezembro de 1954", 2, 9, "Voice - FGBMFI - 2.9 (December 1954).pdf"),
    Config(1956, "01", "Janeiro de 1956", 3, 10, "Voice - FGBMFI - 3.10 (January 1956).pdf"),
    Config(1956, "03", "Março de 1956", 4, 2, "Voice - FGBMFI - 4.2 (March 1956).pdf"),
    Config(1956, "04", "Abril de 1956", 4, 3, "Voice - FGBMFI - 4.3 (April 1956).pdf"),
    Config(1956, "05", "Maio de 1956", 4, 4, "Voice-1956-05.pdf"),
    Config(1956, "06", "Junho de 1956", 4, 5, "Voice - FGBMFI - 4.5 (June 1956).pdf"),
    Config(1956, "07", "Julho de 1956", 4, 6, "Voice - FGBMFI - 4.6 (July 1956).pdf"),
    Config(1956, "08", "Agosto de 1956", 4, 7, "Voice - FGBMFI - 4.7 (August 1954).pdf"),
    Config(1956, "10", "Outubro de 1956", 4, 9, "Voice - FGBMFI - 4.9 (October 1956).pdf"),
    Config(1956, "11", "Novembro de 1956", 4, 10, "Voice - FGBMFI - 4.10 (November 1956).pdf"),
    Config(1956, "12", "Dezembro de 1956", 4, 11, "Voice - FGBMFI - 4.11 (December 1956).pdf"),
    Config(1958, "01", "Janeiro de 1958", 5, 12, "Voice - FGBMFI - 5.12 (January 1958).pdf"),
    Config(1958, "02", "Fevereiro de 1958", 6, 1, "Voice - FGBMFI - 6.1 (February 1958).pdf"),
    Config(1958, "03", "Março de 1958", 6, 2, "Voice - FGBMFI - 6.2 (March 1958).pdf"),
    Config(1958, "04", "Abril de 1958", 6, 3, "Voice - FGBMFI - 6.3 (April 1958).pdf"),
]


TAXONOMY = [
    ("missão transcultural", ("mission", "africa", "india", "mexico", "hong kong", "argentina", "sweden", "finland", "jamaica", "germany", "foreign")),
    ("expansão de capítulos", ("chapter", "convention", "fellowship", "director", "board")),
    ("fé e negócios", ("business", "industry", "company", "dollar", "prosper", "efficiency", "investment")),
    ("unidade cristã", ("unity", "united", "denomination", "fellowship", "together")),
    ("conversão e testemunho", ("conversion", "converted", "saved", "salvation", "testimony", "decision")),
    ("oração e cura alegada", ("heal", "healing", "miracle", "disease", "sick", "prayer", "prayed")),
    ("comunicação cristã", ("radio", "broadcast", "magazine", "voice", "press", "message")),
    ("liberdade e vida pública", ("president", "government", "communis", "freedom", "nixon", "nation")),
    ("vocação e consagração", ("calling", "called", "consecrat", "decision", "serve", "service")),
    ("juventude e formação", ("youth", "young", "school", "student", "children")),
    ("generosidade e recursos", ("offering", "fund", "give", "gave", "donat", "support")),
    ("sofrimento e perseverança", ("suffer", "trial", "persever", "attack", "sunk", "wilderness")),
    ("crucificação e ressurreição", ("crucifix", "resurrection", "empty tomb", "easter", "risen")),
]


DECISIONS = {
    "missão transcultural": "apoiar lideranças locais e servir além das fronteiras culturais",
    "expansão de capítulos": "organizar e fortalecer uma comunidade local",
    "fé e negócios": "colocar profissão, empresa e eficiência a serviço do bem",
    "unidade cristã": "cooperar apesar de diferenças institucionais",
    "conversão e testemunho": "reexaminar a própria vida e assumir publicamente uma mudança",
    "oração e cura alegada": "acolher quem sofre e buscar ajuda sem dispensar cuidado médico",
    "comunicação cristã": "usar comunicação e testemunho com responsabilidade",
    "liberdade e vida pública": "agir com responsabilidade na esfera pública",
    "vocação e consagração": "responder ao chamado com serviço concreto",
    "juventude e formação": "investir na formação de uma nova geração",
    "generosidade e recursos": "sustentar uma obra com transparência e regularidade",
    "sofrimento e perseverança": "perseverar diante de oposição, perda ou incerteza",
    "crucificação e ressurreição": "reorientar a vida à luz da morte e ressurreição de Cristo",
}


NOISE = (
    "published monthly", "per year", "printed in", "full gospel business men",
    "editorial office", "second class", "subscription", "vice-president",
    "secretary-treasurer", "directors", "proverbs 8:4",
)

ARTICLE_OVERRIDES = {
    (1954, "06"): [
        (3, "God's Service Station", "Lee Braxton"),
        (5, "We Want You in Our Midst!", "Demos Shakarian"),
        (9, "For Your Convenience and Your Enjoyment", "Thomas R. Nickel"),
        (13, "Convention Messages and Christian Service", "Equipe editorial"),
    ],
    (1954, "07-08"): [
        (2, "Our God Is Moving!", "Demos Shakarian"),
        (3, "Washington Convention Report", "Equipe editorial"),
        (11, "Little Lands Are Still the Same", "Miner Arganbright"),
        (13, "Argentina Revival Noted by Doctors", "Equipe editorial"),
    ],
    (1954, "09"): [
        (3, "Washington Chapter to Help Sponsor Hicks", "Equipe editorial"),
        (4, "The Minds and Hearts and Souls of Men", "Richard Nixon"),
        (8, "The Historic Argentina Revival", "Dan L. Thrapp"),
        (14, "Chapter Sponsors Branham-Hicks Hunt", "Equipe editorial"),
    ],
    (1954, "10"): [
        (3, "Golden Gate Convention Plans", "Equipe editorial"),
        (4, "God Is My Partner", "Pierce P. Brooks"),
        (8, "He Maketh the Dumb to Speak", "Demos Shakarian"),
        (9, "Opinion of a Non-Business Man", "Kenneth Ware"),
    ],
    (1954, "11"): [
        (4, "Western States Convention: Best Meeting Yet", "Thomas R. Nickel"),
        (8, "God Keeps His Word", "C. C. Ford"),
        (15, "For These We Thank Thee", "Alice E. Sherwood"),
    ],
    (1954, "12"): [
        (4, "God Guides My Hand", "Vaughn Shoemaker"),
        (5, "God's Finger Touched Me", "Thomas R. Nickel"),
        (8, "The True Christmas Story", "Percy D. Fraser"),
        (9, "God Used the Washington Convention", "Stanley H. Frodsham"),
    ],
    (1956, "03"): [
        (2, "New Chapter Established in Hong Kong", "Bulson Chang e Samuel Shih"),
        (14, "The Battle of Atlanta Rages Again!", "N. J. Roccaforte"),
        (17, "President's Inaugural Prayer Commemorated", "Thomas R. Nickel"),
        (19, "The World Needs Prayer in Action!", "Conrad N. Hilton"),
        (20, "This Nation Is Still a Nation Under God", "Dwight D. Eisenhower"),
    ],
    (1956, "10"): [
        (3, "The Golden Jubilee Will Continue in Our Hearts!", "Thomas R. Nickel"),
        (6, "A Revival and a Revolution", "A. G. Osterberg"),
        (9, "Eight New Directors Elected to the FGBMFI Board", "Equipe editorial"),
        (26, "The Victorious Home-Going of George Wyrsch", "Thomas R. Nickel"),
    ],
    (1958, "01"): [
        (3, "The Sungs Gave God His Share", "Thomas R. Nickel"),
        (10, "America's Spiritual Heritage", "Pat Adamson"),
        (14, "Your Body Is the Temple of the Holy Ghost", "R. E. McAlister"),
        (15, "Sustained by God on Unfriendly High Seas", "Marvin Hensley"),
        (21, "Remember What Manner of Man Ye Are!", "T. L. Osborn"),
        (24, "Azusa Street Golden Anniversary", "Thomas R. Nickel"),
    ],
    (1958, "03"): [
        (3, "Guy Braselton Believes God's Word!", "Thomas R. Nickel"),
        (17, "Washington Regional Convention Challenged Men", "Irvine J. Harrison"),
        (22, "Where Will I Spend Eternity?", "Betty J. Crocker"),
        (24, "F. F. Bosworth Promoted to Eternal Reward", "T. L. Osborn"),
        (25, "First-Century Missionary Prayer Requests", "Mary Joiner"),
        (32, "The International 300 Club", "Irvine J. Harrison"),
    ],
    (1958, "04"): [
        (3, "Crucifixion and Resurrection", "Thomas R. Nickel"),
        (7, "The Garden Tomb", "Solomon Mattar"),
        (15, "FGBMFI Chapters Stirring Germany for God", "Fritz Schaufele"),
        (22, "Holy Land Tour Between Two FGBMFI Conventions", "Irvine J. Harrison"),
        (23, "FGBMFI Chapter a Power for God in Puerto Rico", "Victor P. Colon"),
        (28, "Satan Enables Him to Eat Glass and Fire!", "Filomena E. Race"),
        (32, "Moments of Greatness in an Adventure Eternal", "Edmund A. Opitz"),
    ],
}


def clean(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t|*#♦❖□—–-")
    value = re.sub(r"(?<=\w)\s(?=\w(?:\s|$))", "", value)
    return value


def useful(line: str) -> bool:
    low = line.lower()
    return (
        4 <= len(line) <= 150
        and not any(item in low for item in NOISE)
        and len(re.findall(r"[A-Za-z]{2,}", line)) >= 2
    )


def normalize_author(value: str) -> str:
    value = re.split(r"\s{2,}|\||\(", value)[0]
    value = clean(re.sub(r"(?i)^by\s+", "", value))
    value = re.sub(r"[^A-Za-zÀ-ÿ.'’ -]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.title() if value.isupper() else value


def valid_author(value: str) -> bool:
    words = value.split()
    if not 1 <= len(words) <= 7 or not 3 <= len(value) <= 55:
        return False
    forbidden = {
        "the", "this", "that", "with", "from", "when", "where", "because",
        "continued", "page", "full", "gospel", "god", "his", "her", "their",
        "himself", "people", "stands", "speaks", "words", "brought", "because",
        "through", "every", "those", "followed", "once", "again",
    }
    if any(word.lower().strip(".") in forbidden for word in words):
        return False
    particles = {"de", "da", "do", "dos", "du", "van", "von", "jr", "sr"}
    for word in words:
        bare = word.strip(".'’-")
        if not bare or bare.lower() in particles:
            continue
        if not bare[0].isupper():
            return False
    return True


def headline_quality(value: str) -> bool:
    low = value.lower()
    banned = (
        "official publication", "executive staff", "demos shakarian",
        "thomas r. nickel", "subscribe", "men’s publication", "men's publication",
        "vol. ", "secretary", "vice-president",
        "matéria iniciada na página",
    )
    if any(item in low for item in banned):
        return False
    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", value)
    if len(letters) < 7 or len(value.split()) > 16:
        return False
    if sum(char.isalpha() or char.isspace() for char in value) / len(value) < 0.72:
        return False
    if value[0].islower():
        return False
    return useful(value)


def title_candidate(raw_lines: list[str], byline_index: int, page_number: int) -> str:
    for raw in reversed(raw_lines[max(0, byline_index - 5):byline_index]):
        first_column = re.split(r"\s{3,}|\|", raw.strip())[0]
        candidate = clean(first_column)
        if not headline_quality(candidate):
            continue
        if candidate.endswith((".", ",", ";", ":")):
            continue
        if len(candidate.split()) > 14:
            continue
        return candidate
    return f"Matéria iniciada na página {page_number}"


def article_from_page(page_number: int, page: str) -> tuple[str, str] | None:
    raw_lines = [line.rstrip() for line in page.splitlines() if line.strip()]
    for index, raw in enumerate(raw_lines[:45]):
        if "printed" in raw.lower():
            continue
        # Preserva o espaço largo que separa colunas antes de limpar o OCR.
        first_column = re.split(r"\s{3,}|\|", raw.strip())[0]
        byline = re.match(r"(?i)^by\s+(.{3,70})$", first_column)
        if byline:
            author = normalize_author(byline.group(1))
            title = title_candidate(raw_lines, index, page_number)
            if valid_author(author):
                return clean(title), author
    return None


def classify(text: str, limit: int = 5) -> list[str]:
    low = text.lower()
    scored = []
    for topic, keywords in TAXONOMY:
        score = sum(low.count(keyword) for keyword in keywords)
        if score:
            scored.append((score, topic))
    scored.sort(reverse=True)
    return [topic for _, topic in scored[:limit]] or ["fé e vida cristã"]


def page_count(pdf: Path) -> int:
    output = subprocess.run(
        ["/opt/homebrew/bin/pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    return int(re.search(r"^Pages:\s+(\d+)", output, re.MULTILINE).group(1))


def extract_articles(config: Config, text: str) -> list[dict]:
    pages = [page for page in text.split("\f") if page.strip()]
    articles = []
    seen = set()
    overrides = ARTICLE_OVERRIDES.get((config.year, config.month))
    if overrides:
        for number, title, author in overrides:
            body = pages[number - 1]
            if number < len(pages):
                body += "\n" + pages[number]
            topics = classify(body, 4)
            articles.append(
                {
                    "page": number,
                    "title": title,
                    "author": author,
                    "topics": topics,
                    "decisions": [DECISIONS[t] for t in topics[:2] if t in DECISIONS],
                }
            )
        return articles
    for number, page in enumerate(pages, 1):
        found = article_from_page(number, page)
        if not found:
            continue
        title, author = found
        key = (title.lower(), author.lower())
        if key in seen:
            continue
        seen.add(key)
        body = page
        if number < len(pages):
            body += "\n" + pages[number]
        topics = classify(body, 4)
        if not headline_quality(title):
            continue
        articles.append(
            {
                "page": number,
                "title": title,
                "author": author,
                "topics": topics,
                "decisions": [DECISIONS[t] for t in topics[:2] if t in DECISIONS],
            }
        )
    # Evita fichas excessivamente longas, preservando começo, meio e fim.
    if len(articles) > 9:
        indexes = sorted(set([0, 1, 2, len(articles) // 2, len(articles) - 4,
                              len(articles) - 3, len(articles) - 2, len(articles) - 1]))
        articles = [articles[i] for i in indexes if 0 <= i < len(articles)]
    return articles


def caution_lines(all_topics: list[str]) -> list[str]:
    cautions = [
        "Tratar números, resultados de campanhas e dados institucionais como alegações da revista até confirmação independente.",
        "Confirmar nomes, cargos, datas e locais afetados por ruído de OCR antes de uso público.",
    ]
    if "oração e cura alegada" in all_topics:
        cautions.append(
            "Não usar relatos de cura como diagnóstico, aconselhamento médico ou prova independente; preservar linguagem respeitosa sobre doença e deficiência."
        )
    if "liberdade e vida pública" in all_topics:
        cautions.append(
            "Contextualizar afirmações políticas no ambiente histórico da Guerra Fria e verificar discursos, cargos e eventos em fontes externas."
        )
    if "missão transcultural" in all_topics:
        cautions.append(
            "Evitar linguagem colonial ou paternalista; distinguir a voz dos autores norte-americanos da experiência das comunidades locais."
        )
    cautions.append("Respeitar a restrição da ORU e da FGBMFI contra redistribuição dos PDFs.")
    return cautions


def render(config: Config, pdf: Path, text_path: Path, text: str) -> tuple[str, dict]:
    articles = extract_articles(config, text)
    if not articles:
        raise RuntimeError(f"Nenhuma matéria identificada em {text_path}")
    all_topics = classify(text, 8)
    all_decisions = list(dict.fromkeys(DECISIONS[t] for t in all_topics if t in DECISIONS))[:7]
    authors = list(dict.fromkeys(a["author"] for a in articles))[:8]
    rows = []
    for article in articles:
        decision = "; ".join(article["decisions"]) or "realizar leitura dirigida antes de formular uma decisão"
        potential = (
            "Alto como fonte histórica, com cautela"
            if "oração e cura alegada" in article["topics"] or "liberdade e vida pública" in article["topics"]
            else "Alto"
        )
        rows.append(
            f"| {article['page']} | {article['title']} | {article['author']} | "
            f"{'; '.join(article['topics'])} | {decision} | {potential} |"
        )
    people_rows = []
    for author in authors:
        related = [a for a in articles if a["author"] == author]
        topics = list(dict.fromkeys(t for a in related for t in a["topics"]))[:4]
        decision = DECISIONS.get(topics[0], "examinar o testemunho e seu contexto")
        people_rows.append(
            f"| {author} | Autor ou personagem central na edição | "
            f"{'; '.join(topics)} | {decision} |"
        )
    veins = "\n".join(
        f"{i}. **{article['title']} — {article['author']}**\n"
        f"   - Potencial para {', '.join(article['topics'][:3])}."
        for i, article in enumerate(articles[:3], 1)
    )
    cautions = "\n".join(f"- {line}" for line in caution_lines(all_topics))
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages = page_count(pdf)
    markdown = f"""# FGMBV - Volume {config.volume}, número {config.number} - {config.date}

## Identificação

| Campo | Registro |
|---|---|
| Coleção | Full Gospel Business Men's Voice Magazine |
| Edição | Volume {config.volume}, número {config.number} |
| Data | {config.date} |
| Editor | Thomas R. Nickel |
| Extensão | {pages} páginas |
| Fonte | ORU Digital Showcase; exemplar preservado localmente |
| PDF local | `../../01-EDICOES-PDF/{config.year}/{config.pdf_name}` |
| Texto pesquisável | `{text_path.name}` |
| Estado | Mineração preliminar assistida concluída |
| Integridade | PDF validado; OCR presente; sem criptografia |
| SHA-256 | `{sha}` |

Esta ficha registra potencialidades localizadas por leitura estrutural e
taxonomia controlada. Ela não transforma matérias em ilustrações prontas nem
valida de modo independente alegações históricas, numéricas, científicas,
médicas ou sobrenaturais.

## Matérias e potencialidades

| Página inicial | Matéria | Autor ou personagem central | Assuntos básicos | Decisões potencialmente induzidas | Potencial |
|---:|---|---|---|---|---|
{chr(10).join(rows)}

## Personagens principais

| Personagem | Categoria ou contexto informado na edição | Assuntos associados | Decisões potenciais |
|---|---|---|---|
{chr(10).join(people_rows)}

## Índice de assuntos desta edição

{chr(10).join(f'- {topic};' for topic in all_topics[:-1])}
- {all_topics[-1]}.

## Índice de decisões potenciais desta edição

{chr(10).join(f'- {decision};' for decision in all_decisions[:-1])}
- {all_decisions[-1]}.

## Veios de maior potencial

{veins}

## Cuidados para pesquisa dirigida

{cautions}
"""
    summary = {
        "date": config.date.replace(" de ", " ").replace("–", "-"),
        "edition": f"Vol. {config.volume}, nº {config.number}",
        "pages": pages,
        "authors": authors,
        "topics": all_topics,
        "decisions": all_decisions,
    }
    return markdown, summary


def update_index(
    summaries: list[dict], targets: list[Path], rebuild: bool = False
) -> None:
    index = ROOT / "00-INDICE" / "FGMBV-INDEX.md"
    content = index.read_text(encoding="utf-8")
    start = "<!-- LOTE-JUN1954-ABR1958-INICIO -->"
    end = "<!-- LOTE-JUN1954-ABR1958-FIM -->"
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
    if start in content and rebuild:
        content = re.sub(
            re.escape(start) + r".*?" + re.escape(end),
            block,
            content,
            count=1,
            flags=re.DOTALL,
        )
    else:
        anchor = "| Mai. 1954 | Vol. 2, nº 3"
        anchor_pos = content.find(anchor)
        if anchor_pos < 0:
            raise RuntimeError("Linha-âncora de maio de 1954 não encontrada no índice")
        line_end = content.find("\n", anchor_pos)
        content = content[:line_end + 1] + block + "\n" + content[line_end + 1:]

    map_block = """## Mapa temático do lote junho de 1954–abril de 1958

| Assunto | Edições e veios promissores |
|---|---|
| Comunicação cristã | Jun. 1954–abr. 1958 — rádio, revista, testemunhos e campanhas |
| Conversão e testemunho | Todo o lote — autores, empresários, líderes e participantes de campanhas |
| Expansão de capítulos | Jun.-dez. 1954; jan.-dez. 1956; jan.-abr. 1958 — convenções e capítulos internacionais |
| Fé e negócios | Jun.-dez. 1954; jan. 1956; jan.-mar. 1958 — indústria, eficiência, recursos e serviço |
| Liberdade e vida pública | Set. 1954 e edições com contexto da Guerra Fria — verificar discursos e autoridades |
| Missão transcultural | Jul.-dez. 1954; mar.-dez. 1956; jan.-abr. 1958 — Europa, Ásia, Caribe e América Latina |
| Oração e curas alegadas | Presente em diversas edições — uso somente com cautela médica e confirmação externa |
| Unidade cristã | Convenções de 1954 e 1956; capítulos de Hong Kong, Calcutá, México e outras cidades |
| Vocação e consagração | Todo o lote — serviço, decisões pessoais e formação de lideranças |

| Decisão potencial | Aplicação no lote |
|---|---|
| Apoiar lideranças locais | Campanhas e capítulos internacionais |
| Colocar profissão e recursos a serviço do bem | Empresários, industriais, advogados e comunicadores |
| Cooperar apesar de diferenças institucionais | Convenções, capítulos e frentes pastorais |
| Investir na formação de uma nova geração | Juventude, escolas e novos líderes |
| Perseverar diante de oposição ou incerteza | Testemunhos pessoais, viagens e missões |
| Submeter alegações à verificação | Relatos médicos, científicos, políticos e estatísticas de campanhas |
| Usar comunicação com responsabilidade | Rádio, imprensa, revista e testemunho público |

"""
    heading = "## Mapa temático do lote maio de 1953–maio de 1954"
    if heading not in content:
        raise RuntimeError("Ponto de inserção do mapa temático não encontrado")
    if "## Mapa temático do lote junho de 1954–abril de 1958" not in content:
        content = content.replace(heading, map_block + heading, 1)
    temporary = index.with_suffix(".md.part")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(index)
    print("ÍNDICE ATUALIZADO: lote junho/1954–abril/1958")


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
        text_path = ROOT / "02-MINERACAO" / str(config.year) / f"{Path(config.pdf_name).stem}.txt"
        target = ROOT / "02-MINERACAO" / str(config.year) / (
            f"FGMBV-{config.year}-{config.month}-v{config.volume}-n{config.number}.md"
        )
        if not pdf.exists() or not text_path.exists():
            raise FileNotFoundError(f"Fonte ausente: {pdf} ou {text_path}")
        markdown, summary = render(
            config, pdf, text_path, text_path.read_text(encoding="utf-8", errors="replace")
        )
        existed = target.exists()
        if existed and not args.reconstruir:
            print(f"PRESERVADA: {target.relative_to(ROOT)}")
        else:
            temporary = target.with_suffix(".md.part")
            temporary.write_text(markdown, encoding="utf-8")
            temporary.replace(target)
            if existed and args.reconstruir:
                print(f"RECONSTRUÍDA: {target.relative_to(ROOT)}")
            else:
                created += 1
                print(f"CRIADA: {target.relative_to(ROOT)}")
        summaries.append(summary)
        targets.append(target)
    update_index(summaries, targets, rebuild=args.reconstruir)
    print(f"Novas fichas: {created}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
