#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
identificar.py - separa NOME DE PESSOA de NOME DE INSTITUICAO em texto solto.

Porte do CardParser.swift do app CartaoContatos. A licao que veio de la:
o parser dos cartoes recebe `[String]` - so as linhas de texto, sem nenhuma
coordenada - e por isso aguenta diagramacoes completamente diferentes.
Aqui vale o mesmo: NAO usamos altura de fonte nem posicao. Capa de livro
tem diagramacao decidida pelo marketing, e o nome do autor as vezes e o
maior elemento da capa (Bavinck, Tripp). Geometria engana; semantica nao.

Tres camadas, na ordem do app:

    1. honorifico explicito ("Dr.", "Rev.", "Pastor")  -> ganha de tudo
    2. NER, SE passar no score                         -> spaCy PER/ORG
    3. maior score                                     -> sempre responde

A camada 2 nunca e obedecida cega: o app faz
`nameScore(entities.person) >= 15 ? entities.person : ""`, e a razao e boa -
NER erra em texto de OCR sujo, e o score barra o erro.
"""

import re, unicodedata

# --------------------------------------------------------------------------
# NER opcional. Sem spaCy o modulo continua funcionando so com o score -
# e o que o app faz quando o NLTagger nao devolve nada confiavel.
# --------------------------------------------------------------------------
_NLP = None
_NER_TENTADO = False

def _nlp():
    global _NLP, _NER_TENTADO
    if _NER_TENTADO:
        return _NLP
    _NER_TENTADO = True
    try:
        import spacy
        for m in ("es_core_news_sm", "pt_core_news_sm", "xx_ent_wiki_sm"):
            try:
                _NLP = spacy.load(m, disable=["parser", "lemmatizer"])
                break
            except Exception:
                continue
    except ImportError:
        _NLP = None
    return _NLP


def tem_ner():
    return _nlp() is not None


# --------------------------------------------------------------------------
# vocabulario
# --------------------------------------------------------------------------
HONORIFICO = re.compile(
    r"^\s*(?:dr|dra|rev|reverend|reverendo|pastor|pr|prof|professor|"
    r"padre|pe|bispo|mons)\.?\s+[a-zá-ú]", re.I)

# titulacao academica no fim do nome: forte sinal de pessoa
TITULACAO = re.compile(
    r"ph\.?\s*d\.?|m\.?\s*d\.?|d\.?\s*min\.?|ed\.?\s*d\.?|m\.?\s*div\.?|"
    r"th\.?\s*[dm]\.?|mba|jr\.?|sr\.?|iii?\b", re.I)

# pessoa juridica. No app sao "university|church|ltda|inc"; no mundo
# editorial a lista muda - quem assina o (c) costuma ser a editora ou uma
# sociedade, e foi exatamente isso que nos deu "Lubbers" como autor.
INSTITUICAO = re.compile(
    r"editor(?:a|ial|iale)?\b|edicion|ediciones|edicoes|publish|publicac|"
    r"press\b|books?\b|libros?\b|casa\b|sociedad|sociedade|society|"
    r"ministr|iglesia|igreja|church|universi|seminari|instituto|institut|"
    r"funda[cç]|associa|asociaci|grupo\b|group\b|ltda|s\.?a\.?$|inc\.?$|"
    r"llc\b|company|compan[hy]|colecc|cole[cç][aã]o|biblioteca|library|"
    r"congreso|congress|foundation|trust\b|academic|verlag|maison",
    re.I)

# papel declarado - nao e o autor da obra
PAPEL = re.compile(
    r"^\s*(?:editado|edited|edici[oó]n\s+de|editor|edit\.|coordena|organiza|"
    r"tradu|translat|versi[oó]n|prefaci|pr[oó]log|introducci|ilustra|"
    r"revis[aã]o|revisi[oó]n)\b", re.I)

# linhas que nao disputam nada
RUIDO = re.compile(
    r"^\s*(?:todos los derechos|todos os direitos|all rights|reservados|"
    r"isbn|impreso|printed|www\.|https?:|copyright|©|reina.?valera|"
    r"nueva versi|santa biblia|holy bible|used by permission|"
    r"usado con permiso|bestseller|best.?seller|new york times)", re.I)

SERIE = re.compile(
    r"^\s*(?:vol(?:umen|ume)?|tomo|parte|part|libro|book|serie|series)\b"
    r"\s*[:.]?\s*(?:[IVXLC]+|\d+|uno|dos|tres|um|dois|tr[eê]s|"
    r"one|two|three|primer[oa]?|segund[oa]|tercer[oa]?)\b", re.I)


def _sem_acento(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def normalizar(v):
    """Identidade para comparacao: sem acento, sem caixa, sem pontuacao."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", _sem_acento(v).lower()).split())


# --------------------------------------------------------------------------
# o score - equivalente do nameScore() do CardParser
# --------------------------------------------------------------------------
def autor_score(linha):
    """Quao parecido com nome de pessoa. Pesos herdados do app."""
    t = linha.strip()
    if not t:
        return -100
    baixo = t.lower()

    # descarte duro, como no app (digito, arroba, url)
    if re.search(r"\d", t) or "@" in t or "www." in baixo:
        return -100
    if RUIDO.match(t):
        return -100

    palavras = t.split()
    s = 0

    if HONORIFICO.match(t):
        s += 100
    if 2 <= len(palavras) <= 4:
        s += 20
    elif len(palavras) == 1:
        s -= 15          # sobrenome solto e ambiguo demais
    if TITULACAO.search(t):
        s += 40
    if INSTITUICAO.search(t):
        s -= 60
    if PAPEL.match(t):
        s -= 50

    # sigla curta toda em caixa alta: quase sempre selo, nao pessoa
    letras = [c for c in t if c.isalpha()]
    if letras and len(letras) <= 6 and t == t.upper():
        s -= 60

    if len(palavras) > 6:
        s -= 30

    # nome de gente costuma vir capitalizado palavra a palavra
    if len(palavras) >= 2 and all(
            p[:1].isupper() or p.lower() in ("de", "del", "da", "dos", "van",
                                             "von", "la", "le", "y", "e")
            for p in palavras if p):
        s += 15

    return s


PARTICULA = {"de", "del", "da", "das", "do", "dos", "van", "von", "der",
             "la", "le", "y", "e", "di", "el", "bin", "al"}

def caixa_normal(t):
    """'PAUL DAVID TRIPP' -> 'Paul David Tripp'.

    Sem isto o NER erra feio: medido nos dois modelos, "HERMAN BAVINCK"
    sai PER mas "PAUL DAVID TRIPP" sai ORG, enquanto "William Cunningham"
    - a mesma coisa em caixa normal - sai PER. Os modelos sao treinados
    em texto capitalizado, e capa de livro e quase toda caixa alta.

    A caixa so serve para PERGUNTAR ao modelo. O nome que guardamos vem
    sempre da linha original, senao "MACARTHUR" viraria "Macarthur".
    """
    if not t or t != t.upper():
        return t
    saida = []
    for i, p in enumerate(t.split()):
        b = p.lower()
        saida.append(b if (i and b in PARTICULA) else b[:1].upper() + b[1:])
    return " ".join(saida)


def ner_pessoa_org(linhas):
    """Devolve (pessoa, organizacao) pelo NER. Vazio se spaCy ausente."""
    nlp = _nlp()
    if not nlp:
        return "", ""
    pessoa = org = ""
    for ln in linhas[:12]:
        # tenta a linha como veio e tambem com a caixa normalizada; basta
        # uma das duas reconhecer
        for variante in dict.fromkeys([ln, caixa_normal(ln)]):
            try:
                doc = nlp(variante)
            except Exception:
                continue
            for ent in doc.ents:
                if ent.label_ in ("PER", "PERSON") and not pessoa:
                    if len(ent.text.split()) >= 2:
                        pessoa = ent.text
                elif ent.label_ in ("ORG",) and not org:
                    org = ent.text
            if pessoa:
                break
        if pessoa:
            break
    return pessoa, org


def escolher_pessoa(linhas):
    """As tres camadas do app, na mesma ordem e com o mesmo corte (>=15)."""
    cand = [l.strip() for l in linhas if l and l.strip()]
    if not cand:
        return "", "nenhuma linha"

    hon = next((l for l in cand if HONORIFICO.match(l)), "")
    if hon:
        return limpar_pessoa(hon), "honorifico"

    pessoa_ner, _ = ner_pessoa_org(cand)
    if pessoa_ner and autor_score(pessoa_ner) >= 15:
        return limpar_pessoa(pessoa_ner), "ner"

    melhor = max(cand, key=autor_score)
    if autor_score(melhor) >= 15:
        return limpar_pessoa(melhor), "score"
    return "", "nada passou no corte"


def autor_e_fragmento_do_titulo(autor, titulo, origem=""):
    """O 'autor' e na verdade um pedaco do titulo?

    Encontrado auditando o acervo: varias fichas traziam autores montados a
    partir do titulo, sempre na forma "Sobrenome, Nome", que parece valida:

        titulo "The Church and the Last Things"  ->  autor "Things, Last"
        titulo "UM CREDO ORTODOXO"               ->  autor "ORTODOXO, UM"
        titulo "EXAMINAIS AS ESCRITURAS"         ->  autor "AS, EXAMINAIS"

    O sinal e o autor estar INTEIRO dentro do titulo. Mas ele sozinho gera
    falso positivo legitimo - "Graham, Billy" em "El Manual de Billy Graham
    para Obreros Cristianos" e autor de verdade.

    O que separa os dois casos e ser nome de PESSOA, e so o NER responde
    isso: a pontuacao da 35 tanto para "Graham, Billy" quanto para
    "Things, Last" (duas palavras capitalizadas em ambos).

    Sem o NER instalado somos conservadores: so acusamos quando o dado veio
    do nome do arquivo, que e a fonte mais fraca. Preferimos deixar passar
    a acusar um autor legitimo.
    """
    if not autor or not titulo or autor.startswith("["):
        return False, ""

    pa = {w for w in normalizar(autor).split() if len(w) > 2}
    pt = {w for w in normalizar(titulo).split() if len(w) > 2}
    if not pa or not pa <= pt:
        return False, ""

    # fontes que ja provaram a autoria por si mesmas
    if any(marca in (origem or "").lower()
           for marca in ("cip", "api", "copyright", "isbn", "revis", "confirm")):
        return False, ""

    partes = [p.strip() for p in autor.split(",")]
    natural = " ".join(reversed(partes)) if len(partes) > 1 else autor

    if tem_ner():
        pessoa, _ = ner_pessoa_org([natural])
        if pessoa:
            return False, ""          # e gente: "Graham, Billy" passa
        origem_fraca = ("; veio do nome do arquivo"
                        if "nome do arquivo" in (origem or "").lower()
                        else "")
        return True, (f"'{autor}' esta inteiro dentro do titulo e o "
                      f"reconhecedor de nomes nao o identifica como pessoa"
                      f"{origem_fraca}")

    if "nome do arquivo" in (origem or "").lower():
        return True, (f"'{autor}' veio do nome do arquivo e esta inteiro "
                      f"dentro do titulo")
    return False, ""


def limpar_pessoa(v):
    """Tira honorifico e titulacao do fim - o cleanPersonName() do app."""
    v = re.sub(r"(?i)^\s*(?:dr|dra|rev|reverendo?|pastor|pr|prof|professor|"
               r"padre|pe|bispo|mons)\.?\s+", "", v.strip())
    v = re.sub(r"(?i)[,\s]*(?:ph\.?\s*d\.?|m\.?\s*d\.?|d\.?\s*min\.?|"
               r"ed\.?\s*d\.?|m\.?\s*div\.?|th\.?\s*[dm]\.?|mba)\s*$", "", v)
    return v.strip(" ,;·•+-")


def sobrenome_virgula(nome):
    """'John MacArthur Jr.' -> 'MacArthur Jr., John' (grafia do biblio)."""
    nome = limpar_pessoa(nome)
    if not nome or "," in nome:
        return nome
    p = nome.split()
    if len(p) < 2:
        return nome
    sufixo = ""
    if re.fullmatch(r"(?i)(jr|sr|i{1,3}|iv)\.?", p[-1]):
        sufixo = " " + p.pop()
    return f"{p[-1]}{sufixo}, {' '.join(p[:-1])}"


# --------------------------------------------------------------------------
# a separacao propriamente dita
# --------------------------------------------------------------------------
def separar(linhas, autor_conhecido=""):
    """Reivindicacao em sequencia, como o CardParser faz com os cartoes.

    Cada campo tira as suas linhas do bolo antes do proximo disputar. No
    fim, titulo e autor sao mutuamente exclusivos - o app zera a empresa
    quando ela sai igual ao nome, e aqui vale a mesma regra.
    """
    linhas = [l.strip() for l in linhas if l and l.strip()]
    r = {"titulo": "", "nmAutor0": "", "volume": "", "papeis": "",
         "origem_autor": "", "confianca": "baixa"}
    if not linhas:
        return r

    sobra = []
    for l in linhas:
        if RUIDO.match(l):
            continue
        if SERIE.match(l) and not r["volume"]:
            r["volume"] = l
            continue
        if PAPEL.match(l):
            r["papeis"] = (r["papeis"] + " | " + l).strip(" |")
            continue
        sobra.append(l)
    if not sobra:
        return r

    # 1) se ja sabemos o autor por outra camada (CIP, creditos, API),
    #    a linha que o contem esta identificada - nao ha o que decidir
    autor, origem = "", ""
    if autor_conhecido:
        alvo = set(normalizar(autor_conhecido).split())
        alvo = {w for w in alvo if len(w) > 2}
        for l in sobra:
            tokens = set(normalizar(l).split())
            if alvo and len(alvo & tokens) >= max(1, len(alvo) - 1):
                autor, origem = l, "confirmado"
                break

    # 2) senao, as tres camadas do app decidem
    if not autor:
        autor, origem = escolher_pessoa(sobra)
        if autor:
            # recupera a linha inteira que originou o nome
            autor = next((l for l in sobra
                          if normalizar(autor) in normalizar(l)), autor)

    r["origem_autor"] = origem
    r["nmAutor0"] = sobrenome_virgula(autor) if autor else ""

    # 3) titulo = o que sobrou, sem a linha do autor.
    #
    #    Aqui os livros pedem algo que os cartoes nao pediam: nome de
    #    pessoa cabe numa linha, titulo nao. "El Dolor / de la Perdida" e
    #    "ETICA / REFORMADA" chegam quebrados do OCR. Entao nao escolhemos
    #    a melhor LINHA - escolhemos o melhor TRECHO CONTIGUO, remontando
    #    as linhas vizinhas que sobraram juntas.
    idx = {l: i for i, l in enumerate(sobra)}
    resto = [l for l in sobra
             if l != autor and not INSTITUICAO.search(l) and autor_score(l) < 40]

    trechos, atual = [], []
    for l in resto:
        if atual and idx[l] != idx[atual[-1]] + 1:
            trechos.append(atual); atual = []
        atual.append(l)
    if atual:
        trechos.append(atual)

    if trechos:
        melhor = max(trechos, key=lambda t: sum(len(x.split()) for x in t))
        tit = " ".join(melhor).strip(" :,-·•")

        # limpezas que os testes pediram:
        # - sigla solta no comeco, resto de logo lido pelo OCR ("ECEF El Dolor")
        # - o nome do autor colado no fim ("Teologia Historica William Cunningham")
        tit = re.sub(r"^\s*[A-Z]{2,6}\s+(?=[A-ZÁ-Ú][a-zá-ú])", "", tit)
        if r["nmAutor0"]:
            # o nome pode estar colado em qualquer ordem: guardamos
            # "Cunningham, William" mas a folha de rosto traz "Teologia
            # Historica William Cunningham". Tentamos as duas.
            partes = [p for p in r["nmAutor0"].replace(",", " ").split() if len(p) > 2]
            for ordem in (partes, list(reversed(partes))):
                if not ordem:
                    break
                fim = r"[\s,;:.-]*" + r"\s+".join(re.escape(p) for p in ordem) + r"\s*$"
                sem = re.sub(fim, "", tit, flags=re.I)
                if sem != tit and len(sem.split()) >= 2:
                    tit = sem.strip()
                    break
        r["titulo"] = tit.strip(" :,-·•.")

    # exclusao mutua - o `company == name -> ""` do app
    if r["titulo"] and normalizar(r["titulo"]) == normalizar(r["nmAutor0"]):
        r["titulo"] = ""

    if r["nmAutor0"] and r["titulo"]:
        r["confianca"] = "alta" if origem in ("confirmado", "honorifico") \
                         else "media"
    return r
