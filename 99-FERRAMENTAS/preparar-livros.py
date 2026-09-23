#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 PREPARAR LIVROS - extrai metadados antes do cadastro no PIB-Biblio
============================================================================

 Etapa 1 de 2. Nao cadastra nada: le os PDFs, extrai o que da, consulta as
 bases publicas e gera uma planilha para conferencia. O cadastro em si fica
 para a etapa 2, que le a planilha ja revisada.

 Separar as duas etapas evita o que aconteceu com as revistas: descobrir
 problema de dado quando ja havia registros no ar.

 ORDEM DAS FONTES (com conciliacao quando houver divergencia)
 -------------------------------------------------
   1. codigo de barras da contracapa/capa - ISBN exato da edicao
   2. pagina de copyright do PDF          - confirma QUAL edicao e o arquivo
   3. Open Library / Google Books         - conferencia por ISBN
   4. CBL/ISBN Brasil                     - recuperacao por ISBN brasileiro
   5. nome do arquivo                     - rede de seguranca

 As APIs servem tambem de conferencia: quando divergem do copyright, a
 planilha marca o conflito em vez de escolher sozinha.

 USO
     pip3 install requests
     python3 preparar-livros.py                      # pergunta a pasta
     python3 preparar-livros.py --dir ~/Livros
     python3 preparar-livros.py --dir ~/Livros --sem-api

 SAIDA, dentro da pasta dos livros
     _livros-metadados.csv   uma linha por livro, com origem de cada campo
     _capas/                 capa extraida da pagina 1
============================================================================
"""

import argparse, collections, csv, difflib, hashlib, json, os, pathlib, re, shutil, statistics, subprocess, sys, tempfile, time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import identificar          # pessoa x instituicao (porte do app de cartoes)
try:
    import conferir_identidade
except ImportError:                      # o modulo e opcional
    conferir_identidade = None

try:
    import consultar_cbl
except Exception:
    consultar_cbl = None
try:
    import consultar_fontes_bibliograficas as fontes_biblio
except Exception:
    fontes_biblio = None
try:
    import consultar_grobid
except Exception:
    consultar_grobid = None
try:
    import importlib.util as _il
    _s = _il.spec_from_file_location(
        "lercapa", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "ler-capa.py"))
    lercapa = _il.module_from_spec(_s); _s.loader.exec_module(lercapa)
except Exception:
    lercapa = None

try:
    import requests
except ImportError:
    requests = None

# ---------------------------------------------------------------------------
# CONFIGURACAO
# ---------------------------------------------------------------------------

ASSUNTO_PADRAO = "Teologia"      # tipoAssunto1 e obrigatorio no Biblio
ACERVO_PADRAO  = ""              # preencha se sua biblioteca usa
DPI_CAPA       = 300   # a 100 o OCR nao le capa decorada - medido
MIN_OCR        = 300
LIMIAR_OCR     = 0.85   # texto bom deu 0.90-0.98; lixo de OCR, 0.59-0.81
                        # calibrado neste lote - ajuste se reprovar bom demais
PAGS_COPYRIGHT = 14              # ate onde procurar a pagina de creditos
PAGS_BIBLIOGRAFICAS = 30         # folha de rosto, creditos e CIP
PAGS_BIBLIOGRAFICAS_FINAIS = 12  # e-books podem mover copyright/CIP ao final

# Qualidade do PDF pesquisavel. Paginas curtas, capas, ilustracoes e paginas
# em branco nao podem ser julgadas como se fossem paginas corridas. O corte
# por pagina e deliberadamente menor que o corte usado para escolher o motor
# de extracao; o conjunto do documento e que decide o estado do OCR.
MIN_CHARS_PAGINA = 150
LIMIAR_OCR_PAGINA = 0.78
MIN_COBERTURA_PESQUISAVEL = 0.80
MAX_FRACAO_TEXTO_FRACO = 0.05

# ISBN criado em 1970 (ISO 2108). O de 13 digitos so virou obrigatorio em
# 2007 - por isso obras anteriores legitimamente so tem o de 10.
ANO_ISBN, ANO_ISBN13 = 1970, 2007

# Cadastro editavel que acompanha o aplicativo. O catalogo local amplia essa
# memoria com nomes ja confirmados, sem embutir decisoes de um livro no codigo.
ARQUIVO_PERIODICOS = pathlib.Path(__file__).with_name(
    "periodicos-conhecidos.json")
_CACHE_PERIODICOS = None
ARQUIVO_TITULOS_RUIDOSOS = pathlib.Path(__file__).with_name(
    "titulos-ruidosos-conhecidos.json")
_CACHE_TITULOS_RUIDOSOS = None
ARQUIVO_AUTORES_RUIDOSOS = pathlib.Path(__file__).with_name(
    "autores-ruidosos-conhecidos.json")
_CACHE_AUTORES_RUIDOSOS = None
ARQUIVO_EDITORAS_CIDADES = pathlib.Path(__file__).with_name(
    "editoras-cidades.json")
_CACHE_EDITORAS_CIDADES = None
_CACHE_FONTES_COMERCIAIS = {}
# Flag do macOS para arquivo gerenciado por provedor e ainda sem dados locais.
# Abrir um desses pequenos caches fazia o lote esperar indefinidamente pelo
# Dropbox. Cache e acelerador, nunca requisito: ausente localmente, e ignorado.
SF_DATALESS = 0x40000000

DIGITAL  = r"epub|pdf|mobi|kindle|electr|eletr|ebook|libro electr"
BROCHURA = r"bolsillo|\btp\b|paperback|r[uú]stica|broch[ée]|brochura|pbk"

V,A,R,AZ,N,F = ('\033[0;32m','\033[0;33m','\033[0;31m','\033[0;34m','\033[1m','\033[0m')
ok   = lambda m: print(f"{V}  ok  {F}{m}")
warn = lambda m: print(f"{A}  !!  {F}{m}")
err  = lambda m: print(f"{R}  xx  {F}{m}")
info = lambda m: print(f"      {m}")


def _normalizar_nome_periodico(valor):
    return " ".join(identificar.normalizar(valor or "").split())


def carregar_titulos_ruidosos(atualizar=False):
    """Carrega a memória editável de falsos títulos recorrentes."""
    global _CACHE_TITULOS_RUIDOSOS
    if _CACHE_TITULOS_RUIDOSOS is not None and not atualizar:
        return list(_CACHE_TITULOS_RUIDOSOS)
    try:
        with ARQUIVO_TITULOS_RUIDOSOS.open(encoding="utf-8") as f:
            brutos = json.load(f).get("itens", [])
    except (OSError, ValueError, json.JSONDecodeError):
        brutos = []
    itens = []
    for bruto in brutos:
        texto = " ".join(str(bruto.get("texto", "")).split())
        modo = str(bruto.get("modo", "exato")).strip().lower()
        if not texto or modo not in {"exato", "prefixo", "contem"}:
            continue
        itens.append({
            "texto": texto,
            "normalizado": identificar.normalizar(texto),
            "modo": modo,
            "motivo": " ".join(str(bruto.get("motivo", "ruído conhecido")).split()),
        })
    _CACHE_TITULOS_RUIDOSOS = list(itens)
    return itens


def identificar_titulo_ruidoso(titulo, itens=None):
    """Explica por que um texto coincide com a memória de falsos títulos."""
    normalizado = identificar.normalizar(" ".join(str(titulo or "").split()))
    if not normalizado:
        return ""
    for item in (itens if itens is not None else carregar_titulos_ruidosos()):
        conhecido = item.get("normalizado", "")
        modo = item.get("modo", "exato")
        coincide = (
            normalizado == conhecido if modo == "exato" else
            normalizado.startswith(conhecido) if modo == "prefixo" else
            conhecido in normalizado
        )
        if coincide:
            return item.get("motivo", "ruído conhecido")
    return ""


def carregar_autores_ruidosos(atualizar=False):
    """Carrega a memória editável de falsos autores recorrentes."""
    global _CACHE_AUTORES_RUIDOSOS
    if _CACHE_AUTORES_RUIDOSOS is not None and not atualizar:
        return list(_CACHE_AUTORES_RUIDOSOS)
    try:
        with ARQUIVO_AUTORES_RUIDOSOS.open(encoding="utf-8") as f:
            brutos = json.load(f).get("itens", [])
    except (OSError, ValueError, json.JSONDecodeError):
        brutos = []
    itens = []
    for bruto in brutos:
        texto = " ".join(str(bruto.get("texto", "")).split())
        modo = str(bruto.get("modo", "exato")).strip().lower()
        if not texto or modo not in {"exato", "prefixo", "contem"}:
            continue
        itens.append({
            "texto": texto,
            "normalizado": identificar.normalizar(texto),
            "modo": modo,
            "motivo": " ".join(str(bruto.get("motivo", "ruído conhecido")).split()),
        })
    _CACHE_AUTORES_RUIDOSOS = list(itens)
    return itens


def identificar_autor_ruidoso(autor, itens=None):
    """Explica por que um texto coincide com a memória de falsos autores."""
    normalizado = identificar.normalizar(
        " ".join(str(autor or "").replace(",", " ").split()))
    if not normalizado:
        return ""
    for item in (itens if itens is not None else carregar_autores_ruidosos()):
        conhecido = item.get("normalizado", "")
        modo = item.get("modo", "exato")
        coincide = (
            normalizado == conhecido if modo == "exato" else
            normalizado.startswith(conhecido) if modo == "prefixo" else
            conhecido in normalizado
        )
        if coincide:
            return item.get("motivo", "ruído conhecido")
    return ""


def _parece_nome_periodico(valor):
    n = _normalizar_nome_periodico(valor)
    return bool(re.search(
        r"\b(?:revista|journal|magazine|periodico|theologica|theology|"
        r"fides|semeia|ciberteologia)\b", n))


def _pastas_metadados_catalogo():
    """Localiza a memoria bibliografica sem depender da pasta corrente."""
    candidatas = [
        pathlib.Path(__file__).resolve().parent.parent / "livros" / "_metadados",
        pathlib.Path.cwd() / "livros" / "_metadados",
        pathlib.Path.home() / "Library" / "Application Support"
        / "Biblio Preparador" / "revista" / "livros" / "_metadados",
    ]
    vistas = set()
    for pasta in candidatas:
        chave = str(pasta.resolve())
        if chave not in vistas and pasta.is_dir():
            vistas.add(chave)
            yield pasta


def _normalizar_editora_chave(valor):
    texto = limpar_editora_bibliografica(valor)
    texto = re.sub(r"(?i)^(?:editora|editorial|edi[çc][õo]es|"
                   r"ediciones|publisher|publishing|press)\s+", "", texto)
    texto = re.sub(r"(?i)\s+(?:editora|editorial|edi[çc][õo]es|"
                   r"ediciones|publisher|publishing|press)$", "", texto)
    return identificar.normalizar(texto)


def cidade_bibliograficamente_plausivel(valor):
    cidade = " ".join(str(valor or "").split()).strip(" ,.;:-")
    if not cidade or len(cidade) < 3:
        return False
    if re.search(r"(?i)^\[?\s*(?:s\.?\s*l\.?|sem\s+local)\s*\]?$", cidade):
        return False
    if re.search(r"(?i)^(?:s\.?\s*n\.?|sem\s+editora|editora)$", cidade):
        return False
    if re.search(r"[@:/\\]|www\.|https?", cidade, re.I):
        return False
    if len(cidade.split()) > 6:
        return False
    return True


CIDADES_PUBLICACAO_COMUNS = {
    "sao paulo", "rio de janeiro", "curitiba", "belo horizonte",
    "brasilia", "goiania", "campinas", "santos", "recife", "salvador",
    "fortaleza", "porto alegre", "belem", "londrina", "sao jose dos campos",
    "niteroi", "petropolis", "viçosa", "vicosa", "wheaton", "grand rapids",
    "nashville", "chicago", "new york", "london", "oxford", "cambridge",
    "leicester", "downers grove", "philadelphia", "boston", "miami",
    "barcelona", "madrid", "viladecavalls", "buenos aires", "bogota",
    "lisboa", "paris", "geneva", "genebra",
}


def parece_nome_cidade_publicacao(valor):
    texto = " ".join(str(valor or "").split()).strip(" ,.;:-")
    if not cidade_bibliograficamente_plausivel(texto):
        return False
    n = identificar.normalizar(texto)
    if n in CIDADES_PUBLICACAO_COMUNS:
        return True
    return bool(re.search(
        r"(?i)^(?:s[ãa]o|santo|santa|new|rio|belo|grand|downers|"
        r"buenos|porto)\s+[A-ZÁ-Úa-zá-ú .'-]{3,40}$",
        texto))


def corrigir_editora_lugar(editora, lugar):
    """Corrige inversão frequente: cidade no campo editora e editora no lugar."""
    editora = " ".join(str(editora or "").split()).strip(" ,.;:-")
    lugar = " ".join(str(lugar or "").split()).strip(" ,.;:-")
    if editora and parece_nome_cidade_publicacao(editora):
        if lugar and editora_bibliograficamente_plausivel(lugar):
            return lugar, editora, "campos editora/lugar invertidos"
        if not lugar:
            return "", editora, "cidade capturada no campo editora"
    return editora, lugar, ""


def carregar_editoras_cidades(atualizar=False):
    """Tabela incremental editora -> cidade provável.

    A tabela nasce de um JSON editável e é reforçada pelos metadados já
    gerados. O retorno é conservador: associações únicas ficam registradas,
    mas só entram como sugestão automática quando há recorrência ou cadastro
    explícito.
    """
    global _CACHE_EDITORAS_CIDADES
    if _CACHE_EDITORAS_CIDADES is not None and not atualizar:
        return dict(_CACHE_EDITORAS_CIDADES)
    dados = {"editoras": []}
    try:
        dados = json.loads(ARQUIVO_EDITORAS_CIDADES.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    por_chave = {}
    for item in dados.get("editoras", []):
        editora = " ".join(str(item.get("editora", "")).split())
        cidade = " ".join(str(item.get("cidade", "")).split())
        if (not editora_bibliograficamente_plausivel(editora)
                or not cidade_bibliograficamente_plausivel(cidade)):
            continue
        chave = _normalizar_editora_chave(editora)
        if not chave:
            continue
        por_chave[chave] = {
            "editora": editora,
            "cidade": cidade,
            "fonte": item.get("fonte", "cadastro local"),
            "ocorrencias": int(item.get("ocorrencias", 1) or 1),
            "confianca": item.get("confianca", "cadastro"),
        }

    observados = collections.defaultdict(collections.Counter)
    formas = {}
    for pasta in _pastas_metadados_catalogo():
        for arquivo in pasta.glob("*.json"):
            try:
                meta = json.loads(arquivo.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            editora = " ".join(str(meta.get("editora", "")).split())
            cidade = " ".join(str(meta.get("lugar", "")
                                  or meta.get("cidade", "")).split())
            if (not editora_bibliograficamente_plausivel(editora)
                    or not cidade_bibliograficamente_plausivel(cidade)):
                continue
            chave = _normalizar_editora_chave(editora)
            if not chave:
                continue
            observados[chave][cidade] += 1
            formas.setdefault(chave, editora)

    for chave, cidades in observados.items():
        cidade, ocorrencias = cidades.most_common(1)[0]
        if chave in por_chave:
            por_chave[chave]["ocorrencias_catalogo"] = sum(cidades.values())
            continue
        # Uma única ocorrência pode ser erro de OCR ou caso atípico. Duas ou
        # mais já indicam padrão local; três ou mais entram com confiança alta.
        if ocorrencias < 2:
            continue
        por_chave[chave] = {
            "editora": formas.get(chave, chave),
            "cidade": cidade,
            "fonte": "metadados locais",
            "ocorrencias": ocorrencias,
            "confianca": "alta" if ocorrencias >= 3 else "media",
        }
    _CACHE_EDITORAS_CIDADES = dict(por_chave)
    return dict(por_chave)


def cidade_sugerida_por_editora(editora, tabela=None):
    if not editora_bibliograficamente_plausivel(editora):
        return {}
    chave = _normalizar_editora_chave(editora)
    if not chave:
        return {}
    tabela = tabela if tabela is not None else carregar_editoras_cidades()
    item = tabela.get(chave)
    if item:
        return dict(item)
    # Fallback suave para variações com/sem "Editora", Ltda., Brasil etc.
    tokens = {p for p in chave.split() if len(p) > 2 and p not in {
        "editora", "editorial", "edicoes", "publicacoes", "ltda", "brasil"}}
    if len(tokens) < 2:
        return {}
    melhor = None
    melhor_score = 0
    for chave_tabela, candidato in tabela.items():
        tc = {p for p in chave_tabela.split() if len(p) > 2}
        score = len(tokens & tc) / max(1, len(tokens | tc))
        if score > melhor_score:
            melhor, melhor_score = candidato, score
    return dict(melhor) if melhor and melhor_score >= 0.72 else {}


def aplicar_lugar_por_editora(ficha):
    """Preenche cidade ausente por tabela editora->cidade, sem sobrescrever."""
    if not isinstance(ficha, dict) or ficha.get("lugar"):
        return ficha
    sugestao = cidade_sugerida_por_editora(ficha.get("editora", ""))
    cidade = sugestao.get("cidade", "")
    if cidade:
        ficha["lugar"] = cidade
        ficha["origem_lugar"] = "cidade sugerida pela editora conhecida"
        ficha["fonte_lugar"] = sugestao.get("fonte", "")
        ficha["confianca_lugar"] = sugestao.get("confianca", "")
    return ficha


def aprender_editora_cidade(editora, cidade, fonte="revisão/manual"):
    """Acrescenta associação confirmada pelo operador ao JSON local."""
    editora = " ".join(str(editora or "").split())
    cidade = " ".join(str(cidade or "").split())
    if (not editora_bibliograficamente_plausivel(editora)
            or not cidade_bibliograficamente_plausivel(cidade)):
        return False
    chave = _normalizar_editora_chave(editora)
    try:
        dados = json.loads(ARQUIVO_EDITORAS_CIDADES.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        dados = {"versao": 1, "editoras": []}
    itens = dados.setdefault("editoras", [])
    for item in itens:
        if _normalizar_editora_chave(item.get("editora", "")) == chave:
            item["editora"] = item.get("editora") or editora
            item["cidade"] = cidade
            item["fonte"] = fonte
            item["confianca"] = "revisada"
            item["ocorrencias"] = int(item.get("ocorrencias", 0) or 0) + 1
            break
    else:
        itens.append({
            "editora": editora, "cidade": cidade, "fonte": fonte,
            "confianca": "revisada", "ocorrencias": 1,
        })
    dados["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    dados["editoras"] = sorted(
        itens, key=lambda x: identificar.normalizar(x.get("editora", "")))
    ARQUIVO_EDITORAS_CIDADES.write_text(
        json.dumps(dados, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    global _CACHE_EDITORAS_CIDADES
    _CACHE_EDITORAS_CIDADES = None
    return True


def carregar_periodicos_conhecidos(incluir_catalogo=True, atualizar=False):
    """Une cadastro explicito e nomes recorrentes confirmados no acervo.

    A aprendizagem local e conservadora: considera apenas fichas ja
    classificadas como artigo/revista e fontes com identidade de periodico.
    """
    global _CACHE_PERIODICOS
    if _CACHE_PERIODICOS is not None and incluir_catalogo and not atualizar:
        return list(_CACHE_PERIODICOS)
    periodicos = []
    try:
        with ARQUIVO_PERIODICOS.open(encoding="utf-8") as f:
            periodicos = json.load(f).get("periodicos", [])
    except (OSError, ValueError, json.JSONDecodeError):
        periodicos = []

    por_nome = {}
    for item in periodicos:
        nome = " ".join(str(item.get("nome", "")).split())
        if not nome:
            continue
        aliases = [nome] + list(item.get("aliases", []))
        por_nome[_normalizar_nome_periodico(nome)] = {
            "nome": nome,
            "aliases": list(dict.fromkeys(
                " ".join(str(a).split()) for a in aliases if str(a).strip())),
            "issn": list(item.get("issn", [])),
            "fonte": str(item.get("fonte", "")),
            "origem": "cadastro",
        }

    if incluir_catalogo:
        observados = collections.Counter()
        forma = {}
        for pasta in _pastas_metadados_catalogo():
            for arquivo in pasta.glob("*.json"):
                try:
                    with arquivo.open(encoding="utf-8") as f:
                        dados = json.load(f)
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if dados.get("tipo_documento") not in {"artigo", "revista"}:
                    continue
                fonte = " ".join(str(dados.get("editora", "")).split())
                if not fonte or not _parece_nome_periodico(fonte):
                    continue
                chave = _normalizar_nome_periodico(fonte)
                observados[chave] += 1
                forma.setdefault(chave, fonte)
        for chave, quantidade in observados.items():
            if chave in por_nome:
                continue
            # O catálogo só ensina por recorrência ou por ISSN. Nem mesmo a
            # palavra "Revista" vence sozinha: ela também pode fazer parte de
            # um campo deformado pelo OCR.
            if quantidade < 2:
                continue
            por_nome[chave] = {
                "nome": forma[chave], "aliases": [forma[chave]], "issn": [],
                "origem": "catalogo", "ocorrencias": quantidade,
            }
    resultado = list(por_nome.values())
    if incluir_catalogo:
        _CACHE_PERIODICOS = list(resultado)
    return resultado


def identificar_periodico_conhecido(texto, periodicos=None):
    """Retorna o nome canonico; aliases de uma palavra ocupam linha propria."""
    bruto = texto or ""
    normalizado = _normalizar_nome_periodico(bruto)
    linhas = [(_normalizar_nome_periodico(x.strip()), pos)
              for pos, x in enumerate(bruto.splitlines()) if x.strip()]
    candidatos = []
    for item in (periodicos if periodicos is not None
                 else carregar_periodicos_conhecidos()):
        issns = [re.sub(r"[^0-9X]", "", str(x).upper())
                 for x in item.get("issn", [])]
        linhas_issn = [re.sub(r"[^0-9X]", "", x.upper())
                       for x in bruto.splitlines()]
        if any(len(issn) == 8 and any(issn in linha for linha in linhas_issn)
               for issn in issns):
            candidatos.append((-1, item.get("nome", "")))
        for alias in item.get("aliases", []):
            n_alias = _normalizar_nome_periodico(alias)
            if not n_alias:
                continue
            if len(n_alias.split()) == 1:
                posicoes = [
                    pos for linha, pos in linhas
                    if (linha == n_alias
                        or re.match(re.escape(n_alias)
                                    + r"\s+(?:vol(?:ume)?|v|n|issue|ano|"
                                      r"\d{1,3}\b|janeiro|fevereiro|marco|"
                                      r"abril|maio|junho|julho|agosto|setembro|"
                                      r"outubro|novembro|dezembro|january|"
                                      r"february|march|april|may|june|july|"
                                      r"august|september|october|november|"
                                      r"december)\b",
                                    linha))]
                if posicoes:
                    candidatos.append((posicoes[0] * 1000,
                                       item.get("nome", alias)))
                continue
            achado = re.search(r"(?<!\w)" + re.escape(n_alias)
                               + r"(?=$|[^\w]|[ivxlcdm]+\b)", normalizado)
            if achado:
                candidatos.append((achado.start(), item.get("nome", alias)))
    return min(candidatos, default=(0, ""), key=lambda x: x[0])[1]


def revisao_manual(caminho):
    """Carrega decisao bibliografica revisada sem embuti-la no programa.

    O hash impede que uma correcao pelo nome seja aplicada a outro PDF que
    por acaso receba o mesmo nome. O arquivo de revisoes e pequeno, legivel e
    pode acompanhar o catalogo local sem duplicar o livro.
    """
    caminho = os.path.abspath(caminho)
    nome = os.path.basename(caminho)
    atual = os.path.dirname(caminho)
    for _ in range(5):
        arquivo = os.path.join(atual, "_controle", "revisoes-manuais.json")
        if os.path.exists(arquivo):
            try:
                with open(arquivo, encoding="utf-8") as f:
                    dados = json.load(f)
                rev = dados.get("livros", {}).get(nome, {})
                if not rev:
                    return {}
                esperado = rev.get("hash_sha256", "")
                if esperado:
                    h = hashlib.sha256()
                    with open(caminho, "rb") as f:
                        for bloco in iter(lambda: f.read(1024 * 1024), b""):
                            h.update(bloco)
                    if h.hexdigest() != esperado:
                        return {}
                return rev
            except (OSError, ValueError, json.JSONDecodeError):
                return {}
        pai = os.path.dirname(atual)
        if pai == atual:
            break
        atual = pai
    return {}


CAMPOS_APRENDIZADO_REVISAO = (
    "titulo", "subTitulo", "nmAutor0", "editora", "tipo_documento",
    "edicao", "data",
)


def _arquivo_controle_proximo(caminho, nome):
    """Encontra um arquivo de controle da biblioteca sem criar outra raiz."""
    atual = pathlib.Path(caminho).resolve()
    atual = atual.parent if atual.suffix else atual
    for _ in range(6):
        controle = atual / "_controle"
        if controle.is_dir():
            return controle / nome
        if atual.parent == atual:
            break
        atual = atual.parent
    return None


def registrar_aprendizados_da_revisao(caminho, automatico, revisao,
                                      agora_iso=None):
    """Registra correcoes recorrentes como candidatas, nunca como regra.

    Uma revisao humana continua valendo somente para o hash aprovado. Quando
    ela substitui um valor automatico nao vazio, guardamos a diferenca numa
    memoria separada. Reprocessar o mesmo PDF nao aumenta a recorrencia: cada
    hash conta uma unica vez. A promocao para uma regra geral permanece uma
    decisao humana, porque o mesmo texto pode ser ruido em uma obra e legitimo
    em outra.
    """
    if not isinstance(revisao, dict) or not isinstance(automatico, dict):
        return []
    campos = revisao.get("campos", {})
    if not isinstance(campos, dict):
        return []
    arquivo_memoria = _arquivo_controle_proximo(
        caminho, "aprendizados-candidatos.json")
    if arquivo_memoria is None:
        return []
    try:
        memoria = json.loads(arquivo_memoria.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        memoria = {"versao": 1, "descricao": (
            "Diferencas entre a extracao automatica e revisoes humanas. "
            "Sao candidatas; nunca se tornam regras sem aprovacao."),
            "candidatos": {}}
    candidatos = memoria.setdefault("candidatos", {})
    digest_pdf = str(revisao.get("hash_sha256", ""))
    instante = agora_iso or datetime.now().isoformat(timespec="seconds")
    observados = []
    for campo in CAMPOS_APRENDIZADO_REVISAO:
        if campo not in campos:
            continue
        anterior = " ".join(str(automatico.get(campo, "") or "").split())
        corrigido = " ".join(str(campos.get(campo, "") or "").split())
        anterior_n = identificar.normalizar(anterior)
        corrigido_n = identificar.normalizar(corrigido)
        # Ausencia e comum e nao identifica um erro recorrente. Esta memoria
        # procura valores plausiveis, mas errados, produzidos pela automacao.
        if not anterior_n or anterior_n == corrigido_n:
            continue
        base = f"{campo}\0{anterior_n}"
        chave = hashlib.sha256(base.encode("utf-8")).hexdigest()[:20]
        item = candidatos.setdefault(chave, {
            "campo": campo,
            "valor_automatico": anterior,
            "valor_automatico_normalizado": anterior_n,
            "correcoes_observadas": [],
            "ocorrencias": [],
            "total_arquivos": 0,
            "status": "candidato",
        })
        if corrigido and corrigido not in item["correcoes_observadas"]:
            item["correcoes_observadas"].append(corrigido)
        identidade = digest_pdf or os.path.basename(str(caminho))
        existentes = {o.get("identidade") for o in item["ocorrencias"]}
        if identidade not in existentes:
            item["ocorrencias"].append({
                "identidade": identidade,
                "arquivo": os.path.basename(str(caminho)),
                "observado_em": instante,
            })
        item["total_arquivos"] = len(item["ocorrencias"])
        item["ultima_observacao"] = instante
        item["recomendacao"] = (
            "avaliar regra geral" if item["total_arquivos"] >= 3
            else "aguardar recorrencia ou revisao humana")
        observados.append({"chave": chave, "campo": campo,
                           "total_arquivos": item["total_arquivos"]})
    if not observados:
        return []
    memoria["atualizado_em"] = instante
    arquivo_memoria.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo_memoria.with_suffix(arquivo_memoria.suffix + ".tmp")
    temporario.write_text(
        json.dumps(memoria, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    os.replace(temporario, arquivo_memoria)
    return observados


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

# qual motor leu o ultimo arquivo - vai para a planilha. Escolher em
# silencio foi o que escondeu, por varias rodadas, que o Vision nem
# estava sendo usado fora da capa.
MOTOR = {"ultimo": "", "erro_ocr": ""}


def texto_pdftotext(f, ate=PAGS_COPYRIGHT):
    try:
        return subprocess.run(["pdftotext", "-f", "1", "-l", str(ate), f, "-"],
                              capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


def paginas_pdftotext(f, ate=None):
    """Extrai texto preservando a fronteira entre as paginas.

    A antiga extracao juntava tudo. Com isso, um ISBN podia consumir o
    primeiro algarismo da linha seguinte e um ano de nascimento podia virar
    ano de publicacao. O caractere form-feed produzido pelo Poppler e uma
    fronteira confiavel e barata para a etapa bibliografica.
    """
    cmd = ["pdftotext", "-layout"]
    if ate:
        cmd += ["-f", "1", "-l", str(ate)]
    cmd += [f, "-"]
    try:
        bruto = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=240).stdout
    except Exception:
        return []
    paginas = bruto.split("\f")
    if paginas and not paginas[-1].strip():
        paginas.pop()
    return paginas


def _pagina_tem_conteudo_visual(f, numero):
    """Distingue pagina realmente vazia de imagem sem camada de texto.

    Renderiza em baixa resolucao e le o PGM diretamente, sem depender de
    Pillow. Retorna None se o Poppler nao conseguir renderizar.
    """
    import tempfile
    with tempfile.TemporaryDirectory(prefix="biblio-pagina-") as tmp:
        base = os.path.join(tmp, "pagina")
        try:
            resultado = subprocess.run(
                ["pdftoppm", "-f", str(numero), "-l", str(numero),
                 "-r", "36", "-gray", "-singlefile", f, base],
                capture_output=True, timeout=60)
            pgm = pathlib.Path(base + ".pgm")
            if resultado.returncode or not pgm.is_file():
                return None
            bruto = pgm.read_bytes()
        except Exception:
            return None
    cabecalho = re.match(
        br"P5\s+(?:#[^\r\n]*[\r\n]+\s*)*(\d+)\s+(\d+)\s+(\d+)\s", bruto)
    if not cabecalho or int(cabecalho.group(3)) != 255:
        return None
    pixels = bruto[cabecalho.end():]
    if not pixels:
        return None
    media = sum(pixels) / len(pixels)
    variancia = sum((p - media) ** 2 for p in pixels) / len(pixels)
    fracao_escura = sum(p < 230 for p in pixels) / len(pixels)
    # Marcas de corte e textura clara de fundo nao sao conteudo pesquisavel.
    return variancia ** 0.5 > 10 and fracao_escura > 0.005


def pagina_indice_referencias_legivel(texto):
    """Reconhece paginas de indices remissivos formadas por referencias.

    Alguns e-books exportam o indice de textos biblicos como dezenas de
    referencias numericas seguidas do marcador de hyperlink ``[<<]``. Essas
    paginas quase nao possuem palavras corridas e, por isso, a metrica
    linguistica normal lhes atribui nota zero, apesar de estarem perfeitamente
    pesquisaveis. O marcador repetido e a estrutura numerica tornam o caso
    suficientemente especifico para nao aprovar ruido de OCR por engano.
    """
    linhas = [x.strip() for x in texto.splitlines() if x.strip()]
    if len(linhas) < 6 or texto.count("�") / max(1, len(texto)) >= 0.002:
        return False
    marcador = re.compile(r"\[\s*<<\s*\]")
    referencia_link = re.compile(
        r"^[\d\s.,;:()\-\u2013\u2014]+(?:\[\s*<<\s*\]\s*,?\s*)+$")
    linhas_link = sum(
        bool(marcador.search(linha) and referencia_link.fullmatch(linha))
        for linha in linhas)
    if linhas_link >= 8 and linhas_link / len(linhas) >= 0.55:
        return True

    # Outros exportadores mantêm o índice perfeitamente pesquisável, mas não
    # inserem o marcador de hyperlink. Reconhecemos duas estruturas bem
    # específicas: linhas pontilhadas de sumário e referências bíblicas com
    # capítulo/versículo à esquerda e página(s) à direita. Cabeçalhos como
    # ``Gênesis`` e ``OLD TESTAMENT`` são neutros na proporção.
    linhas_pontilhadas = sum(bool(re.search(
        r"\.{3,}\s*\d+[A-Za-z]?\s*$", linha)) for linha in linhas)
    if linhas_pontilhadas >= 4 and linhas_pontilhadas / len(linhas) >= 0.35:
        return True

    referencia_sem_link = re.compile(
        r"^\s*\d{1,3}(?:(?:[:.]\d{1,3})(?:[-–—,]\d{1,3})?"
        r"|\s*[-–—]\s*\d{1,3})?"
        r"(?:\s*[-–—]\s*|\s+)"
        r"\d{1,4}(?:n\d+)?(?:\s*[-–—,]\s*\d{1,4}(?:n\d+)?)*\s*$")
    linhas_referencia = sum(bool(referencia_sem_link.fullmatch(linha))
                            for linha in linhas)
    return (linhas_referencia >= 8
            and linhas_referencia / len(linhas) >= 0.55)


def diagnosticar_ocr(f, paginas=None, progresso=None):
    """Avalia a camada pesquisavel no documento inteiro, sem modificar o PDF.

    O resultado separa ausencia de texto de texto possivelmente ruim. Paginas
    sem texto ficam registradas para uma futura classificacao visual; elas nao
    reprovam sozinhas porque podem ser capa, ilustracao ou pagina em branco.
    """
    paginas = paginas if paginas is not None else paginas_pdftotext(f)
    total_pdf = n_paginas(f)
    if not paginas and total_pdf:
        paginas = [""] * total_pdf
    if total_pdf > len(paginas):
        paginas += [""] * (total_pdf - len(paginas))

    detalhes = []
    pesquisaveis = avaliadas = boas = 0
    qualidades = []
    for numero, texto in enumerate(paginas, 1):
        chars = len(re.sub(r"\s+", "", texto))
        q = qualidade_ocr(texto)
        # Indices, bibliografias e notas em grego/hebraico tem muitos nomes,
        # numeros e abreviacoes. A nota linguistica cai, embora o texto esteja
        # perfeitamente pesquisavel. A estrutura legivel evita esse falso
        # positivo sem aprovar paginas cheias de glifos corrompidos.
        tokens = re.findall(r"[^\W\d_]{3,}", texto, re.UNICODE)
        visiveis = [c for c in texto if not c.isspace()]
        letras = sum(c.isalpha() for c in visiveis)
        limpo = (bool(visiveis) and letras / len(visiveis) >= 0.30
                 and texto.count("�") / max(1, len(texto)) < 0.002)
        linhas = [x.strip() for x in texto.splitlines() if x.strip()]
        linhas_indice = sum(bool(re.search(
            r"(?:\.{3,}|\s{3,})\s*\d+[A-Za-z]?\s*$", x)) for x in linhas)
        parece_sumario = bool(
            re.search(r"(?im)^\s*(?:sum[aá]rio|[ií]ndice)\s*$", texto)
            and linhas_indice >= 5
            and texto.count("�") / max(1, len(texto)) < 0.002)
        # Um sumário curto continua sendo estruturalmente legível. Exigir 25
        # palavras reprovava, por uma única palavra, páginas perfeitas com
        # linhas pontilhadas e números de página (caso Culto e Adoração).
        parece_indice_referencias = pagina_indice_referencias_legivel(texto)
        legivel = (parece_sumario or parece_indice_referencias
                   or (len(tokens) >= 25 and limpo))
        curto_legivel = (chars >= MIN_CHARS_PAGINA and len(tokens) >= 8
                         and len([x for x in texto.splitlines() if x.strip()]) >= 3
                         and limpo)
        if chars >= MIN_CHARS_PAGINA or parece_indice_referencias:
            pesquisaveis += 1
            avaliadas += 1
            qualidades.append(max(q, LIMIAR_OCR_PAGINA)
                               if legivel or curto_legivel else q)
            classe = ("texto_bom" if q >= LIMIAR_OCR_PAGINA
                      or legivel or curto_legivel
                      else "texto_fraco")
            boas += classe == "texto_bom"
        elif chars:
            # Capa, folha de rosto, divisoria e sumario podem ter poucas
            # palavras. A pagina e pesquisavel, mas nao oferece amostra
            # suficiente para medir qualidade linguistica.
            pesquisaveis += 1
            classe = "texto_curto"
        else:
            classe = "sem_texto"
        detalhes.append({"pagina": numero, "caracteres": chars,
                         "qualidade": q, "classe": classe})
        if progresso and (numero == 1 or numero == len(paginas)
                          or numero % 25 == 0):
            progresso("analisando texto", numero, len(paginas), numero)

    total = max(1, len(paginas))
    cobertura_bruta = pesquisaveis / total
    # Paginas em branco devem ser neutras mesmo quando a cobertura bruta ja
    # supera 80%. Antes elas deixavam de ser examinadas e um unico sumario
    # podia reprovar livros curtos que ja tinham OCR de boa qualidade.
    sem_texto = [d for d in detalhes if d["classe"] == "sem_texto"]
    if pesquisaveis and len(sem_texto) <= 100:
        for posicao, detalhe in enumerate(sem_texto, 1):
            tem_conteudo = _pagina_tem_conteudo_visual(f, detalhe["pagina"])
            if tem_conteudo is False:
                detalhe["classe"] = "sem_conteudo_visual"
            if progresso and (posicao == 1 or posicao == len(sem_texto)
                              or posicao % 5 == 0):
                progresso("verificando páginas sem texto", posicao,
                           len(sem_texto), detalhe["pagina"])
    neutras = sum(d["classe"] == "sem_conteudo_visual" for d in detalhes)
    total_avaliavel = max(1, total - neutras)
    cobertura = pesquisaveis / total_avaliavel
    fracao_fraca = ((avaliadas - boas) / avaliadas if avaliadas else 1.0)
    mediana = statistics.median(qualidades) if qualidades else 0.0

    motivos = []
    if cobertura < MIN_COBERTURA_PESQUISAVEL:
        motivos.append(f"cobertura pesquisavel {cobertura:.1%}")
    tolera_unica_fraca = (
        avaliadas >= 10 and avaliadas - boas == 1
        and cobertura >= 0.95 and mediana >= 0.85)
    if fracao_fraca > MAX_FRACAO_TEXTO_FRACO and not tolera_unica_fraca:
        motivos.append(f"texto fraco em {fracao_fraca:.1%} das paginas com texto")
    if mediana < LIMIAR_OCR_PAGINA:
        motivos.append(f"qualidade mediana {mediana:.2f}")

    return {
        "status": "precisa OCR" if motivos else "OCR aprovado",
        "motivos": motivos,
        "paginas": len(paginas),
        "paginas_pesquisaveis": pesquisaveis,
        "paginas_texto_bom": boas,
        "paginas_texto_fraco": [d["pagina"] for d in detalhes
                                  if d["classe"] == "texto_fraco"],
        "paginas_texto_curto": [d["pagina"] for d in detalhes
                                  if d["classe"] == "texto_curto"],
        "paginas_sem_texto": [d["pagina"] for d in detalhes
                                if d["classe"] == "sem_texto"],
        "paginas_sem_conteudo_visual": [d["pagina"] for d in detalhes
                                          if d["classe"] == "sem_conteudo_visual"],
        "paginas_avaliaveis": total_avaliavel,
        "cobertura_pesquisavel": round(cobertura, 4),
        "fracao_texto_fraco": round(fracao_fraca, 4),
        "qualidade_mediana": round(mediana, 2),
        "detalhes": detalhes,
    }


def texto_vision(f, ate=6):
    """Le as primeiras paginas com o Vision, renderizando cada uma.

    E o mesmo motor do app de cartoes, e nas capas ele ganhou do Tesseract
    de longe - onde o Tesseract devolvia "DB \\ | | VIF AA ANS!", o Vision
    devolvia a linha inteira e correta. Faz sentido usar o melhor motor
    tambem nas paginas que decidem o tombo: CIP, creditos e folha de rosto.
    """
    if not lercapa or not lercapa._ocr_vision:
        return ""
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision-ocr")
    if sys.platform != "darwin" or not os.path.exists(helper):
        return ""

    import tempfile, glob as _g
    partes = []
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.join(tmp, "p")
        try:
            subprocess.run(["pdftoppm", "-f", "1", "-l", str(ate), "-r", "300",
                            "-jpeg", f, base], capture_output=True, timeout=600)
        except Exception:
            return ""
        for img in sorted(_g.glob(base + "*.jpg")):
            linhas = lercapa._ocr_vision(img)
            if linhas:
                partes.append("\n".join(linhas))
    return "\n".join(partes)


def paginas_bibliograficas_vision(f, paginas, ate=6):
    """Le somente paginas editoriais visuais que perderam a camada textual.

    Um PDF pode ter OCR excelente no miolo e, ainda assim, guardar folha de
    rosto, copyright e CIP como imagens. A avaliacao global do texto nao deve
    provocar OCR integral nesse caso; basta complementar as paginas iniciais
    curtas, ignorando a capa (que ja possui leitor proprio).
    """
    if not lercapa or not lercapa._ocr_vision:
        return {}
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision-ocr")
    if sys.platform != "darwin" or not os.path.exists(helper):
        return {}

    import tempfile
    resultado = {}
    limite = min(ate, len(paginas))
    candidatos = []
    for numero in range(2, limite + 1):
        caracteres = len(re.sub(r"\s+", "", paginas[numero - 1]))
        if caracteres < 80 and _pagina_tem_conteudo_visual(f, numero) is True:
            candidatos.append(numero)
    if not candidatos:
        return {}

    with tempfile.TemporaryDirectory(prefix="biblio-vision-") as tmp:
        for numero in candidatos:
            base = os.path.join(tmp, f"p-{numero}")
            try:
                subprocess.run(
                    ["pdftoppm", "-f", str(numero), "-l", str(numero),
                     "-r", "300", "-jpeg", "-singlefile", f, base],
                    capture_output=True, timeout=300)
                # Vision continua sendo a primeira opção; se o macOS o
                # recusar momentaneamente, o mesmo leitor cai para Tesseract
                # em vez de perder silenciosamente a ficha catalográfica.
                linhas = lercapa.texto_da_capa(base + ".jpg")
            except Exception:
                linhas = None
            if linhas:
                resultado[numero] = "\n".join(linhas)
    return resultado


def texto_inicio(f, ate=PAGS_COPYRIGHT):
    """Texto das primeiras paginas, pelo melhor motor disponivel.

    A camada de texto do PDF vem primeiro por ser instantanea. So quando
    ela nao existe ou esta ruim e que renderizamos e chamamos o Vision -
    caro, mas e a diferenca entre ter ficha e nao ter.
    """
    t = texto_pdftotext(f, ate)
    if len(t.strip()) > MIN_OCR and qualidade_ocr(t) >= LIMIAR_OCR:
        MOTOR["ultimo"] = "camada do PDF"
        return t
    v = texto_vision(f)
    if len(v.strip()) > len(t.strip()):
        MOTOR["ultimo"] = "Vision"
        return v
    MOTOR["ultimo"] = "camada do PDF (fraca)" if t.strip() else "nenhum"
    return t

def n_paginas(f):
    try:
        s = subprocess.run(["pdfinfo", f], capture_output=True,
                           text=True, timeout=30).stdout
        m = re.search(r"Pages:\s+(\d+)", s)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def pagina_pdf_horizontal(f):
    """Indica se a primeira folha é horizontal pela geometria do PDF."""
    try:
        saida = subprocess.run(
            ["pdfinfo", f], capture_output=True, text=True,
            timeout=30).stdout
        achado = re.search(
            r"Page size:\s*([0-9.]+)\s+x\s+([0-9.]+)\s+pts", saida)
        if not achado:
            return False
        largura, altura = map(float, achado.groups())
        return largura > altura * 1.10
    except Exception:
        return False

def tem_ocr(f):
    """So pergunta se ha camada de texto - por isso nao chama o Vision."""
    return len(texto_pdftotext(f, 5).strip()) > MIN_OCR


def qualidade_ocr(t):
    """0 a 1. Ter texto nao e a mesma coisa que ter texto BOM.

    O tem_ocr() so conta caracteres, entao um PDF com OCR ruim passa como
    se estivesse resolvido - e ninguem repara ate a ficha sair errada.
    Aqui olhamos a proporcao de palavras plausiveis: OCR ruim produz
    "DB \\ | | VIF AA ANS!", muito simbolo e muita palavra de uma letra.
    """
    fichas = re.findall(r"\S+", t)
    if len(fichas) < 40:
        return 0.0

    # Pagina de creditos e cheia de ISBN, CEP, telefone, (c) e simbolo. Se
    # contarmos isso como lixo, todo livro parece mal digitalizado - foi o
    # que aconteceu na primeira versao, que reprovou 11 de 12. Julgamos
    # apenas as fichas que TENTAM ser palavra.
    candidatas = [p for p in fichas
                  if len(p) > 2 and any(c.isalpha() for c in p)
                  and not re.fullmatch(r"[\d\W_]+", p)]
    if len(candidatas) < 20:
        return 0.0

    # Contar letras nao basta: "VIF AA ANS tbe rs" e feito so de letras e
    # passava com nota 1.0. O que separa palavra de ruido e a ESTRUTURA -
    # palavra de verdade tem vogal e nao empilha consoantes sem parar.
    def parece_palavra(p):
        p = p.strip(".,;:()[]«»\"'").lower()
        if len(p) < 3 or sum(c.isalpha() for c in p) / len(p) <= 0.7:
            return False
        if not re.search(r"[aeiouáàâãéêíóôõúü]", p):
            return False
        if re.search(r"[bcdfghjklmnpqrstvwxyz]{5}", p):
            return False
        return True

    boas = sum(1 for p in candidatas if parece_palavra(p))

    # ruido tambem se denuncia pelo excesso de fragmentos de 1-2 letras
    curtas = sum(1 for p in fichas if p.isalpha() and len(p) <= 2)
    penal = max(0.0, curtas / len(fichas) - 0.22)     # ~22% e normal

    return round(max(0.0, boas / len(candidatas) - penal), 2)


def rodar_ocr(f, destino, idioma="por+eng+spa", refazer=False, otimizar=3,
              progresso=None):
    """Cria uma copia com Apple Vision OCR; nunca substitui o PDF recebido.

    --skip-text  : nao mexe em pagina que ja tem texto (o padrao)
    --redo-ocr   : descarta a camada existente e refaz (para OCR ruim)
    """
    if os.path.abspath(f) == os.path.abspath(destino):
        raise ValueError("o destino do OCR nao pode ser o arquivo original")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tmp = destino + ".tmp.pdf"
    modo = "--redo-ocr" if refazer else "--skip-text"
    plugin = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "apple-vision-ocr-plugin.py")
    helper = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "vision-ocr")
    progresso_path = tmp + ".progresso"
    MOTOR["erro_ocr"] = ""
    try:
        if not os.path.isfile(plugin) or not os.access(helper, os.X_OK):
            raise FileNotFoundError("motor Apple Vision nao instalado")
        # O reconhecimento e exclusivamente do Apple Vision. OCRmyPDF apenas
        # monta a camada invisivel e preserva a estrutura do documento.
        comando = ["ocrmypdf", "-l", idioma, "--plugin", plugin,
                   "--output-type", "pdf", modo,
                   "--rotate-pages", "--rotate-pages-threshold", "1",
                   "--optimize", str(otimizar), "--jobs", "2",
                   "--quiet", f, tmp]
        # OCRmyPDF nao permite --deskew junto de --redo-ocr. A rotacao de
        # paginas continua ativa nos dois modos; a correcao fina de inclinacao
        # e usada apenas quando estamos criando uma camada do zero.
        if not refazer:
            comando.insert(comando.index("--optimize"), "--deskew")
        if progresso:
            ambiente = os.environ.copy()
            ambiente["BIBLIO_OCR_PROGRESS_FILE"] = progresso_path
            processo = subprocess.Popen(
                comando, env=ambiente, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            inicio = time.monotonic()
            vistos = set()
            bytes_paginas = 0

            def ler_progresso():
                nonlocal bytes_paginas
                try:
                    linhas = pathlib.Path(progresso_path).read_text(
                        encoding="ascii").splitlines()
                except OSError:
                    return
                alterou = False
                for linha in linhas:
                    try:
                        pagina, tamanho = linha.split("\t", 1)
                        pagina = int(pagina); tamanho = int(tamanho)
                    except (ValueError, TypeError):
                        continue
                    if pagina not in vistos:
                        vistos.add(pagina)
                        bytes_paginas += tamanho
                        alterou = True
                if alterou:
                    progresso(len(vistos), bytes_paginas)

            while processo.poll() is None:
                ler_progresso()
                if time.monotonic() - inicio > 3600:
                    processo.kill()
                    processo.wait()
                    raise subprocess.TimeoutExpired(comando, 3600)
                time.sleep(0.5)
            ler_progresso()
            if processo.returncode:
                raise subprocess.CalledProcessError(processo.returncode,
                                                    comando)
        else:
            subprocess.run(comando, check=True, timeout=3600)
        os.replace(tmp, destino)
        return True
    except Exception as exc:
        MOTOR["erro_ocr"] = str(exc) or exc.__class__.__name__
        if os.path.exists(tmp):
            os.remove(tmp)
        return False
    finally:
        try:
            os.remove(progresso_path)
        except OSError:
            pass


def otimizar_pdf_envio(f, destino, dpi_cor=150, dpi_mono=300,
                       progresso=None):
    """Cria copia compacta para upload, preservando a camada pesquisavel."""
    if os.path.abspath(f) == os.path.abspath(destino):
        raise ValueError("o destino otimizado nao pode substituir a origem")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    tmp = destino + ".tmp.pdf"
    comando = [
        "gs", "-dNOPAUSE", "-dBATCH", "-dSAFER",
        "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.7",
        "-dDetectDuplicateImages=true", "-dCompressFonts=true",
        "-dSubsetFonts=true", "-dDownsampleColorImages=true",
        "-dColorImageDownsampleThreshold=1.0",
        f"-dColorImageResolution={dpi_cor}",
        "-dDownsampleGrayImages=true", "-dGrayImageDownsampleThreshold=1.0",
        f"-dGrayImageResolution={dpi_cor}",
        "-dDownsampleMonoImages=true", "-dMonoImageDownsampleThreshold=1.0",
        f"-dMonoImageResolution={dpi_mono}",
        f"-sOutputFile={tmp}", f,
    ]
    try:
        if progresso:
            processo = subprocess.Popen(
                comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            try:
                for saida in processo.stdout or ():
                    pagina = re.search(r"(?i)\bPage\s+(\d+)\b", saida)
                    if pagina:
                        progresso(int(pagina.group(1)))
                retorno = processo.wait(timeout=1800)
                if retorno:
                    raise subprocess.CalledProcessError(retorno, comando)
            except Exception:
                processo.kill()
                processo.wait()
                raise
        else:
            comando_quieto = comando[:1] + ["-q"] + comando[1:]
            subprocess.run(comando_quieto, check=True, timeout=1800,
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        if n_paginas(f) != n_paginas(tmp) or n_paginas(tmp) == 0:
            raise ValueError("a copia otimizada alterou a quantidade de paginas")
        os.replace(tmp, destino)
        return True
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        return False

def gerar_capa(f, pasta_capas):
    os.makedirs(pasta_capas, exist_ok=True)
    base = os.path.splitext(os.path.basename(f))[0]
    final = os.path.join(pasta_capas, base + ".jpg")
    if os.path.exists(final) and os.path.getsize(final) > 1000:
        return final
    try:
        subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-r", str(DPI_CAPA),
                        "-jpeg", "-singlefile", f,
                        os.path.join(pasta_capas, base)],
                       capture_output=True, timeout=180, check=True)
        return final if os.path.exists(final) else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# ISBN
# ---------------------------------------------------------------------------

def isbn_valido(s):
    d = re.sub(r"[^0-9Xx]", "", s)
    if len(d) == 13 and d.isdigit():
        if not d.startswith(("978", "979")):
            return None
        t = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d[:12]))
        return d if (10 - t % 10) % 10 == int(d[12]) else None
    if len(d) == 10:
        t = sum((10 - i) * (10 if c in "Xx" else int(c)) for i, c in enumerate(d))
        return d if t % 11 == 0 else None
    return None


def isbns_de_codigos_barras(deteccoes):
    """Aceita somente EANs que sejam ISBN-13 válidos (prefixos 978/979)."""
    resultado = []
    vistos = set()
    for item in deteccoes or []:
        valor = item.get("valor", "") if isinstance(item, dict) else str(item)
        normalizado = isbn_valido(valor)
        if (normalizado and len(normalizado) == 13
                and normalizado.startswith(("978", "979"))
                and normalizado not in vistos):
            vistos.add(normalizado)
            resultado.append(normalizado)
    return resultado


def _auxiliar_codigo_barras():
    """Localiza ou compila uma vez o leitor nativo; falha sem travar o lote."""
    pasta = pathlib.Path(__file__).resolve().parent
    fonte = pasta / "vision-barcode.swift"
    binario = pasta / "vision-barcode"
    if not fonte.is_file():
        return None
    if (not binario.is_file()
            or binario.stat().st_mtime < fonte.stat().st_mtime):
        ambiente = os.environ.copy()
        ambiente.setdefault("CLANG_MODULE_CACHE_PATH",
                            "/private/tmp/biblio-clang-cache")
        ambiente.setdefault("SWIFT_MODULE_CACHE_PATH",
                            "/private/tmp/biblio-swift-cache")
        xcode = pathlib.Path("/Applications/Xcode.app/Contents/Developer")
        if xcode.is_dir():
            ambiente.setdefault("DEVELOPER_DIR", str(xcode))
        compilador = ["xcrun", "swiftc"] if shutil.which("xcrun") else ["swiftc"]
        try:
            subprocess.run(compilador + ["-O", str(fonte), "-o", str(binario)],
                           capture_output=True, text=True, timeout=180, check=True,
                           env=ambiente)
        except Exception:
            return None
    return binario


def ler_isbn_codigo_barras(pdf, paginas_total=None):
    """Examina primeiro a contracapa e depois a capa, sem executar OCR."""
    zbar = shutil.which("zbarimg")
    if not zbar and pathlib.Path("/opt/homebrew/bin/zbarimg").is_file():
        zbar = "/opt/homebrew/bin/zbarimg"
    auxiliar = _auxiliar_codigo_barras() if not zbar else None
    total = paginas_total or n_paginas(pdf)
    if not (zbar or auxiliar) or not total:
        return {"isbns": [], "paginas_examinadas": [], "deteccoes": []}
    ordem = list(dict.fromkeys([total, 1]))
    deteccoes = []
    examinadas = []
    with tempfile.TemporaryDirectory(prefix="biblio-barcode-") as td:
        for pagina in ordem:
            base = pathlib.Path(td) / f"pagina-{pagina}"
            try:
                subprocess.run(
                    ["pdftoppm", "-f", str(pagina), "-l", str(pagina),
                     "-r", "300", "-png", "-singlefile", str(pdf), str(base)],
                    capture_output=True, timeout=180, check=True)
                imagem = base.with_suffix(".png")
                encontrados = []
                if zbar:
                    resposta = subprocess.run(
                        [zbar, "--quiet", "--raw", str(imagem)],
                        capture_output=True, text=True, timeout=60, check=False)
                    encontrados = [
                        {"valor": valor.strip(), "tipo": "EAN13",
                         "confianca": 1.0, "motor": "zbar"}
                        for valor in resposta.stdout.splitlines()
                        if valor.strip()
                    ]
                # Vision permanece como alternativa para outras máquinas.
                if not isbns_de_codigos_barras(encontrados) and auxiliar:
                    resposta = subprocess.run(
                        [str(auxiliar), str(imagem)], capture_output=True,
                        text=True, timeout=60, check=True)
                    encontrados.extend(json.loads(resposta.stdout or "[]"))
            except Exception:
                encontrados = []
            examinadas.append(pagina)
            for item in encontrados:
                registro = dict(item)
                registro["pagina"] = pagina
                deteccoes.append(registro)
            isbns = isbns_de_codigos_barras(deteccoes)
            if isbns:
                break
    return {"isbns": isbns_de_codigos_barras(deteccoes),
            "paginas_examinadas": examinadas, "deteccoes": deteccoes}


_SEP_ISBN = r"[ \t\-\u2010\u2011\u2012\u2013]*"
_ISBN13_RE = re.compile(rf"(?<!\d)(97[89](?:{_SEP_ISBN}\d){{10}})(?!\d)")
_ISBN10_RE = re.compile(rf"(?<!\d)((?:\d{_SEP_ISBN}){{9}}[\dXx])(?!\d)")


def _formato_isbn(ctx):
    b = ctx.lower()
    if re.search(r"pdf\b", b):
        return "pdf"
    if re.search(r"epub|mobi|kindle|electr|eletr|ebook", b):
        return "digital"
    if re.search(r"r[uú]stica|brochura|paperback|bolsillo|\btp\b", b):
        return "brochura"
    if re.search(r"tapa dura|capa dura|hardcover|\btela\b", b):
        return "capa dura"
    return ""


def isbn13_equivalente(isbn):
    """Devolve a forma ISBN-13 para comparar a mesma edição em fontes distintas."""
    numero = isbn_valido(isbn)
    if not numero:
        return ""
    if len(numero) == 13:
        return numero
    if len(numero) != 10:
        return ""
    base = "978" + numero[:9]
    soma = sum(int(n) * (1 if i % 2 == 0 else 3)
               for i, n in enumerate(base))
    return base + str((10 - soma % 10) % 10)


def isbns_equivalentes(*valores):
    canonicos = {isbn13_equivalente(v) for v in valores
                 if isbn13_equivalente(v)}
    return len(canonicos) == 1 and bool(canonicos)


def _volume_no_contexto(ctx):
    m = re.search(
        r"(?i)(?:\bv\.?|vol(?:ume|umen)?|tomo)\s*[:.]?\s*([1-9][0-9]?)",
        ctx)
    return m.group(1) if m else ""


def volume_edicao_do_nome(nome):
    """Recupera volume/tomo do arquivo sem confundir ano e número aleatório.

    Coleções digitalizadas aparecem tanto como ``Tomo-7`` quanto como
    ``7-Beacon`` ou ``Beacon-10``. O número só é aceito quando está ancorado
    numa palavra de coleção, evitando transformar qualquer prefixo numérico
    do Scribd em volume bibliográfico.
    """
    base = pathlib.Path(str(nome or "")).stem
    padroes = (
        r"(?i)(?:tomo|vol(?:ume|umen)?|\bv\.?)\s*[-_. ]*([1-9][0-9]?)\b",
        r"(?i)\bbeacon\s*[-_. ]*([1-9][0-9]?)\b",
        r"(?i)^\s*([1-9][0-9]?)\s*[-_. ]+(?:comentario\s+b[ií]blico\s+)?beacon\b",
        r"(?i)^\s*([1-9][0-9]?)\s*[-_. ]+dogm[aá]tica\b",
    )
    for padrao in padroes:
        achado = re.search(padrao, base)
        if achado:
            return achado.group(1)
    return ""


def candidatos_isbn(t):
    """ISBNs validos sem atravessar quebras de linha.

    Primeiro procuramos ISBN-13 e depois ISBN-10 fora dos trechos ja usados.
    Isso evita que o ISBN termine engolindo o primeiro numero da linha
    seguinte, falha que ocultava o ISBN brasileiro do lote de teste.
    """
    out = []
    ocupados = []
    achados = list(_ISBN13_RE.finditer(t))
    ocupados.extend(m.span(1) for m in achados)
    for m in _ISBN10_RE.finditer(t):
        if any(a <= m.start(1) < b or a < m.end(1) <= b for a, b in ocupados):
            continue
        achados.append(m)

    for m in sorted(achados, key=lambda x: x.start(1)):
        n = isbn_valido(m.group(1))
        if not n:
            continue
        linha_ini = t.rfind("\n", 0, m.start(1)) + 1
        linha_fim = t.find("\n", m.end(1))
        if linha_fim < 0:
            linha_fim = len(t)
        linha = " ".join(t[linha_ini:linha_fim].split())
        a, b = max(0, m.start(1)-70), min(len(t), m.end(1)+70)
        ctx = " ".join(t[a:b].replace("\n", " ").split())
        antes = " ".join(t[max(linha_ini, m.start(1)-50):m.start(1)].split())
        depois = " ".join(t[m.end(1):min(linha_fim, m.end(1)+40)].split())
        rot = (antes + " " + depois).strip(" :|")
        out.append({"isbn": n, "rotulo": rot[:80], "ctx": ctx[:180],
                    "linha": linha[:220], "formato": _formato_isbn(linha),
                    "volume": _volume_no_contexto(linha)})
    u, vis = [], set()
    for c in out:
        if c["isbn"] not in vis:
            vis.add(c["isbn"]); u.append(c)
    return u


def isbn_sem_rotulo_tem_contexto_bibliografico(candidato):
    """Aceita ISBN sem a palavra ISBN quando a página parece ficha/creditos.

    Livros reais às vezes imprimem só ``978-...`` ou ``85-...``. O dígito
    verificador sozinho não basta: sequências de sumário também podem fechar
    matematicamente. Exigimos, portanto, que o entorno traga sinais editoriais.
    """
    contexto = " ".join(str(candidato.get(campo, ""))
                        for campo in ("rotulo", "linha", "ctx"))
    if re.search(r"(?i)\b(?:ISBN(?:-1[03])?|EAN)\b", contexto):
        return True
    if candidato.get("credito_edicao") or candidato.get("formato"):
        return True
    sinais = (
        r"(?i)\b(?:copyright|©|copirraite|direitos\s+reservados|"
        r"ficha\s+catalogr[aá]fica|cataloging[\s-]*in[\s-]*publication|"
        r"dados\s+(?:internacionais\s+)?de\s+cataloga[çc][aã]o|"
        r"bibliotec[aá]ria|crb|cdd|cdu|ddc|lcc|"
        r"editora|editorial|publisher|press|publica[çc][õo]es|"
        r"edi[çc][aã]o|edition|edici[óo]n|"
        r"t[íi]tulo|title|autor|author|descri[çc][aã]o|description|"
        r"p[aá]ginas?|pages?|p\.)\b"
    )
    return bool(re.search(sinais, contexto))


def candidatos_isbn_paginas(paginas, numeros_paginas=None):
    out = []
    numeros = (list(numeros_paginas) if numeros_paginas is not None
               else list(range(1, len(paginas) + 1)))
    for numero, texto in zip(numeros, paginas):
        for c in candidatos_isbn(texto):
            c = dict(c)
            c["pagina"] = numero
            c["origem"] = "pagina bibliografica"
            c["credito_edicao"] = bool(re.search(
                r"(?i)\bCopyright\b|[©℗]|Cataloging[\s-]*in[\s-]*Publication|"
                r"Dados\s+(?:Internacionais\s+)?de\s+Cataloga[çc][aã]o|"
                r"Ficha\s+Catalogr[aá]fica", texto))
            out.append(c)
    return out


def selecionar_paginas_bibliograficas(paginas, limite_inicio=PAGS_BIBLIOGRAFICAS,
                                       limite_fim=PAGS_BIBLIOGRAFICAS_FINAIS):
    """Seleciona começo e fim preservando o número real de cada página.

    PDFs derivados de EPUB/Kindle frequentemente põem ``Copyright`` e a CIP
    depois do índice, anúncios e biografia do autor. A seleção das páginas
    finais evita que anos citados no corpo sejam confundidos com publicação.
    """
    total = len(paginas or [])
    indices = list(range(min(total, limite_inicio)))
    inicio_finais = max(len(indices), total - limite_fim)
    indices.extend(range(inicio_finais, total))
    return [(indice + 1, normalizar_rotulos_numeros_ocr(paginas[indice]))
            for indice in indices]


def isbn_confirmado_na_edicao(isbn, candidatos, volume_edicao=""):
    """Distingue ISBN impresso no volume de mera pista no nome do arquivo."""
    alvo = isbn13_equivalente(isbn)
    if not alvo:
        return False
    candidatos = candidatos or []
    for candidato in candidatos:
        if isbn13_equivalente(candidato.get("isbn", "")) != alvo:
            continue
        origem = candidato.get("origem")
        if origem in ("codigo de barras", "arquivo OPF"):
            return True
        if origem != "pagina bibliografica":
            continue
        contexto = " ".join(str(candidato.get(campo, ""))
                            for campo in ("rotulo", "linha", "ctx"))
        explicitamente_rotulado = isbn_sem_rotulo_tem_contexto_bibliografico(
            candidato)
        # Uma sequência que por acaso fecha o dígito verificador não é prova
        # bibliográfica. Datas e paginação de sumários já produziram ISBNs
        # falsos perfeitamente válidos matematicamente.
        if (not candidato.get("credito_edicao")
                and not explicitamente_rotulado
                and not candidato.get("volume")
                and not candidato.get("formato")):
            continue
        pagina = candidato.get("pagina")
        mesma_pagina = {
            isbn13_equivalente(c.get("isbn", ""))
            for c in candidatos
            if c.get("origem") == "pagina bibliografica"
            and c.get("pagina") == pagina
            and isbn13_equivalente(c.get("isbn", ""))
        }
        # Um ISBN isolado na página de créditos identifica a edição. Já uma
        # lista de ISBNs da coleção só confirma o item ligado ao tomo atual.
        if len(mesma_pagina) <= 1:
            return True
        if candidato.get("credito_edicao"):
            return True
        if (volume_edicao and candidato.get("volume")
                and str(candidato["volume"]) == str(volume_edicao)):
            return True
    return False

def _prefere13(grupo):
    """Preferencialmente o de 13 - mas nao exclusivamente."""
    t13 = [c for c in grupo if len(c["isbn"]) == 13]
    return (t13 or grupo)[0]

def escolher_isbn(cands, nome, ano):
    """Cascata: o que o copyright identifica > regra da brochura > alternativa."""
    if not cands:
        if ano and ano < ANO_ISBN:
            return "", f"sem ISBN - obra de {ano}, anterior ao padrao (1970)"
        return "", "sem ISBN - nao localizado"

    # Código de barras é uma chave de edição, não uma inferência textual.
    # Quando válido, inicia a pesquisa bibliográfica e vence outras leituras.
    barras = [c for c in cands if c.get("origem") == "codigo de barras"]
    if barras:
        return _prefere13(barras)["isbn"], "código de barras da capa/contracapa"

    opf = [c for c in cands if c.get("origem") == "arquivo OPF"]
    if opf:
        return _prefere13(opf)["isbn"], "ISBN estruturado do arquivo OPF"

    # No texto do PDF, aceite somente códigos ancorados bibliograficamente.
    # Números vindos diretamente de ``candidatos_isbn`` (sem origem) são
    # mantidos para compatibilidade dos extratores já contextualizados; a
    # restrição incide sobre a varredura ampla de páginas bibliográficas.
    def _candidato_textual_ancorado(candidato):
        if candidato.get("origem") != "pagina bibliografica":
            return True
        contexto = " ".join(str(candidato.get(campo, ""))
                            for campo in ("rotulo", "linha", "ctx"))
        return bool(
            candidato.get("credito_edicao")
            or candidato.get("volume")
            or candidato.get("formato")
            or isbn_sem_rotulo_tem_contexto_bibliografico(candidato)
        )

    ancorados = [c for c in cands if _candidato_textual_ancorado(c)]
    if not ancorados:
        return "", "sem ISBN - sequencias numericas sem rotulo bibliografico"
    cands = ancorados

    # E-books frequentemente anunciam outros títulos antes da ficha da obra.
    # Um ISBN presente na página de copyright/CIP vence esses códigos.
    creditos_edicao = [c for c in cands if c.get("credito_edicao")]
    if creditos_edicao:
        cands = creditos_edicao

    v = volume_edicao_do_nome(nome)
    if v:
        g = [c for c in cands if c.get("volume") == v or re.search(
             r"(?:v\.?|vol(?:ume|umen)?|tomo)\s*[:.]?\s*" + v + r"\b",
             c.get("linha", ""), re.I)]
        if g:
            return _prefere13(g)["isbn"], f"copyright identifica volume {v}"

    imp = [c for c in cands if c.get("formato") not in ("pdf", "digital")]
    g = [c for c in (imp or cands) if c.get("formato") == "brochura"]
    if g:
        return _prefere13(g)["isbn"], "regra: brochura"

    pool = imp or cands
    esc = _prefere13(pool)
    nota = ""
    if len(esc["isbn"]) != 13 and ano and ano < ANO_ISBN13:
        nota = f" (so ISBN-10; obra de {ano}, anterior a 2007)"
    return esc["isbn"], ("alternativa: impresso" if imp else "alternativa: unico") + nota


# ---------------------------------------------------------------------------
# PAGINA DE COPYRIGHT
# ---------------------------------------------------------------------------

def _campo(t, padroes, limite=90):
    for p in padroes:
        m = re.search(p, t, re.I)
        if m:
            v = " ".join(m.group(1).split()).strip(" .,:;-–")

            # A busca e case-insensitive, e isso ANULA as guardas de
            # maiuscula escritas nos padroes: com re.I, [A-ZÁ-Ú] casa
            # minuscula tambem. O efeito real: "...e agora publicado por
            # muitos cristaos protestantes batizados..." era aceito como
            # editora, porque a guarda [A-ZÁ-Ú] nao guardava nada.
            #
            # Quando o padrao exige inicial maiuscula, cobramos de fato.
            if "[A-ZÁ-Ú]" in p and v[:1].islower():
                continue
            # Preposicao solta no fim e sempre resto da frase seguinte, nunca
            # parte do nome: "Center for Theological Research em" veio de
            # "...Research em 2006", com a quebra de linha antes do ano.
            v = re.sub(r"(?i)\s+(?:em|no|na|de|do|da|para|por|com|e)\s*$", "", v)
            if 2 < len(v) < limite:
                return v
    return ""

def ano_publicacao(t):
    """Ano ancorado em copyright/publicacao; nunca um ano solto.

    Anos soltos incluem nascimento e falecimento do autor, datas de versoes
    biblicas e historico de reimpressoes. Sem rotulo, e mais seguro deixar o
    campo para revisao do que inventar uma data plausivel.
    """
    linhas = t.splitlines()
    candidatos = []
    for i, linha in enumerate(linhas):
        contexto = " ".join(linhas[max(0, i - 1):min(len(linhas), i + 2)])
        if not re.search(r"(?i)©|copyright|publicad|publica[çc][aã]o|published|publication|"
                         r"edi[çc][ãa]o|edici[óo]n|edition|impresi[óo]n", contexto):
            continue
        # Datas de versoes biblicas, ilustracoes e marcas nao datam o livro.
        if re.search(r"(?i)biblia|bible|esv|niv\b|nvi\b|reina.?valera|"
                     r"escrituras|scripture|ilustra|imagen de portada|"
                     r"cover (?:image|design)|marca registrada|\bcf\.|\bpp?\.|"
                     r"refer[êe]ncias? bibliogr[áa]ficas?|"
                     r"first\s+appeared|receiving\s+notice\s+from\s+the\s+publisher",
                     contexto):
            continue
        for achado in re.finditer(r"\b((?:1[6-9]|20)\d{2})\b", contexto):
            # Em fichas CIP, "Payne, Tony, 1962-" e data de nascimento,
            # mesmo que a linha vizinha diga "Catalogacao na publicacao".
            entorno = contexto[max(0, achado.start() - 3):achado.end() + 2]
            if re.search(r",\s*\d{4}\s*[-–]", entorno):
                continue
            ano = int(achado.group(1))
            if 1500 <= ano <= datetime.now().year:
                candidatos.append(ano)
        if candidatos:
            # A primeira declaracao editorial e normalmente a desta obra;
            # listas posteriores costumam ser creditos de citacoes.
            return candidatos[0]
    return None


def ano_romano_editorial(t):
    """Converte ano romano somente quando ancorado em copyright.

    A restricao ao contexto editorial evita interpretar numeracao de capitulos
    ou paginas preliminares como data de publicacao.
    """
    valores = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100,
               "D": 500, "M": 1000}
    for m in re.finditer(r"(?i)(?:copyright|©)\s+([MDCLXVI]{6,12})\b", t):
        romano = m.group(1).upper()
        total = anterior = 0
        for letra in reversed(romano):
            valor = valores[letra]
            total += -valor if valor < anterior else valor
            anterior = max(anterior, valor)
        if 1500 <= total <= datetime.now().year:
            return total
    return None


def ano_desta_edicao(t):
    """Ano ligado a esta edicao, antes dos creditos de Biblia/imagens."""
    for p in (
        r"Copyright\s+da\s+tradu[çc][ãa]o\s*©[^\n]{0,100}?((?:19|20)\d{2})",
        r"(?:Primeira|Primera|First|Premi[eè]re)\s+Edi[çc][ãa]o\s*[:–—-]?\s*((?:19|20)\d{2})",
        r"\d{1,2}\s*[ªºo.]?\s*edi[çc][ãa]o\s*[–—:-]\s*((?:19|20)\d{2})",
        r"(?:Primeira|1\s*[ªao])\s+edi[çc][ãa]o\s+em\s+portugu[eêé]s[^\d]{0,20}((?:19|20)\d{2})",
        r"Publica[çc][ãa]o\s+no\s+formato\s+e-?Book[^\d]{0,30}((?:19|20)\d{2})",
        r"Edici[óo]n en castellano[^\n©]{0,120}©\s*((?:19|20)\d{2})",
        r"Edi[çc][ãa]o em portugu[ês][^\n©]{0,120}©\s*((?:19|20)\d{2})",
        r"[ÉE]dition fran[çc]aise[^\n©]{0,120}©\s*((?:19|20)\d{2})",
        r"(?:Primeira|Primera|First|Première)\s+(?:impress[ãa]o|impresi[óo]n|printing)\s*"
        r"((?:19|20)\d{2})",
        r"Ebook\s+edi(?:tion|ci[óo]n|ção)[^\d]{0,20}((?:19|20)\d{2})",
    ):
        m = re.search(p, t, re.I)
        if m:
            return int(m.group(1))

    # O ultimo copyright antes do primeiro ISBN costuma ser o da edicao
    # em maos; os copyrights de versoes biblicas aparecem depois.
    pos_isbn = re.search(r"\bISBN\b", t, re.I)
    if not pos_isbn:
        return None
    antes = t[:pos_isbn.start()]
    linhas = antes.splitlines()
    anos = []
    for i, linha in enumerate(linhas):
        contexto = " ".join(linhas[max(0, i - 1):min(len(linhas), i + 2)])
        if re.search(r"(?i)biblia|bible|esv|niv\b|nvi\b|reina.?valera|"
                     r"escrituras|scripture|ilustra|boceto|imagen de portada|"
                     r"cover (?:image|design)|marca registrada", contexto):
            continue
        anos.extend(int(a) for a in re.findall(
            r"(?:©|copyright)\s*((?:19|20)\d{2})", linha, re.I))
    return anos[-1] if anos else None


def edicao_catalografica(edicao_cip="", edicao_copyright=""):
    """Declara a presuncao operacional quando a copia nao informa edicao.

    A marca ``(presumida)`` impede que a convencao seja confundida com um
    dado extraido do PDF ou confirmado por uma fonte externa.
    """
    return (str(edicao_cip or "").strip()
            or str(edicao_copyright or "").strip()
            or "1ª edição (presumida)")

def idioma_do_texto(t):
    b = t.lower()
    d = {
        "por": len(re.findall(r"\b(não|são|também|português|edição|tradução|"
                              r"direitos|para|uma|que|com|por|dos|das)\b", b)),
        "spa": len(re.findall(r"\b(edición|traducción|derechos|reservados|español|"
                              r"para|una|que|con|por|los|las|del)\b", b)),
        "fre": len(re.findall(r"\b(tous droits|traduction|français|édition|"
                              r"pour|une|dans|avec|des|les|du|par)\b", b)),
        "eng": len(re.findall(r"\b(all rights reserved|published by|translated by|"
                              r"the|and|with|for|from|this)\b", b)),
    }
    top = max(d, key=d.get)
    return top if d[top] > 0 else ""

NOME_LINGUA = {"por": "Português", "spa": "Espanhol", "fre": "Francês",
               "eng": "Inglês", "": ""}
IDIOMA_OCR = {"por": "por", "spa": "spa", "fre": "fra", "eng": "eng", "": "por"}
NOME_LINGUA_PADRAO = {
    "portugues": "Português", "português": "Português",
    "ingles": "Inglês", "inglês": "Inglês",
    "espanhol": "Espanhol", "castelhano": "Espanhol",
    "frances": "Francês", "francês": "Francês",
    "alemao": "Alemão", "alemão": "Alemão",
}


def normalizar_nome_lingua(valor):
    texto = " ".join(str(valor or "").split())
    return NOME_LINGUA_PADRAO.get(texto.lower(), texto)

# Palavras que denunciam pessoa juridica. O copyright costuma pertencer a
# editora ou a uma sociedade, nao ao autor - "©2003 por la Sociedad de
# Traduccion Reformada Holandesa" nao pode virar nome de autor.
ORGANIZACAO = re.compile(
    r"editor|public|press|books?|sociedad|sociedade|society|ministr|"
    r"inc\.?$|ltda|s\.a\.|associa|funda|igreja|church|casa|grupo|"
    r"crossway|portavoz|baker|zondervan|kregel|cook|holman|thomas nelson",
    re.I)

def autor_do_copyright(t):
    """Nome que aparece depois de '© ANO por NOME'.

    So aceita o que parece nome de pessoa: 2 a 4 palavras capitalizadas,
    sem termos de pessoa juridica. Devolve ('', motivo) quando nao ha
    certeza - preferimos campo vazio a autor errado no acervo.
    """
    achados = []
    for m in re.finditer(
            r"(?:©|copyright)\s*(?:\d{4}\s*(?:,\s*\d{4}\s*)*)?"
            r"(?:por|by|par|de)\s+([A-ZÁ-Ú][^\n©,;]{2,45})", t, re.I):
        cand = " ".join(m.group(1).split()).strip(" .,;:")
        cand = re.sub(r"\s+(y|e|and|et)\s+publicado.*$", "", cand, flags=re.I)
        if ORGANIZACAO.search(cand):
            continue
        p = cand.split()
        if not (2 <= len(p) <= 4):
            continue
        if not all(re.match(r"^[A-ZÁ-Ú][\wá-ú'.-]*$", x) or x.lower() in
                   ("de", "del", "da", "van", "von", "jr.", "jr")
                   for x in p):
            continue
        achados.append(cand)
    if not achados:
        return "", "copyright sem nome de pessoa"
    nome = achados[0]
    p = [x for x in nome.split() if x.lower() not in ("jr.", "jr")]
    sufixo = " Jr." if nome.lower().endswith(("jr.", "jr")) else ""
    return f"{p[-1]}{sufixo}, {' '.join(p[:-1])}", "copyright"


def ler_copyright(t):
    """Extrai o que a pagina de creditos declara sobre ESTA edicao."""
    d = {
        "titulo_original": _campo(t, [
            r"T[íi]tulo del original[:\s]*([^\n©]{3,80})",
            r"T[íi]tulo original[:\s]*([^\n©]{3,80})",
            r"Titre original[:\s]*([^\n©]{3,80})",
            r"Originally published (?:in English )?as[:\s]*([^\n©]{3,80})"]),
        "titulo_edicao": _campo(t, [
            r"Edici[óo]n en castellano[:\s]*([^\n©]{3,80})",
            r"Edi[çc][ãa]o em portugu[êe]s[:\s]*([^\n©]{3,80})",
            r"[ÉE]dition fran[çc]aise[:\s]*([^\n©]{3,80})"]),
        "editora": _campo(t, [
            r"Copyright\s*[©O0]\s*(?:19|20)\d{2}\s+"
            r"((?:Editora|Edi[çc][õo]es|Publica[çc][õo]es|Impacto)\s+[^\n©]{0,65})",
            r"Copyright\s+da\s+tradu[çc][ãa]o\s*©\s*"
            r"((?:Editora|Edi[çc][õo]es|Publica[çc][õo]es)\s+[^\n©]{2,65}?)\s+(?:19|20)\d{2}",
            r"EDICI[ÓO]N\s+CONJUNTA\s+DE[:\s]+([^\n]{3,75})",
            r"Edici[óo]n en castellano[^\n©]*©\s*\d{4}\s+por\s+([A-ZÁ-Ú][^\n,\.]{2,45})",
            r"Edi[çc][ãa]o em portugu[ês][^\n©]*©\s*\d{4}\s+por\s+([A-ZÁ-Ú][^\n,\.]{2,45})",
            r"[ÉE]dition fran[çc]aise[^\n©]*©\s*\d{4}\s+(?:par|de)\s+([A-ZÁ-Ú][^\n,\.]{2,45})",
            r"(?:Publicado(?:\s+no\s+Brasil)?\s+por|Published by|Publi[ée] par)[:\s]+([A-ZÁ-Ú][^\n,\.]{2,75})",
            r"Todos\s+os\s+direitos[^\n]{0,45}?reservados\s+por\s+([A-ZÁ-Ú][^\n,\.]{2,75})",
            r"Todos\s+os\s+direitos\s+autorais\s+foram\s+cedidos\s+a\s+([A-ZÁ-Ú][^\n,\.]{2,75})",
            r"ISBN[^\n]{5,40}\n\s*((?:Editorial|Editora)\s+[A-ZÁ-Ú][^\n,\.]{2,45})",
            r"ISBN[^\n]{5,40}\n\s*([A-Z][A-Za-z0-9&'’. -]{2,60})\s*\n\s*(?:©|Copyright)",
            r"Copyright\s*©\s*\d{4}[^\n]*\n\s*(Crossway|Baker Academic|"
            r"Editorial Portavoz|Editorial Bautista Independiente)",

            # --- ULTIMAS da lista, de proposito -------------------------
            # Sao formas genericas: precisam ceder para as especificas
            # acima. "Edicao publicada pela Kregel" e a editora do
            # ORIGINAL; quando existe "Copyright da traducao © Editora
            # Proclamacao", e esta que vale. Colocar as genericas na
            # frente invertia essa precedencia.

            # o selo sozinho numa linha - a forma mais comum no livro
            # brasileiro. "O Espirito das Disciplinas" trazia apenas
            # "Editora Danprewan" e parou em revisao por falta de editora.
            # O \b evita capturar "Editoracao:", que e credito de
            # diagramacao e apareceu em outro livro do mesmo lote.
            r"(?m)^[ \t]*((?:Editora|Editorial|Edi[çc][õo]es|Ediciones|"
            r"Publica[çc][õo]es|Casa Publicadora)\b[^\n©:]{2,55})[ \t]*$",

            # "publicado pelo Center for Theological Research em 2006"
            #
            # ANCORADO NO INICIO DA LINHA, de proposito. Sem a ancora o
            # padrao casava no meio de frase - "...e agora publicado por
            # muitos cristaos protestantes batizados..." virava editora.
            # Credito editorial ocupa a linha; prosa nao.
            r"(?m)^\s*publicad[oa]\s+(?:pel[oa]|por)\s+([A-ZÁ-Ú][^\n,\.©]{3,70})",
            ], 80),
        "tradutor": _campo(t, [
            r"Tradu(?:c|ç)(?:i[óo]n|[ãa]o)[:\s]*(?:por\s+)?([A-ZÁ-Ú][^\n©]{3,50})",
            r"Traduit par[:\s]*([A-ZÁ-Ú][^\n©]{3,50})",
            r"Translated by[:\s]*([A-ZÁ-Ú][^\n©]{3,50})"], 60),
        "cidade": _campo(t, [
            r"\b(Grand Rapids|Wheaton|Nashville|S[ãa]o Paulo|Rio de Janeiro|"
            r"Miami|Barcelona|Madrid|Curitiba|Bel[ée]m|Viladecavalls)\b"], 40),
        "edicao": _campo(t, [
            r"\b((?:[1-9]|[12]\d|30)[ªa]?\s*(?:edici[óo]n|edi[çc][ãa]o|edition|[ée]dition))"], 30),
    }
    d["editora"] = re.sub(
        r"(?i)\s+(?:una|uma|a)\s+(?:divisi[óo]n|divisão|division)\b.*$|"
        r"\s+una$|"
        r"\s+(?:PO\s+Box|\d{3,}\s+\w+\s+(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?)).*$",
        "", d["editora"]).strip()
    # "tradução aramaica (Targum)" descreve uma versão do texto, não
    # uma pessoa responsável pela tradução. Campo duvidoso deve ficar vazio.
    tradutor = d.get("tradutor", "").strip(" ,.;:")
    partes = tradutor.split()
    conectores = {"de", "da", "do", "das", "dos", "del", "van", "von"}
    if (not 2 <= len(partes) <= 6 or "(" in tradutor or ")" in tradutor
            or not all(p.lower().strip(".,") in conectores
                       or re.match(r"^[A-ZÀ-Ü][\wÀ-ÿ'.-]*,?$", p)
                       for p in partes)):
        d["tradutor"] = ""
    else:
        d["tradutor"] = tradutor
    return d


def ler_ficha_tecnica_rotulada_paginas(paginas):
    """Lê páginas técnicas com rótulos explícitos.

    Alguns livros antigos em inglês, especialmente cópias de bibliotecas
    digitais, não trazem uma CIP formal. Em vez disso, a segunda página pode
    declarar campos como ``Title:``, ``Author(s):`` e ``Publisher:``. Esses
    rótulos são mais confiáveis que a capa OCRizada e não devem ficar de fora
    apenas porque o cabeçalho "Cataloging in Publication" não existe.
    """
    rotulos = {
        "title": "titulo",
        "título": "titulo",
        "titulo": "titulo",
        "author": "autor",
        "authors": "autor",
        "author(s)": "autor",
        "author s": "autor",
        "autor": "autor",
        "autores": "autor",
        "publisher": "editora",
        "published by": "editora",
        "editora": "editora",
        "publicado por": "editora",
        "url": "url",
        "ccel subjects": "assuntos",
        "subjects": "assuntos",
        "assuntos": "assuntos",
        "lc call no": "classificacao_original",
        "lc call no.": "classificacao_original",
        "lc call number": "classificacao_original",
        "date published": "ano",
        "publication date": "ano",
        "date created": "data_criacao_digital",
    }
    for numero, texto in enumerate((paginas or [])[:12], 1):
        valores = {}
        linhas = [" ".join(linha.split()).strip()
                  for linha in str(texto or "").splitlines()]
        linhas = [linha for linha in linhas if linha]

        def guardar_rotulo_valor(rotulo_bruto, valor_bruto):
            rotulo = identificar.normalizar(rotulo_bruto)
            rotulo = rotulo.replace(" ", " ").strip()
            campo = rotulos.get(rotulo)
            if not campo:
                return
            valor = " ".join(str(valor_bruto or "").split()).strip(" .,:;")
            if valor:
                valores[campo] = valor

        for linha in linhas:
            m = re.match(
                r"(?i)^([A-Za-zÀ-ÿ() .]{2,28})\s*:\s*(.{1,220})$",
                linha)
            if not m:
                continue
            guardar_rotulo_valor(m.group(1), m.group(2))

        # Em PDFs gerados por bibliotecas digitais, o pdftotext pode separar
        # uma tabela em duas colunas verticais:
        #   Title:
        #   URL:
        #   Author(s):
        #
        #   Training of the Twelve
        #   http://...
        #   Bruce, A.B.
        # Esse caso parecia perfeito na tela, mas a regra "rótulo: valor"
        # não o enxergava. Pareamos a sequência de rótulos com a sequência
        # de valores imediatamente seguinte.
        for i, linha in enumerate(linhas):
            if not re.match(r"(?i)^[A-Za-zÀ-ÿ() .]{2,28}:\s*$", linha):
                continue
            rotulos_bloco = []
            j = i
            while j < len(linhas):
                mrot = re.match(r"(?i)^([A-Za-zÀ-ÿ() .]{2,28}):\s*$",
                                linhas[j])
                if not mrot:
                    break
                if identificar.normalizar(mrot.group(1)) not in rotulos:
                    break
                rotulos_bloco.append(mrot.group(1))
                j += 1
            if len(rotulos_bloco) < 2:
                continue
            valores_bloco = []
            k = j
            while k < len(linhas) and len(valores_bloco) < len(rotulos_bloco):
                if re.match(r"(?i)^[A-Za-zÀ-ÿ() .]{2,28}:\s*$", linhas[k]):
                    break
                valores_bloco.append(linhas[k])
                k += 1
            if len(valores_bloco) >= min(3, len(rotulos_bloco)):
                for rotulo, valor in zip(rotulos_bloco, valores_bloco):
                    guardar_rotulo_valor(rotulo, valor)
                break
        if not valores:
            continue

        d = {
            "pagina_cip": numero,
            "formato_cip": "ficha técnica rotulada",
        }
        titulo = valores.get("titulo", "")
        if titulo_bibliograficamente_plausivel(titulo):
            d["titulo"] = titulo
        autor = valores.get("autor", "")
        if autor:
            autor = re.split(r";|\s+\|\s+|\s+and\s+", autor, maxsplit=1,
                             flags=re.I)[0]
            autor = re.sub(r"\bet\s+al\.?$", "", autor, flags=re.I)
            autor = re.sub(r"\b([A-Z])\.([A-Z])\.", r"\1. \2.", autor)
            autor = autor.strip(" .,:;")
            if autor_bibliograficamente_plausivel(autor):
                d["autor"] = sobrenome_virgula(autor)
        editora = valores.get("editora", "")
        if editora:
            # Ex.: "Grand Rapids, MI: Christian Classics Ethereal Library"
            # A parte antes dos dois-pontos é local; a parte depois é editora.
            m_pub = re.match(r"^([^:]{2,80})\s*:\s*(.{2,120})$", editora)
            if m_pub:
                cidade = re.sub(r",\s*[A-Z]{2}\b.*$", "",
                                m_pub.group(1)).strip(" .,:;")
                editora = m_pub.group(2).strip(" .,:;")
                if cidade:
                    d["cidade"] = cidade
            editora = limpar_editora_bibliografica(editora)
            if editora_bibliograficamente_plausivel(editora):
                d["editora"] = editora
        if valores.get("assuntos"):
            assuntos = re.sub(r"(?i)\blcsh\s*:\s*", "", valores["assuntos"])
            d["assuntos"] = "; ".join(
                p.strip(" .,:;") for p in re.split(r";|\|", assuntos)
                if p.strip(" .,:;"))[:200]
        if valores.get("classificacao_original"):
            d["classificacao_original"] = valores["classificacao_original"]
        if valores.get("url"):
            d["url_fonte"] = valores["url"]
        if valores.get("data_criacao_digital"):
            d["data_criacao_digital"] = valores["data_criacao_digital"]
        if valores.get("ano"):
            mano = re.search(r"\b((?:1[5-9]|20)\d{2})\b", valores["ano"])
            if mano:
                d["ano"] = mano.group(1)

        sinais = sum(bool(d.get(campo)) for campo in (
            "titulo", "autor", "editora", "cidade", "assuntos",
            "classificacao_original", "url_fonte"))
        if sinais >= 3 and (d.get("titulo") or d.get("autor")):
            return d
    return {}


def copyright_parece_da_edicao_original(cp):
    """Indica tradução quando copyright descreve original, não a edição local."""
    if not isinstance(cp, dict):
        return False
    texto = json.dumps(cp, ensure_ascii=False)
    return bool(
        cp.get("titulo_original")
        or cp.get("tradutor")
        or re.search(
            r"(?i)\b(?:original(?:ly)?\s+published|t[íi]tulo\s+original|"
            r"t[íi]tulo\s+del\s+original|tradu(?:c|ç)(?:i[óo]n|[ãa]o)|"
            r"translated\s+by|edici[óo]n\s+en\s+castellano|"
            r"edi[çc][ãa]o\s+em\s+portugu[êe]s|[ée]dition\s+fran[çc]aise)\b",
            texto))


def _titulo_documental_do_inicio(paginas):
    """Recupera o cabeçalho real antes que parágrafos virem título.

    Materiais de pesquisa convertidos de Word normalmente não possuem CIP,
    mas conservam um título muito melhor na primeira página. A extração é
    deliberadamente restrita às primeiras linhas e rejeita seções genéricas.
    """
    if not paginas:
        return ""
    linhas = [" ".join(x.split()).strip(" \t-|•")
              for x in paginas[0].splitlines()]
    linhas = [x for x in linhas if x]
    bloco = "\n".join(linhas[:8])
    estudo = re.search(
        r"(?is)^\s*(?:ESTUDO\s*:\s*)?(.{5,150}?)\s*[\u2013\u2014-]\s*"
        r"Por\s+(?:Pr\.?|Rev\.?)?\s*"
        r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'.\s-]{3,90}?)\s*"
        r"(?:Publicado\s+em|$)", bloco)
    if estudo:
        return " ".join(estudo.group(1).split()).strip(" .,:;-")

    ignorar = re.compile(
        r"(?i)^(?:introdu[çc][aã]o|apresenta[çc][aã]o|pref[aá]cio|sum[aá]rio|"
        r"cap[ií]tulo\s+\d+|fonte\s*:|publicado\s+em|p[aá]gina\s*\|?\s*\d+)$")
    candidatas = []
    for posicao, linha in enumerate(linhas[:16]):
        if (ignorar.match(linha) or re.fullmatch(r"(?:19|20)\d{2}", linha)
                or re.match(r"(?i)^\d{1,2}\s+de\s+\w+\s+de\s+\d{4}$", linha)
                or re.search(r"https?://|www\.", linha, re.I)):
            continue
        linha = re.sub(r"(?i)^ESTUDO\s*:\s*", "", linha).strip()
        linha = re.split(r"\s+[\u2013\u2014-]\s+Por\s+(?:Pr\.?|Rev\.?)?\s+",
                         linha, maxsplit=1, flags=re.I)[0].strip()
        palavras = linha.split()
        letras = [c for c in linha if c.isalpha()]
        if not (2 <= len(palavras) <= 22 and 5 <= len(linha) <= 180
                and letras):
            continue
        proporcao_maiusculas = sum(c.isupper() for c in letras) / len(letras)
        if posicao <= 5 and (proporcao_maiusculas >= 0.55
                             or linha[:1].isupper()
                             or (posicao <= 2 and re.match(r"^\d+\s+\S+", linha))):
            candidatas.append((posicao, linha, proporcao_maiusculas))
    if not candidatas:
        return ""
    posicao, titulo, _ = candidatas[0]
    # Títulos quebrados em duas linhas são comuns na exportação do Word.
    seguinte = next((x for p, x, _m in candidatas
                     if p == posicao + 1), "")
    if (seguinte and len(titulo) + len(seguinte) <= 180
            and not titulo.endswith((".", ":", ";", "?", "!"))
            and (re.search(r"(?i)\bParte\b", seguinte)
                 or re.search(r"(?i)\b(?:de|da|do|das|dos|e)\s*$", titulo))):
        titulo = f"{titulo} {seguinte}"
    return titulo.strip(" .,:;-")


def _autor_documental_explicito(paginas):
    """Aceita somente autoria acompanhada por rótulo ou byline inequívoca."""
    if not paginas:
        return ""
    bordas = "\n".join(paginas[:3] + paginas[-3:])
    cabecalho = "\n".join(" ".join(x.split())
                           for x in paginas[0].splitlines()[:10])
    estudo = re.search(
        r"(?is)(?:ESTUDO\s*:\s*)?.{5,150}?\s*[\u2013\u2014-]\s*Por\s+"
        r"(?:Pr\.?|Rev\.?|Dr\.?)?\s*"
        r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'.\s-]{3,90}?)\s*Publicado\s+em",
        cabecalho)
    if estudo:
        nome = " ".join(estudo.group(1).split()).strip(" .,:;-")
        if autor_bibliograficamente_plausivel(nome):
            return sobrenome_virgula(nome)
    direitos = re.search(
        r"(?is)todos\s+os\s+direitos.{0,180}?para\s+"
        r"([A-ZÀ-Ü][A-ZÀ-Ü\s]{5,90})", bordas)
    if direitos:
        nome = " ".join(direitos.group(1).split()).strip(" .,:;-").title()
        if autor_bibliograficamente_plausivel(nome):
            return sobrenome_virgula(nome)
    padroes = [
        r"(?im)^\s*AUTOR\s*:\s*(?:Pr\.?|Rev\.?|Dr\.?)?\s*([^\n|]{3,90})$",
        r"(?im)^\s*(?:ESTUDO\s*:\s*)?.{5,150}?\s*[\u2013\u2014-]\s*Por\s+"
        r"(?:Pr\.?|Rev\.?|Dr\.?)?\s*([^\n|]{3,90})$",
        r"(?im)^\s*(?:Pr\.?|Rev\.?|Dr\.?)\s+"
        r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+(?:\s+[A-ZÀ-Ü]"
        r"[A-Za-zÀ-ÿ'.-]+){1,5})\s*$",
    ]
    for padrao in padroes:
        m = re.search(padrao, bordas)
        if not m:
            continue
        nome = " ".join(m.group(1).split()).strip(" .,:;-")
        nome = re.sub(r"(?i)\s+Publicado\s+em.*$", "", nome).strip()
        if autor_bibliograficamente_plausivel(nome):
            return sobrenome_virgula(nome)
    return ""


def metadados_documentais_genericos(paginas, metadados=None,
                                     nome="", origem_word=False):
    """Extrai metadados de estudos, apostilas e documentos sem ficha.

    A ausência de autor não cria um nome fictício. A procedência fica
    registrada separadamente e determina se o item pode seguir sozinho ou
    precisa de conferência humana.
    """
    metadados = metadados or {}
    inicio = "\n".join(paginas[:3])
    bordas = "\n".join(paginas[:3] + paginas[-3:])
    faixa_editorial = "\n".join(paginas[:10] + paginas[-3:])
    bordas_urls = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "-", bordas)
    titulo = _titulo_documental_do_inicio(paginas)
    autor = _autor_documental_explicito(paginas)
    urls = []
    for valor in re.findall(r"(?i)(?:https?://|www\.)[^\s<>()]+", bordas_urls):
        for pedaco in re.split(r",(?=(?:https?://|www\.))", valor,
                               flags=re.I):
            limpo = pedaco.rstrip(".,;:)]}")
            if limpo not in urls:
                urls.append(limpo)
    data = ""
    mdata = re.search(r"(?i)Publicado\s+em\s+\d{1,2}/\d{1,2}/((?:19|20)\d{2})",
                      bordas)
    if not mdata:
        mdata = re.search(
            r"(?im)^\s*\d{1,2}\s+de\s+(?:janeiro|fevereiro|mar[çc]o|abril|"
            r"maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+"
            r"de\s+((?:19|20)\d{2})\s*$", inicio)
    if not mdata and urls:
        mdata = re.search(r"/((?:19|20)\d{2})/", urls[0])
        if mdata:
            data = mdata.group(1)
    elif mdata:
        data = mdata.group(1)

    nome_n = identificar.normalizar(pathlib.Path(nome).stem)
    titulo_n = identificar.normalizar(titulo)
    if re.search(r"\b(?:resumo|questionario)\b", f"{nome_n} {titulo_n}"):
        return {
            "tipo_documento": "arquivo inválido", "titulo": titulo,
            "autor": "", "ano": data, "fontes": urls,
            "confianca": "descarte",
            "motivo_descarte": "resumo ou questionário explicitamente identificado",
        }

    sinais_livro = re.search(
        r"(?i)\bISBN\b|\bCopyright\b|[©℗]|Dados\s+(?:Internacionais\s+)?"
        r"de\s+Cataloga[çc][aã]o|Ficha\s+Catalogr[aá]fica|"
        r"(?:Editora|Publisher|Publicado\s+por)\s*:|\bTradutor\b",
        faixa_editorial)
    rotulos_documentais = re.search(
        r"(?i)\b(?:Fonte|AUTOR)\s*:|Publicado\s+em\s+\d{1,2}/\d{1,2}/\d{4}|"
        r"blogspot\.|geocities\.|artigos?_print\.php|\bcurso\s+de\b", bordas)
    tipo_nome = "apostila" if re.search(r"\bapostila\b", nome_n) else "documento"
    if (not sinais_livro and titulo
            and (origem_word or rotulos_documentais or urls)):
        confianca = "alta" if autor and (urls or data) else (
            "media" if urls or autor else "baixa")
        return {
            "tipo_documento": tipo_nome, "titulo": titulo, "autor": autor,
            "ano": data, "fontes": urls, "confianca": confianca,
        }
    return {}


def metadados_livro_word_folha_rosto(paginas, autor=""):
    """Lê a folha de rosto simples preservada por DOC/DOCX antigos."""
    if not paginas:
        return {}
    linhas = [" ".join(x.split()).strip(" \t-|•")
              for x in paginas[0].splitlines()]
    linhas = [x for x in linhas if x]
    autor_n = set(identificar.normalizar(autor.replace(",", " ")).split())
    pos_autor = None
    for pos, linha in enumerate(linhas[:10]):
        tokens = set(identificar.normalizar(linha).split())
        if autor_n and tokens and len(tokens & autor_n) / len(autor_n) >= 0.75:
            pos_autor = pos
            break
    if pos_autor is None:
        return {}
    pos_tradutor = next((i for i, linha in enumerate(linhas[pos_autor + 1:],
                                                    pos_autor + 1)
                         if re.fullmatch(r"(?i)tradutor(?:a)?", linha)), None)
    fim_titulo = pos_tradutor if pos_tradutor is not None else min(
        len(linhas), pos_autor + 4)
    titulo_linhas = [x for x in linhas[pos_autor + 1:fim_titulo]
                     if 2 <= len(x.split()) <= 18]
    titulo = " ".join(titulo_linhas[:2]).strip(" .,:;-")
    if not titulo_bibliograficamente_plausivel(titulo):
        titulo = ""
    tradutor = ""
    if pos_tradutor is not None and pos_tradutor + 1 < len(linhas):
        candidato = linhas[pos_tradutor + 1]
        if autor_bibliograficamente_plausivel(candidato):
            tradutor = candidato
    editora = ""
    inicio_editora = (pos_tradutor + 2 if pos_tradutor is not None
                      else fim_titulo)
    for linha in linhas[inicio_editora:inicio_editora + 5]:
        letras = [c for c in linha if c.isalpha()]
        if (1 <= len(linha.split()) <= 5 and len(letras) >= 4
                and sum(c.isupper() for c in letras) / len(letras) >= 0.75
                and not re.search(r"(?i)caixa\s+postal|endere[çc]o|rio\s+de\s+janeiro",
                                  linha)):
            editora = linha
            break
    editora = limpar_editora_bibliografica(editora)
    return {"titulo": titulo, "tradutor": tradutor, "editora": editora}


def metadados_documentais_rotulados(paginas, metadados=None,
                                     nome="", origem_word=False,
                                     incluir_generico=True):
    """Extrai cabeçalhos explícitos de materiais que não são livros comerciais."""
    inicio = "\n".join(paginas[:10])
    metadados = metadados or {}

    if (re.search(r"(?i)Congresso\s+Brasileiro\s+de\s+Reflex[aã]o\s+Teol[oó]gica",
                  inicio)
            or re.search(r"(?i)\bABIBET\b", inicio)):
        mtitulo = re.search(
            r"(?im)^[\"“']?\s*(Os\s+Batistas[^\n\"”']{12,180})[\"”']?\s*$",
            inicio)
        mautor = re.search(
            r"(?im)^\s*(?:Dr\.?|Prof\.?)\s*"
            r"([A-ZÀ-Ü](?:\.?\s*[A-ZÀ-Ü])?\.?\s+"
            r"[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+)\s*,?\s*(?:Ph\.?D\.?)?\s*$",
            inicio)
        return {
            "tipo_documento": "documento",
            "titulo": (" ".join(mtitulo.group(1).split()).strip(" .,:;-\"“”'")
                       if mtitulo else ""),
            "autor": (sobrenome_virgula(mautor.group(1)) if mautor else ""),
        }

    if re.search(r"(?i)Conc[ií]lio\s+Examinat[oó]rio\s+ao\s+Minist[eé]rio\s+Pastoral",
                 inicio):
        mautor = re.search(
            r"(?im)^\s*([A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+(?:\s+[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+){1,5})"
            r"\s*,\s*pastor\s*$", inicio)
        return {
            "tipo_documento": "apostila",
            "titulo": ("Livro de perguntas e respostas e material de apoio para "
                       "Concílio Examinatório ao Ministério Pastoral Batista"),
            "autor": sobrenome_virgula(mautor.group(1)) if mautor else "",
        }

    if re.search(r"(?i)PREGA[ÇC][ÃA]O\s+EXPOSITIVA\s+TEM[ÁA]TICA", inicio):
        mautor = re.search(
            r"(?im)^\s*(?:Prof\.?|Professor)\s*"
            r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+(?:\s+[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+){1,5})\s*$",
            inicio)
        return {
            "tipo_documento": "apostila",
            "titulo": "Pregação Expositiva Temática",
            "autor": sobrenome_virgula(mautor.group(1)) if mautor else "",
        }

    if (re.search(r"(?i)\bEscola\s+de\s+Homens\b", inicio)
            and re.search(r"(?i)\bAula\s*0?1\b|\bCentro\s+de\s+Educa[çc][ãa]o\b",
                          inicio)):
        autor_pdf = primeiro_autor(metadados.get("autor", ""))
        return {
            "tipo_documento": "apostila",
            "titulo": "Escola de Homens",
            "autor": (sobrenome_virgula(autor_pdf)
                      if autor_bibliograficamente_plausivel(autor_pdf) else ""),
        }
    if incluir_generico:
        return metadados_documentais_genericos(
            paginas, metadados, nome=nome, origem_word=origem_word)
    return {}


TIPOS_ACADEMICOS = {"tese", "dissertação", "trabalho acadêmico"}


def metadados_academicos_paginas(paginas):
    """Lê folha de rosto acadêmica antes das heurísticas documentais gerais."""
    if not paginas:
        return {}
    inicio = "\n".join(paginas[:12])
    marcador = re.search(
        r"(?i)\b(?:a\s+)?(disserta[çc][aã]o|dissertation|tese|thesis|"
        r"trabalho\s+de\s+conclus[aã]o\s+de\s+curso|monografia)\b"
        r".{0,180}?\b(?:apresentad[ao]|submitted|presented)\b",
        inicio, re.S)
    if not marcador:
        return {}
    # Manuais de metodologia descrevem, no sumário e nos capítulos, como
    # preparar uma dissertação ou tese. Isso não transforma o próprio manual
    # em trabalho acadêmico. A declaração de submissão precisa estar nas
    # páginas preliminares quando a capa identifica explicitamente um manual.
    primeiras_tres = "\n".join(paginas[:3])
    if (re.search(r"(?i)\bMANUAL\s+DE\b", paginas[0] if paginas else "")
            and not re.search(
                r"(?is)\b(?:disserta[\u00e7c][a\u00e3]o|tese|thesis|dissertation)\b"
                r".{0,180}?\b(?:apresentad[ao]|submitted|presented)\b",
                primeiras_tres)):
        return {}
    termo = identificar.normalizar(marcador.group(1))
    tipo = ("dissertação" if "disserta" in termo else
            "tese" if termo in {"tese", "thesis"} else
            "trabalho acadêmico")
    antes = inicio[:marcador.start()]

    # Algumas capas antigas condensam a identificação nesta ordem:
    # "Dissertação de Mestrado por:", autor, título e ano. Sem tratar o
    # rótulo, a heurística de caixa-alta pode inverter autor e título. O rótulo
    # explícito e a posição das linhas tornam essa leitura determinística.
    capa_por = re.search(
        r"(?im)^\s*(?:disserta[\u00e7c][aã]o|tese)\s+(?:de\s+\w+\s+)?por\s*:\s*$",
        inicio)
    if capa_por:
        trecho_capa = inicio[capa_por.end():]
        proxima_declaracao = re.search(
            r"(?im)^\s*(?:disserta[\u00e7c][aã]o|tese)\s+apresentad[ao]\b",
            trecho_capa)
        if proxima_declaracao:
            trecho_capa = trecho_capa[:proxima_declaracao.start()]
        posteriores = [
            " ".join(linha.split()).strip(" \t-|\u2022")
            for linha in trecho_capa.splitlines()
        ]
        posteriores = [linha for linha in posteriores if linha]
        if posteriores:
            autor_capa = posteriores[0]
            if autor_capa.isupper():
                autor_capa = autor_capa.title()
            titulo_linhas = []
            for linha in posteriores[1:]:
                if re.fullmatch(r"(?:18|19|20)\d{2}", linha):
                    break
                if len(titulo_linhas) < 4:
                    titulo_linhas.append(linha)
            titulo_capa = limpar_titulo_bibliografico(
                " ".join(titulo_linhas).strip(" .,:;-"))
            instituicao_capa = next((
                " ".join(linha.split()) for linha in inicio.splitlines()
                if re.search(r"(?i)\b(?:universidade|university|faculdade|"
                             r"institute|semin[aá]rio)\b", linha)
            ), "")
            anos_capa = re.findall(r"(?m)^\s*((?:19|20)\d{2})\s*$", inicio)
            if (autor_bibliograficamente_plausivel(autor_capa)
                    and titulo_bibliograficamente_plausivel(titulo_capa)):
                return {
                    "tipo_documento": tipo,
                    "titulo": titulo_capa,
                    "autor": sobrenome_virgula(autor_capa),
                    "instituicao": instituicao_capa,
                    "editora": instituicao_capa,
                    "ano": anos_capa[-1] if anos_capa else "",
                    "confianca": "alta" if instituicao_capa else "média",
                }
    linhas_brutas = antes.splitlines()
    linhas = [(i, " ".join(x.split()).strip(" \t-|•"))
              for i, x in enumerate(linhas_brutas)]
    linhas = [(i, x) for i, x in linhas if x]
    rejeitar_instituicao = re.compile(
        r"(?i)\b(?:universidade|university|faculdade|faculty|instituto|institute|"
        r"programa|program|departamento|department|curso|school|semin[aá]rio|"
        r"p[oó]s-gradua[çc][aã]o|graduate)\b")
    instituicao = next((x for _i, x in linhas[:18]
                        if re.search(r"(?i)\b(?:universidade|university|"
                                     r"faculdade|institute|semin[aá]rio)\b", x)), "")

    autor = ""
    pos_autor = -1
    rotulo_autor = re.search(
        r"(?im)^\s*(?:autor(?:a)?|author|candidato(?:a)?)\s*:\s*"
        r"([^\n]{4,100})\s*$", antes)
    if rotulo_autor:
        candidato = " ".join(rotulo_autor.group(1).split()).strip(" .,:;-")
        if autor_bibliograficamente_plausivel(candidato):
            autor = sobrenome_virgula(candidato)
            pos_autor = antes[:rotulo_autor.start()].count("\n")
    if not autor:
        for indice, linha in linhas[:30]:
            if rejeitar_instituicao.search(linha):
                continue
            if re.search(r"(?i)\b(?:orientador|advisor|supervisor|cidade|city)\s*:",
                         linha):
                continue
            letras = [c for c in linha if c.isalpha()]
            palavras = linha.split()
            if not (2 <= len(palavras) <= 7 and letras
                    and sum(c.isupper() for c in letras) / len(letras) >= 0.72):
                continue
            candidato = linha.title() if linha.isupper() else linha
            if autor_bibliograficamente_plausivel(candidato):
                autor = sobrenome_virgula(candidato)
                pos_autor = indice
                break

    candidatos_titulo = []
    inicio_titulo = pos_autor + 1 if pos_autor >= 0 else 0
    for indice, linha in linhas:
        if indice < inicio_titulo:
            continue
        if rejeitar_instituicao.search(linha):
            continue
        if (re.fullmatch(r"(?:18|19|20)\d{2}", linha)
                or re.search(r"(?i)\b(?:orientador|advisor|supervisor)\s*:", linha)
                or re.fullmatch(r"(?i)[A-ZÀ-Ü][A-Za-zÀ-ÿ .'-]+,?\s*[-–]?\s*"
                                r"(?:18|19|20)\d{2}", linha)):
            continue
        if autor and similaridade_titulos(linha, autor.replace(",", " ")) >= 0.75:
            continue
        if 1 <= len(linha.split()) <= 24 and len(linha) <= 200:
            candidatos_titulo.append((indice, linha))
    titulo = ""
    if candidatos_titulo:
        # A declaração acadêmica costuma vir imediatamente após o título.
        finais = candidatos_titulo[-4:]
        bloco = []
        ultimo = None
        for indice, linha in finais:
            if ultimo is not None and indice > ultimo + 2:
                bloco = []
            bloco.append(linha)
            ultimo = indice
        candidato = " ".join(bloco).strip(" .,:;-")
        if titulo_bibliograficamente_plausivel(candidato):
            titulo = candidato
    anos_sozinhos = re.findall(r"(?m)^\s*((?:19|20)\d{2})\s*$", inicio)
    ano = anos_sozinhos[-1] if anos_sozinhos else ""
    return {
        "tipo_documento": tipo, "titulo": titulo, "autor": autor,
        "instituicao": instituicao, "editora": instituicao, "ano": ano,
        "confianca": "alta" if titulo and autor and instituicao else "média",
    }


def edicao_completa_periodico(paginas):
    """Reconhece uma edicao inteira sem confundi-la com artigo avulso."""
    if not paginas:
        return {}
    inicio = "\n".join(paginas[:10])
    fonte = identificar_periodico_conhecido(inicio)
    if not fonte:
        return {}
    tem_numero = bool(re.search(
        r"(?i)\b(?:vol(?:ume)?|ano)\s*[IVXLCDM\d]+|"
        r"\bN[.º°o]\s*\d+|\bissue\s*\d+", inicio))
    tem_data = bool(re.search(
        r"(?i)\b(?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|"
        r"agosto|setembro|outubro|novembro|dezembro|january|february|"
        r"march|april|may|june|july|august|september|october|november|"
        r"december)\b.{0,15}\b(?:19|20)\d{2}\b|\b(?:19|20)\d{2}\b",
        inicio))
    tem_sumario = bool(re.search(r"(?im)^\s*(?:SUM[ÁA]RIO|CONTENTS)\s*$",
                                 inicio))
    entradas_sumario = len(re.findall(
        r"(?im)^\s*.{5,100}?\s+(?:\.{2,}\s*)?\d{1,4}\s*$", inicio))
    declara_artigo = bool(re.search(
        r"(?i)\b(?:este|o\s+presente)\s+(?:artigo|ensaio|estudo)\b|"
        r"\bobjetivo\s+d[oe]\s+(?:presente\s+)?artigo\b|"
        r"\b(?:this|the\s+present)\s+(?:article|essay|study|paper)\b|"
        r"(?:^|\s)!is\s+(?:article|essay|study|paper)\b|"
        r"\bthe\s+aim\s+of\s+(?:this\s+)?(?:article|paper|study)\b",
        "\n".join(paginas[:3])))
    tem_resumo = bool(re.search(
        r"(?im)^\s*(?:RESUMO|ABSTRACT)\s*(?::|$)",
        "\n".join(paginas[:3])))
    sumario_de_edicao = tem_sumario and entradas_sumario >= 3
    # Revistas historicas como Voice podem nao trazer sumario nas primeiras
    # paginas. Nome recorrente + numero/data + corpo extenso vale somente na
    # ausencia de sinais de artigo individual.
    capa_de_edicao = (len([p for p in paginas if p.strip()]) >= 6
                      and tem_numero and tem_data
                      and not (declara_artigo or tem_resumo))
    if sumario_de_edicao or capa_de_edicao:
        return {"editora": fonte, "tipo_documento": "revista"}
    return {}


def metadados_artigo_periodico(paginas):
    """Reconhece recortes de periódicos mesmo sem ISSN ou a palavra revista."""
    if not paginas:
        return {}
    primeira = paginas[0]
    bordas = "\n".join(paginas[:3] + paginas[-2:])
    numero_paginas = re.search(
        r"(?im)^\s*[^\n]{2,80}?\b(?:[IVXLCDM]+|\d{1,3})"
        r"(?:\s*/\s*\d{1,3}|\s*,?\s*N[.\u00ba°o]*\s*\d{1,3}|\s*\(\s*\d{1,3}\s*\))"
        r"[^\n]{0,45}?\b(?:19|20)\d{2}\b[^\n]{0,25}?"
        r"\d{1,4}\s*[-–—]\s*\d{1,4}\s*$", primeira)
    numero_paginas_final_ano = re.search(
        r"(?im)^\s*[^\n]{2,80}?\b\d{1,3}\s*\(\s*\d{1,3}\s*\)"
        r"\s*:\s*\d{1,4}\s*[-–—]\s*\d{1,4}\s*,\s*"
        r"(?:19|20)\d{2}\s*$", primeira)
    numero_paginas_romano_colado = re.search(
        r"(?im)^\s*[^\n]{2,60}?[IVXLCDM]+\s*,?\s*"
        r"N[.\u00ba°o]*\s*\d{1,3}\s*\([^\n)]*(?:19|20)\d{2}\)"
        r"\s*:\s*\d{1,4}\s*[-–—]\s*\d{1,4}\s*$", primeira)
    numero_ano = re.search(
        r"(?im)^\s*[^\n]{2,70}?\b(?:[IVXLCDM]+|\d{1,3})"
        r"\s*/\s*\d{1,3}\s*\([^\n)]*(?:19|20)\d{2}\)\s*$",
        primeira)
    citacao_volume = re.search(
        r"(?i)\b(?:orgs?|eds?)\.,?[^\n]{0,80}?\b"
        r"([A-Z][A-Za-zÀ-ÿ'.-]+)\s+\d{1,3}\s*"
        r"\(((?:19|20)\d{2})\)", primeira)
    tem_resumo = bool(re.search(
        r"(?im)^\s*(?:RESUMO|ABSTRACT)\s*(?::|$)", primeira))
    declara_artigo = bool(re.search(
        r"(?i)\b(?:este|o\s+presente)\s+(?:artigo|ensaio|estudo)\b|"
        r"\bobjetivo\s+d[oe]\s+(?:presente\s+)?artigo\b|"
        r"\b(?:this|the\s+present)\s+(?:article|essay|study|paper)\b|"
        r"(?:^|\s)!is\s+(?:article|essay|study|paper)\b|"
        r"\bthe\s+aim\s+of\s+(?:this\s+)?(?:article|paper|study)\b",
        "\n".join(paginas[:3])))
    referencia_resenhada = re.search(
        r"(?ims)^\s*[A-ZÀ-Ü][A-ZÀ-Ü'\u2019-]+,\s*[^\n.]{2,80}\.\s*"
        r"(.{8,220}?)\.\s*(?:Trad\.|[A-ZÀ-Ü][^:\n]{1,80}:)",
        primeira)
    assinatura_resenha = re.search(
        r"(?im)^\s*[-–—]\s*([A-ZÀ-Ü][A-Za-zÀ-ÿ'\u2019.-]+"
        r"(?:\s+[A-ZÀ-Ü][A-Za-zÀ-ÿ'\u2019.-]+){1,5})\s*$", bordas)
    resenha_curta = bool(
        numero_ano and len([p for p in paginas if p.strip()]) <= 5
        and referencia_resenhada and assinatura_resenha)
    estrutura_periodico = bool(
        numero_paginas or numero_paginas_final_ano
        or numero_paginas_romano_colado or numero_ano or citacao_volume)
    # Decisão conservadora: numeração editorial sozinha não basta. O
    # conteúdo também precisa se declarar artigo/ensaio/estudo e trazer
    # resumo ou faixa de páginas. Casos incompletos permanecem em revisão.
    # A fonte deve aparecer na primeira página. Procurar também no fim do
    # artigo fazia uma referência bibliográfica vencer o cabeçalho real.
    fonte_conhecida = identificar_periodico_conhecido(primeira)
    artigo_forte = bool(
        (estrutura_periodico and declara_artigo
         and (tem_resumo or numero_paginas or numero_paginas_final_ano
              or numero_paginas_romano_colado))
        or (fonte_conhecida and declara_artigo and tem_resumo))
    if not (artigo_forte or resenha_curta):
        return {}

    fonte = fonte_conhecida
    if not fonte and citacao_volume:
        fonte = citacao_volume.group(1)

    anos = re.findall(r"\b((?:19|20)\d{2})\b", primeira)
    ano = anos[0] if anos else (citacao_volume.group(2)
                                if citacao_volume else "")
    if resenha_curta:
        return {
            "titulo": "Resenha de " + " ".join(
                referencia_resenhada.group(1).split()),
            "autor": sobrenome_virgula(assinatura_resenha.group(1)),
            "ano": ano, "editora": fonte,
        }

    linhas = [(i, " ".join(x.split()).strip())
              for i, x in enumerate(primeira.splitlines())]
    indice_resumo = next(
        (i for i, x in linhas
         if re.match(r"(?i)^(?:RESUMO|ABSTRACT)\s*(?::|$)", x)),
        min(len(linhas), 28))
    rejeitar_nome = re.compile(
        r"(?i)\b(?:college|university|universidade|faculdade|seminary|"
        r"instituto|journal|revista|fides|ateli[\u00ea]e?|semeia|JETS)\b")
    candidatos_autor = []
    padrao_nome = re.compile(
        r"^(?:[A-ZÀ-Ü][A-Za-zÀ-ÿ'\u2019.-]*|[A-Z]\.)"
        r"(?:\s+(?:de|da|do|dos|das|van|von|e|&|"
        r"[A-ZÀ-Ü][A-Za-zÀ-ÿ'\u2019.-]*|[A-Z]\.)){1,6}$")
    for indice, linha in linhas[:indice_resumo]:
        if linha.rstrip().endswith((':', ';')):
            continue
        candidato = re.sub(r"\s*[\d*]+​?\s*$", "", linha).strip(" ,;:")
        if (padrao_nome.fullmatch(candidato) and not rejeitar_nome.search(candidato)
                and not re.match(
                    r"(?i)^(?:A|O|OS|AS|UM|UMA|PARA|PELO|PELA|THE|OF|IN)\b",
                    candidato)
                and autor_bibliograficamente_plausivel(candidato)):
            candidatos_autor.append((indice, candidato))
    if not candidatos_autor:
        return {"titulo": "", "autor": "", "ano": ano, "editora": fonte}
    # Quando o título está todo em maiúsculas e o nome vem em caixa normal,
    # a linha final do título também pode parecer uma pessoa. A presença de
    # candidato com minúsculas permite descartar esse falso positivo; se a
    # edição imprimir todos os autores em maiúsculas, nada é descartado.
    candidatos_caixa_normal = [
        item for item in candidatos_autor if any(c.islower() for c in item[1])]
    if candidatos_caixa_normal:
        candidatos_autor = candidatos_caixa_normal
    inicio_bloco = len(candidatos_autor) - 1
    while (inicio_bloco > 0 and candidatos_autor[inicio_bloco][0]
           - candidatos_autor[inicio_bloco - 1][0] <= 2):
        inicio_bloco -= 1
    indice_autor, autor = candidatos_autor[inicio_bloco]

    excluir_titulo = re.compile(
        r"(?i)\b(?:JETS|FIDES\s+REFORMATA|ATELI[\u00caE]\s+DE\s+HIST[\u00d3O]RIA|"
        r"JOURNAL\s+OF|SEMEIA|COLLEGE|UNIVERSITY|UNIVERSIDADE)\b")
    titulo_linhas = []
    for _indice, linha in linhas[:indice_autor]:
        if (not linha or excluir_titulo.search(linha)
                or re.fullmatch(r"\d+", linha)):
            continue
        palavras = linha.split()
        if 1 <= len(palavras) <= 24 and len(linha) <= 180:
            titulo_linhas.append(linha)
    titulo = " ".join(titulo_linhas[-6:]).strip(" .,:;-")
    titulo = limpar_titulo_bibliografico(titulo)
    if not titulo_bibliograficamente_plausivel(titulo):
        titulo = ""
    return {
        "titulo": titulo, "autor": sobrenome_virgula(autor),
        "ano": ano, "editora": fonte,
    }


def tipo_documento_e_autor(t, paginas, metadados=None,
                           nome="", origem_word=False):
    """Reconhece documentos que nao sao livros e autores explicitamente rotulados."""
    inicio = "\n".join(paginas[:10])
    metadados = metadados or {}
    nome_n = identificar.normalizar(pathlib.Path(nome).stem)

    # Uma aula isolada pode nao usar a palavra "apostila". Numero da aula
    # no arquivo, checklist final e reflexoes repetidas formam em conjunto
    # uma assinatura didatica forte, sem reagir a uma mencao casual.
    if (re.search(r"\baula\s*0?\d+\b", nome_n)
            and re.search(r"(?im)^\s*CHECKLIST\s+DA\s+AULA\b",
                          "\n".join(paginas[-3:]))
            and len(re.findall(
                r"(?im)^\s*>?\s*REFLEX[ÃA]O\b", inicio)) >= 2
            and not re.search(
                r"(?i)\bISBN\b|Ficha\s+Catalogr[aá]fica|Dados\s+de\s+"
                r"Cataloga[çc][ãa]o|(?:Editora|Publisher)\s*:", inicio)):
        return "apostila", ""

    # O nome de arquivo pode vir de scanners que prefixam um identificador
    # numérico diretamente a "apostila" (ex.: 11520apostila_...). Exigimos
    # também sinais didáticos/religiosos no conteúdo para que uma mera menção
    # no nome não reclassifique um livro comercial.
    if (re.search(r"(?i)apostila", pathlib.Path(nome).stem)
            and re.search(r"(?i)\b(?:treinamento|di[aá]cono|disciplina|curso|"
                          r"aulas?|manual|conceito\s+e\s+miss[aã]o)\b", inicio)):
        autor_capa = _campo(
            inicio,
            [r"(?im)^\s*(?:Pr\.?|Prof\.?|Professor)\s+"
             r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+(?:[ \t]+[A-ZÀ-Ü]"
             r"[A-Za-zÀ-ÿ'.-]+){1,6})\s*$"], 100)
        return "apostila", sobrenome_virgula(autor_capa)

    # E-books distribuídos diretamente pelo autor, sem ficha editorial,
    # podem se declarar gratuitos e pedir doação nas páginas iniciais.
    # São documentos digitais, não edições comerciais incompletas. Exigir
    # simultaneamente as três marcas evita reagir a uma frase isolada.
    if (re.search(r"(?i)\be-?book\b.{0,100}\bdisponibilizado\b", inicio, re.S)
            and re.search(r"(?i)\btotalmente\s+gratuito\b", inicio)
            and re.search(r"(?i)\b(?:doa[\u00e7c][aã]o|PayPal|QR\s*Code)\b", inicio)):
        autor_pdf = primeiro_autor(metadados.get("autor", ""))
        autor_pdf = (sobrenome_virgula(autor_pdf)
                     if autor_bibliograficamente_plausivel(autor_pdf) else "")
        return "documento", autor_pdf

    # Um manual de metodologia descreve teses, dissertações e monografias
    # no sumário; ele não é, por isso, um trabalho acadêmico. A capa precisa
    # declarar simultaneamente MANUAL e metodologia/normatização.
    primeira_pagina = paginas[0] if paginas else ""
    if (re.search(r"(?i)\bMANUAL\s+DE\b", primeira_pagina)
            and re.search(r"(?i)\b(?:METODOLOGIA|NORMATIZA[\u00c7C][\u00c3A]O)\b",
                          primeira_pagina)):
        nomes = []
        for linha in primeira_pagina.splitlines()[:12]:
            candidato = " ".join(linha.split()).strip(" .,:;-")
            if re.search(r"(?i)\bMANUAL\s+DE\b", candidato):
                break
            if (2 <= len(candidato.split()) <= 7
                    and autor_bibliograficamente_plausivel(candidato)
                    and not re.search(r"(?i)\b(?:manual|metodologia|pesquisa|"
                                      r"cient[ií]fica|faculdade|normatiza[\u00e7c][\u00e3a]o|"
                                      r"trabalhos?\s+acad[\u00eam]micos?)\b", candidato)):
                nomes.append(sobrenome_virgula(candidato))
        return "apostila", "; ".join(dict.fromkeys(nomes[:3]))

    academico_estruturado = metadados_academicos_paginas(paginas)
    if academico_estruturado:
        return (academico_estruturado["tipo_documento"],
                academico_estruturado.get("autor", ""))
    edicao_periodico = edicao_completa_periodico(paginas)
    if edicao_periodico:
        return "revista", ""
    artigo_periodico = metadados_artigo_periodico(paginas)
    if artigo_periodico:
        return "artigo", artigo_periodico.get("autor", "")
    # Declarações editoriais inequívocas observadas em materiais do lote.
    # Cada regra exige mais de um sinal para não reagir a uma palavra solta
    # no corpo de um livro.
    apostila_professor = re.search(
        r"(?is)\bAPOSTILA\b.{0,240}?\b(?:Professor|Prof\.)\s*:\s*"
        r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+(?:\s+[A-ZÀ-Ü]"
        r"[A-Za-zÀ-ÿ'.-]+){1,5})", inicio)
    if apostila_professor:
        return "apostila", sobrenome_virgula(apostila_professor.group(1))
    if (re.search(r"(?i)programa\s+de\s+discipulado", inicio)
            and re.search(r"(?i)pequenos?\s+grupos?", inicio)
            and re.search(r"(?i)minist[\u00e9e]rio|conven[\u00e7c][\u00e3a]o|igreja", inicio)):
        return "apostila", ""
    # Cadernos de aulas podem omitir a palavra "apostila" na capa. Uma
    # sequência de aulas no sumário, ou a combinação código + disciplina +
    # escola de discípulos, identifica material didático sem depender do nome.
    aulas_sumario = len(re.findall(
        r"(?im)^\s*Aula(?:\s+Pr[aá]tica)?\s+\d+\s*[-–—]", inicio))
    if aulas_sumario >= 4:
        return "apostila", ""
    if (re.search(r"(?im)^\s*C[oó]digo\s*:\s*$", inicio)
            and re.search(r"(?im)^\s*Disciplina\s*:\s*$", inicio)
            and re.search(r"(?i)Escola\s+de\s+Disc[ií]pulos", inicio)):
        autor_material = _campo(
            inicio,
            [r"(?i)Copyright\s*(?:©|\(c\))?\s*(?:19|20)\d{2}\s+por\s+"
             r"([^\n]{3,80})"], 90)
        return "apostila", sobrenome_virgula(autor_material)
    # Coletâneas digitais de artigos não são livros comerciais, ainda que
    # tenham muitas páginas e um único autor. O nome precisa declarar
    # simultaneamente a coletânea e os artigos.
    if (re.search(r"\bcoletanea\b.*\bartigos?\b|\bartigos?\b.*\bcompilad", nome_n)
            and re.search(r"(?im)^\s*Orlando\s+E\.?\s+Costas\s*$", inicio)):
        return "documento", "Costas, Orlando E."
    # Resenhas recortadas de periódicos podem começar pelo título e autor do
    # livro resenhado. Identidade do periódico, seção e assinatura final são
    # exigidas em conjunto para não atribuir a resenha ao autor do livro.
    fim = "\n".join(paginas[-2:])
    if (len([p for p in paginas if p.strip()]) <= 5
            and re.search(r"(?im)^\s*Theology\s+Today\s*$", inicio)
            and re.search(r"(?i)Review\s+Section|Downloaded\s+from\s+ttj\.",
                          "\n".join(paginas))
            and re.search(r"(?is)HUGH\s*MOFFETT.{0,120}SAMUEL|"
                          r"SAMUEL.{0,120}HUGH\s*MOFFETT", fim)):
        return "artigo", "Moffett, Samuel Hugh"
    # Cadernos de curso sem ficha editorial ou ISBN pertencem à fila de
    # documentos. As três marcas combinadas evitam uma classificação por
    # simples menção da palavra "curso".
    if (re.search(r"(?i)CURSO\s+B[ÁA]SICO", inicio)
            and re.search(r"(?i)CRESCIMENTO\s+EQUILIBRADO\s+NA\s+IGREJA\s+LOCAL",
                          inicio)
            and re.search(r"(?i)PESQUISA\s+E\s+TREINAMENTO", inicio)):
        return "documento", "[autor não identificado]"
    if (re.search(r"(?i)\b(?:WORKSHOP\s+)?VOLUNT[\u00c1A]RIOS?\b", inicio)
            and re.search(r"(?i)\b(?:igreja|Lagoinha|minist[\u00e9e]rio)\b", inicio)):
        return "documento", ""
    if (re.search(r"(?i)\bRevista\s+do\s+Aluno\b", inicio)
            and re.search(r"(?i)Publica[\u00e7c][\u00e3a]o\s+e\s+Distribui[\u00e7c][\u00e3a]o", inicio)
            and re.search(r"(?i)\b(?:L[\u00cdI][\u00c7C][\u00c3A]O|[\u00cdI]NDICE|curso)\b", inicio)):
        return "revista", ""
    if (re.search(r"(?i)testimonies\s+were\s+excerpted", inicio)
            and re.search(r"(?i)\bThis\s+site\b", inicio)
            and re.search(r"(?i)\bMain\s+Contents\b|\bREFERENCES\b", inicio)):
        return "documento", ""
    rotulado = metadados_documentais_rotulados(
        paginas, metadados, nome=nome, origem_word=origem_word,
        incluir_generico=False)
    if rotulado:
        if (rotulado.get("tipo_documento") == "artigo"
                and not rotulado.get("autor")):
            artigo_rotulado = metadados_artigo_paginas(paginas, nome=nome)
            rotulado["autor"] = artigo_rotulado.get("autor", "")
        return rotulado["tipo_documento"], rotulado.get("autor", "")
    # Apostilas institucionais podem trazer uma ficha própria chamada DCIP.
    # Ela é uma fonte bibliográfica forte, mas não transforma a disciplina
    # em livro comercial. O conjunto DCIP + disciplina/curso é a trava para
    # não reclassificar livros que apenas mencionem uma apostila no texto.
    if (re.search(r"(?i)DADOS\s+DE\s+CATALOGA[ÇC][ÃA]O\s+INTERNA\s+"
                  r"DA\s+PUBLICA[ÇC][ÃA]O\s*[-–—]?\s*DCIP", inicio)
            and re.search(r"(?i)\b(?:DISCIPLINA|CURSO\s+ONLINE\s+DE\s+"
                          r"TEOLOGIA|Esta\s+apostila)\b", inicio)):
        dc = ler_dcip_institucional_paginas(paginas)
        return "apostila", dc.get("autor", "")
    produtor = " ".join((metadados.get("criador", ""),
                          metadados.get("produtor", "")))
    tamanhos = [len(" ".join(p.split())) for p in paginas if p.strip()]
    fracao_curta = (sum(n < 700 for n in tamanhos) / len(tamanhos)
                    if tamanhos else 0.0)
    if (re.search(r"(?i)powerpoint|impress|keynote", produtor)
            and len(tamanhos) >= 4 and fracao_curta >= 0.60):
        return "documento", "[autor não identificado]"
    # Relatórios e manuais institucionais se declaram como tais na capa.
    # Reconhecê-los antes das fontes comerciais evita tratá-los como livros
    # apenas porque possuem autor, copyright e muitas páginas.
    relatorio = re.search(
        r"(?im)^\s*(?:A\s+)?(?:Research\s+Report|Relat[oó]rio\s+de\s+Pesquisa)"
        r"\s+(?:by|por)\s+([^\n|]{3,80})\s*$", inicio)
    if relatorio:
        return "documento", sobrenome_virgula(relatorio.group(1).strip())
    if re.search(r"(?im)^\s*Manual\s+Institucional\s*$", inicio):
        return "documento", ""
    # Materiais de conferência marcados como LAB são apostilas de trabalho,
    # não monografias comerciais, ainda que o nome do arquivo seja ambíguo.
    if (re.search(r"(?im)^\s*LAB\s*\|", inicio)
            and re.search(r"(?i)\bConfer[êe]ncia\b\s+\w*\s*(?:19|20)\d{2}",
                          inicio)):
        return "apostila", ""
    # Materiais de curso podem trazer a palavra "livro" na capa, mas a
    # própria edição os identifica como apostila/complemento de aulas.
    if (re.search(r"(?i)CURSO\s+B[ÍI]BLICO\s+INTERNACIONAL", inicio)
            and re.search(r"(?i)ENCONTRO\s+COM\s+A\s+PALAVRA", inicio)):
        autor = _campo(inicio, [r"(?im)^\s*(?:PR\.\s*)?(DICK\s+WOODWARD)\s*$"], 80)
        return "apostila", sobrenome_virgula(autor)
    if re.search(r"(?i)PLANO\s+DE\s+AULA\s+APOSTILADO", inicio):
        autor = _campo(
            inicio,
            [r"(?i)(Escola\s+Superior\s+de\s+Teologia\s+do\s+Esp[íi]rito\s+Santo)"],
            100)
        return "apostila", autor
    if (re.search(r"(?i)Caderno\s+Igreja", inicio)
            and re.search(r"(?i)(?:m[oó]dulo|discipulado|aulas?)", inicio)):
        return "apostila", ""
    material_unidade = (
        re.search(r"(?i)Unidade\s+Tem[aá]tica\s*[o0]?\d+", inicio)
        or (re.search(r"(?i)Plano\s+de\s+Ensino", inicio)
            and re.search(r"(?i)\bEmenta\b", inicio)
            and len(re.findall(r"(?i)\bUnidade\s+\d+\b", inicio)) >= 2))
    if (material_unidade
            and re.search(r"(?i)Plano\s+de\s+Ensino", inicio)
            and re.search(r"(?i)Faculdade|Semin[aá]rio|Instituto", inicio)):
        autor = _campo(
            inicio,
            [r"(?i)Breve\s+Biografia\s+do\s+Autor(?:[ \t]*\n){1,2}[ \t]*"
             r"([A-ZÀ-Ü][A-ZÀ-Ü \t]{5,80})"],
            90)
        return "apostila", sobrenome_virgula(autor.title())
    if (re.search(r"(?im)^\s*(?:Texto|Tema|Prop[oó]sito)\s*:", inicio)
            and re.search(r"(?im)\b(?:serm[aã]o|predica[çc][aã]o|mensaje)\b|"
                          r"^\s*Texto\s*:\s*\d?\s*[A-ZÁ-Ú]", inicio)):
        return "sermão", ""
    if (re.search(r"(?i)Transcri[çc][ãa]o\s+feita\s+a\s+partir\s+do\s+v[íi]deo", inicio)
            and re.search(r"(?i)serm[ãa]o", inicio)):
        autor = _campo(inicio, [r"(?im)^\s*Por\s*:\s*([^\n©|]{3,80})"], 90)
        return "sermão", sobrenome_virgula(autor)
    academico = re.search(
        r"(?i)trabalho\s+de\s+conclus[aã]o\s+de\s+curso|monografia\s+apresentada|"
        r"disserta[çc][aã]o\s+apresentada|tese\s+apresentada|"
        r"obten[çc][aã]o\s+do\s+(?:t[ií]tulo|grau)\s+de", inicio)
    if academico:
        if re.search(r"(?i)disserta[çc][aã]o\s+apresentada", inicio):
            return "dissertação", ""
        if re.search(r"(?i)tese\s+apresentada", inicio):
            return "tese", ""
        return "trabalho acadêmico", ""
    if re.search(r"(?im)^\s*Discente\s*:\s*", inicio):
        autor = _campo(inicio, [r"Discente\s*:\s*([^\n]{3,80})"], 90)
        return "trabalho acadêmico", sobrenome_virgula(autor)
    if (re.search(r"(?i)Faculdade|Universidade", inicio)
            and re.search(r"(?i)Disciplina\s*:|Docente\s*:", inicio)):
        return "trabalho acadêmico", ""
    # Cadernos didáticos de faculdades de teologia nem sempre imprimem a
    # palavra "apostila". No lote real, a instituição, o nível/curso no nome
    # e a identificação da disciplina aparecem juntos. Essa convergência é
    # específica o bastante para não reclassificar livros publicados por uma
    # editora universitária.
    sinais_curso = "\n".join((inicio, nome_n))
    if (re.search(r"(?i)\b(?:Faculdade|Semin[aá]rio|Instituto\s+Teol[oó]gico)\b",
                  inicio)
            and re.search(r"(?i)\b(?:m[eé]dio\s+teologia|disciplina\s*:|"
                          r"profa?\.\s*(?:dra?\.)?.{0,80}\bautor(?:a)?\b|"
                          r"plano\s+de\s+ensino|ementa)\b", sinais_curso)):
        autor_curso = _campo(
            inicio,
            [r"(?im)^\s*Profa?\.\s*(?:Dra?\.)?\s*"
             r"([A-ZÀ-Ü][^\n]{3,80}?)\s+Autor(?:a)?\s*$"], 90)
        return "apostila", sobrenome_virgula(autor_curso)
    # Artigos avulsos nem sempre preservam ISSN ou cabeçalho do periódico.
    # Título destacado, autoria, introdução numerada e nota de afiliação
    # formam um conjunto inequívoco.
    artigo_sem_cabecalho = re.search(
        r"(?is)^\s*\d*\s*\n\s*([^\n]{8,160})\n\s*"
        r"([A-ZÀ-Ü][^\n]{3,80})\n.{0,500}?\b1\.\s*Introdu[çc][aã]o\b",
        inicio)
    if (artigo_sem_cabecalho
            and re.search(r"(?is)\b(?:doutor|professor)\b.{0,160}"
                          r"\b(?:Faculdade|Universidade|Instituto)\b", inicio)):
        autor_artigo = artigo_sem_cabecalho.group(2).strip(" .,:;-")
        if autor_bibliograficamente_plausivel(autor_artigo):
            return "artigo", sobrenome_virgula(autor_artigo)
    if re.search(r"(?i)artigos?_print\.php|Imprimir\s*\|\s*Fechar", inicio):
        autor = _campo(inicio, [r"(?im)^\s*Por\s+([^\n]{3,80})"], 90)
        return "artigo", sobrenome_virgula(autor)
    # Impressões de artigos web preservam URL, cabeçalho ou marcador ARTICLE.
    # Isso também cobre páginas com muita navegação antes do H1, como as da
    # American Bible Society, sem confundi-las com documentos institucionais.
    dados_artigo_web = metadados_artigo_paginas(paginas, nome=nome)
    if (dados_artigo_web.get("fonte_web")
            and dados_artigo_web.get("url")
            and dados_artigo_web.get("titulo")):
        return "artigo", dados_artigo_web.get("autor", "")
    if (re.search(r"(?im)^\s*ARTICLE\s*$", inicio)
            and re.search(r"(?i)Tyndale\s+House|biblical scholarship", inicio)):
        return "artigo", dados_artigo_web.get("autor", "")
    # Páginas salvas de sites frequentemente perdem URL e logotipo, mas
    # preservam a assinatura relativa "Por Nome | 12 meses atrás".
    artigo_web = re.search(
        r"(?im)^\s*Por\s+([^\n|]{3,80})\s*\|\s*"
        r"\d+\s+(?:minutos?|horas?|dias?|semanas?|meses?|anos?)\s+atr[aá]s\s*$",
        inicio)
    if artigo_web:
        return "artigo", sobrenome_virgula(artigo_web.group(1).strip())
    # Um artigo avulso conserva o cabeçalho/rodapé do periódico, mas não deve
    # ser encaminhado como uma edição completa da revista.
    if (re.search(r"(?i)\b(?:revista|journal|ci[êe]ncias\s+da\s+religi[aã]o)\b",
                  inicio)
            and re.search(r"(?i)\bRESUMO\b|\bABSTRACT\b", inicio)
            and re.search(r"(?i)\bVolume\s*\d+|\bN[.º°o]\s*\d+|\bISSN\b", inicio)):
        autor = _campo(inicio, [r"(?m)^([A-ZÁ-Ú][^\n]{3,80})\n(?:Mestre|Doutor|Professor)"], 90)
        if not autor:
            autor = metadados_artigo_paginas(
                paginas, nome=nome).get("autor", "")
            return "artigo", autor
        return "artigo", sobrenome_virgula(autor)
    # Alguns periódicos internacionais usam somente o nome próprio (por
    # exemplo, Acta Theologica), seguido de volume, páginas, ISSN e Abstract.
    if (re.search(r"(?im)^\s*Abstract\s*$", inicio)
            and re.search(r"(?i)\bISSN\s*[:.-]?\s*\d{4}[ -]?\d{3}[\dX]\b", inicio)
            and re.search(r"(?m)\b(?:19|20)\d{2}\s+\d{1,3}\s*\(\d+\)\s*:\s*\d+", inicio)):
        dados_artigo = metadados_artigo_paginas(paginas, nome=nome)
        return "artigo", dados_artigo.get("autor", "")
    # Exige simultaneamente identidade editorial e ISSN/numeração. Uma
    # simples citação da palavra "revista" dentro de um livro não basta.
    if (re.search(r"(?i)\b(?:revista|magazine|journal|peri[oó]dico|boletim)\b",
                  inicio)
            and (re.search(r"(?i)\bISSN\s*[:.-]?\s*\d{4}[ -]?\d{3}[\dX]\b",
                           inicio)
                 or re.search(r"(?i)\b(?:vol(?:ume)?|ano)\s*[IVXLCDM\d]+\s*[,/-]?\s*"
                              r"(?:n[º°o.]|número)\s*\d+", inicio))):
        return "revista", ""
    if re.search(r"(?i)QUICK TABLE OF CONTENTS", inicio) and re.search(
            r"(?i)Seven\s+Classic|7\s+Classic", inicio):
        return "coletânea", ""
    # Materiais digitais de estudo às vezes se autodenominam "livro", mas
    # trazem somente um aviso genérico de uso pessoal e proibição de revenda,
    # sem qualquer identidade de uma edição publicada. Catalogá-los como
    # livro força autor/editora/data inexistentes; como documento, preserva-se
    # o conteúdo sem inventar um tombo editorial.
    paginas_com_texto = [p.strip() for p in paginas if p.strip()]
    aviso_material_pessoal = bool(
        re.search(r"(?is)este\s+livro.{0,500}?uso\s+pessoal", inicio)
        and re.search(r"(?is)(?:n[aã]o\s+[ée]\s+permitida\s+a\s+revenda|"
                      r"proibid[ao].{0,120}?revenda)", inicio)
        and re.search(r"(?i)consentimento\s+(?:expresso\s+)?do\s+autor|"
                      r"propriet[aá]rio\s+dos\s+direitos", inicio))
    identidade_publicada = bool(re.search(
        r"(?i)\bISBN\b|Dados\s+(?:Internacionais\s+)?de\s+Cataloga[çc][aã]o|"
        r"Ficha\s+Catalogr[aá]fica|(?:Publicado|Published)\s+(?:por|by)|"
        r"(?:Editora|Editorial|Publisher)\s*:", inicio))
    autoria_explicita = bool(_autor_documental_explicito(paginas))
    if (2 <= len(paginas_com_texto) <= 80 and aviso_material_pessoal
            and not identidade_publicada and not autoria_explicita):
        return "documento", ""
    # Um PDF curto que começa diretamente por um capítulo numerado, sem
    # qualquer folha de rosto, copyright, ISBN ou identidade editorial, é
    # provavelmente um recorte de obra. Ele deve ser preservado na fila de
    # documentos, não cadastrado como se fosse um livro completo.
    primeira = paginas_com_texto[0] if paginas_com_texto else ""
    sinais_editoriais = re.search(
        r"(?i)\bISBN\b|\bCopyright\b|[©℗]|Dados\s+(?:Internacionais\s+)?de\s+"
        r"Cataloga[\u00e7c][\u00e3a]o|Ficha\s+Catalogr[aá]fica|"
        r"(?:Editora|Publisher)\s*:", inicio)
    comeca_em_capitulo = re.match(
        r"(?s)^\s*(?:CAP[\u00cdI]TULO\s+)?\d{1,2}\s*\n\s*"
        r"[A-ZÀ-Ü][A-ZÀ-Ü0-9 ,:'\u2013\u2014\-]{5,100}(?:\n|$)", primeira)
    if (2 <= len(paginas_com_texto) <= 30 and comeca_em_capitulo
            and not sinais_editoriais):
        return "trecho", ""
    declarado = re.search(
        r"(?i)permiss[aã]o\s+do\s+autor\s+(?:Pr\.?\s*)?"
        r"([A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+(?:[ \t]+[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+){0,4})"
        r"(?:(?:[ \t]*\n){1,2}[ \t]*([A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+))?",
        inicio)
    autor_declarado = (" ".join(x for x in declarado.groups() if x).strip()
                       if declarado else "")
    if autor_declarado:
        return "livro", sobrenome_virgula(autor_declarado)
    generico = metadados_documentais_genericos(
        paginas, metadados, nome=nome, origem_word=origem_word)
    if generico:
        return generico["tipo_documento"], generico.get("autor", "")

    institucional = material_institucional_de_igreja(t, inicio)
    if institucional:
        return institucional, ""

    return "livro", ""


# ---------------------------------------------------------------------------
# MATERIAL INTERNO DE IGREJA
# ---------------------------------------------------------------------------
#
# Sete dos livros parados em revisao eram manuais de ministerio, series de
# estudo para pequenos grupos e apostilas de igreja - material que NAO TEM
# editora nem ISBN porque nunca teve. Estavam classificados como "livro", e
# o tombo de livro exige editora e data, entao ficavam presos por falta de
# um dado que nao existe.
#
# O proprio codigo ja advertia sobre isso ao tratar documentos:
#   "exigir campos inexistentes criava revisao artificial"
# faltava so o material de igreja cair nessa categoria.
#
# Exemplos reais do acervo:
#   "MINISTERIO DE LOUVOR / Manual de Orientacoes / 1a Edicao / Janeiro 2022"
#   "Esta serie de estudos e uma ferramenta ... Pequeno Grupo"

MINISTERIO = (r"minist[ée]rio|departamento|congrega[çc][ãa]o|"
              r"igreja|par[óo]quia|pastoral|di[áa]cono|pequenos? grupos?|"
              r"c[ée]lula|escola b[íi]blica|EBD\b")

INSTITUCIONAL = (
    # "Manual de Orientacoes" de um ministerio
    (rf"(?i)manual\s+(?:de|para|do|da)\s+[^\n]{{0,60}}", MINISTERIO, "documento"),
    # serie de estudos / material de discipulado
    (r"(?i)s[ée]rie\s+de\s+estudos|roteiro\s+de\s+estudos?|"
     r"material\s+de\s+discipulado|caderno\s+de\s+estudos?",
     MINISTERIO, "apostila"),
    # apostila declarada
    (r"(?i)\bapostila\b", MINISTERIO, "apostila"),
    # regimento, estatuto, diretrizes - documento normativo interno
    (r"(?i)regimento\s+interno|estatuto\s+(?:da|do)\s+|diretrizes\s+(?:da|do)\s+",
     MINISTERIO, "documento"),
)


# ---------------------------------------------------------------------------
# NAO REFAZER O QUE NAO MUDOU  -  ESCRITO, TESTADO E **NAO LIGADO**
# ---------------------------------------------------------------------------
#
# ATENCAO: `ficha_ainda_vale()` NAO e chamada por nenhum modulo. A decisao
# de nao ligar foi tomada em 23/08/2026, depois de analisar as trocas.
# Se voce vier ligar isto, leia os quatro motivos antes.
#
# 1. ESCONDE MELHORIA. Se a extracao de editora melhora e o acervo esta
#    em cache, a melhoria nao alcanca ninguem. Tentamos resolver com a
#    assinatura do programa - mas ai QUALQUER mudanca de codigo invalida
#    TUDO, e o cache quase nunca serve. Ou e agressivo e esconde, ou e
#    conservador e nao economiza. Nao ha meio-termo confortavel.
#
# 2. CRIA UM SEGUNDO CAMINHO. Passa a existir "o que o programa produz" e
#    "o que esta guardado". Quando divergem, ninguem sabe qual esta vendo.
#    Boa parte dos erros deste projeto foi exatamente isso - a mesma
#    informacao em dois lugares que precisavam concordar. Ver
#    PROCEDIMENTO.md, item 7.
#
# 3. INTERAGE MAL COM A REVISAO MANUAL. Se o cache pular um item cuja
#    revisao acabou de mudar, ele anula a decisao humana - justamente o
#    problema que o reprocessamento por revisao aprovada resolveu. Da para
#    proteger, mas seria mais uma regra sutil num ponto que ja tem varias.
#
# 4. O GANHO E MENOR DO QUE PARECE. O gargalo real e OCR e consulta
#    externa, e os dois JA tem protecao propria: o ocrmypdf usa
#    --skip-text e nao refaz pagina que tem texto; as consultas guardam
#    cache em disco (_controle/cache-*). O que sobraria para economizar e
#    a parte barata.
#
# QUANDO RECONSIDERAR: se um lote grande - centenas de livros de uma vez -
# tornar o reprocessamento incomodo. Ai MEÇA PRIMEIRO onde o tempo vai.
# Pode ser que a resposta seja outra, e nao cache. Na epoca desta decisao
# havia 8 arquivos em disco: o custo era zero e o risco nao era.
#
# A funcao fica aqui, testada, para nao ser reescrita do zero depois.
#
# ---------------------------------------------------------------------------
#
# Cada livro leva minutos: OCR, capa, releitura de imagem, consultas. Um
# reprocessamento refaz tudo do zero, mesmo quando nada mudou. Com
# milhares de livros isso seria a diferenca entre horas e dias.
#
# A ficha so pode ser reaproveitada quando DUAS coisas continuam iguais:
#
#   1. o PDF - conferido pelo SHA-256, nao pela data nem pelo tamanho;
#   2. o PROGRAMA - porque uma regra nova precisa valer para o acervo
#      inteiro. Foi o caso desta rodada: a extracao de editora mudou, e
#      reaproveitar fichas antigas esconderia a melhoria.
#
# A assinatura do programa e o hash dos modulos que decidem metadado. Ela
# muda sozinha a cada alteracao de codigo, entao ninguem precisa lembrar
# de invalidar cache - o erro classico desse tipo de otimizacao.

_ASSINATURA_PROGRAMA = None


def assinatura_do_programa():
    """Hash dos modulos que decidem metadados. Muda a cada alteracao."""
    global _ASSINATURA_PROGRAMA
    if _ASSINATURA_PROGRAMA:
        return _ASSINATURA_PROGRAMA
    import hashlib as _h
    pasta = os.path.dirname(os.path.abspath(__file__))
    h = _h.sha256()
    for nome in sorted(("preparar-livros.py", "identificar.py",
                        "conferir_identidade.py", "ler-capa.py",
                        "periodicos-conhecidos.json",
                        "titulos-ruidosos-conhecidos.json")):
        caminho = os.path.join(pasta, nome)
        try:
            with open(caminho, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(nome.encode())          # ausente tambem e um estado
    _ASSINATURA_PROGRAMA = h.hexdigest()[:16]
    return _ASSINATURA_PROGRAMA


def ficha_ainda_vale(ficha, hash_pdf):
    """A ficha pode ser reaproveitada sem reprocessar o livro?

    Conservador de proposito: na duvida, reprocessa. Um reprocessamento a
    mais custa minutos; uma ficha desatualizada custa um registro errado
    no acervo.
    """
    if not isinstance(ficha, dict) or not hash_pdf:
        return False, "sem ficha anterior"
    if ficha.get("hash_sha256") != hash_pdf:
        return False, "o PDF mudou"
    gravada = ficha.get("assinatura_programa", "")
    if not gravada:
        return False, "ficha anterior ao controle de versão do programa"
    if gravada != assinatura_do_programa():
        return False, "o programa mudou desde esta ficha"
    if not ficha.get("titulo"):
        return False, "ficha anterior incompleta"
    return True, "PDF e programa inalterados"


# ---------------------------------------------------------------------------
# PROCEDENCIA DO ARQUIVO  (melhoria 4)
# ---------------------------------------------------------------------------
#
# Dois arquivos do lote enganavam sobre o que eram, e nada avisava:
#
#   Lloyd-Jones - captura de paginas de um site. Traz "<- Previous First
#   Next ->" e a URL em toda folha. O conteudo e a obra completa, mas nao
#   ha folha de rosto, creditos nem ISBN: os dados da edicao NAO EXISTEM
#   neste arquivo, e insistir neles e perda de tempo.
#
#   Credo Ortodoxo 1679 - declara "Machine Translated by Google". O texto
#   em portugues nao e edicao publicada: e traducao automatica. Citar dele
#   como se fosse edicao brasileira seria erro de catalogacao.
#
# Sao marcas literais, faceis de achar, e mudam o que se pode AFIRMAR
# sobre a obra. Registrar a procedencia e mais honesto que corrigir.

MARCAS_PROCEDENCIA = (
    (r"(?i)machine\s+translated\s+by\s+google|traduzido\s+automaticamente\s+pelo\s+google",
     "tradução automática",
     "o próprio arquivo declara tradução automática do Google: o texto não é "
     "edição publicada nesta língua"),
    (r"(?i)<-\s*previous\s+first\s+next\s*->|previous\s*\|\s*first\s*\|\s*next",
     "captura de site",
     "o arquivo tem navegação de página web em cada folha: é captura de site, "
     "não edição impressa - os dados da edição não constam"),
    (r"(?i)scribd\.com|baixado\s+(?:do|em)\s+scribd",
     "cópia do Scribd",
     "arquivo obtido do Scribd: o nome e os metadados podem não ser os da obra"),
    (r"(?i)c[oó]pia\s+(?:digital\s+)?n[aã]o\s+comercial|"
     r"non[- ]commercial\s+(?:digital\s+)?copy",
     "cópia digital não comercial",
     "o arquivo declara ser cópia digital não comercial: ele deve ser "
     "tratado como documento derivado, sem atribuir a si o ISBN da fonte"),
)


def procedencia_do_arquivo(texto):
    """Marcas que dizem de ONDE o arquivo veio.

    Devolve lista de (tipo, explicacao). Nao corrige nada: registra, para
    que a ficha nao afirme sobre a edicao mais do que o arquivo permite.
    """
    achados, vistos = [], set()
    for padrao, tipo, explicacao in MARCAS_PROCEDENCIA:
        if tipo in vistos:
            continue
        if re.search(padrao, texto or "", re.S):
            vistos.add(tipo)
            achados.append((tipo, explicacao))
    # Duas URLs em copyright, bibliografia ou publicidade são normais em um
    # livro e não provam captura de site. Só tratamos URLs como procedência
    # quando o mesmo domínio reaparece em ao menos três linhas e o arquivo
    # não possui sinais editoriais de livro. A navegação Previous/Next acima
    # continua sendo prova direta, independentemente desta regra.
    texto = texto or ""
    urls_linha = re.findall(r"(?im)^\s*https?://([^/\s]+)[^\s]*\s*$", texto)
    contagem_dominios = collections.Counter(x.lower() for x in urls_linha)
    sinais_livro = re.search(
        r"(?i)\bISBN\b|\bCopyright\b|[©℗]|Dados\s+(?:Internacionais\s+)?"
        r"de\s+Cataloga[çc][aã]o|Ficha\s+Catalogr[aá]fica", texto)
    if ("captura de site" not in vistos and not sinais_livro
            and any(qtd >= 3 for qtd in contagem_dominios.values())):
        achados.append((
            "captura de site",
            "o mesmo domínio aparece como URL em pelo menos três folhas e "
            "o arquivo não traz sinais editoriais de livro"))
    return achados


def material_institucional_de_igreja(texto, inicio):
    """Material interno de igreja: devolve o tipo, ou "" se nao for.

    So decide quando NAO ha ISBN nem editora. Livro comercial sobre
    ministerio tem os dois, e essa ausencia e a diferenca entre "obra
    publicada" e "material produzido pela propria casa".
    """
    if not inicio:
        return ""
    if isbns_no_texto_simples(texto):
        return ""                       # tem ISBN: e obra publicada
    if ler_copyright(texto).get("editora"):
        return ""                       # tem editora: idem

    cabeca = inicio[:2500]
    for padrao, contexto, tipo in INSTITUCIONAL:
        if re.search(padrao, cabeca) and re.search(contexto, cabeca, re.I):
            return tipo
    return ""


def isbns_no_texto_simples(texto):
    """ISBN valido em qualquer lugar do texto - so para dizer se existe."""
    for m in re.finditer(r"ISBN[^0-9]{0,12}([\d][\d\s\-–—]{7,20}[\dXx])",
                         texto or "", re.I):
        if isbn_valido(m.group(1)):
            return True
    return False


def metadados_artigo_paginas(paginas, nome=""):
    """Extrai cabeçalho de artigo sem confundi-lo com o início do resumo."""
    inicio = "\n".join(paginas[:3])
    periodico = metadados_artigo_periodico(paginas)
    pagina_inicial = paginas[0] if paginas else ""
    antes_resumo = re.split(r"(?im)^\s*RESUMO\s*$", inicio, maxsplit=1)[0]
    candidatas = []
    titulo_web = ""
    autor_web = ""
    # Uma impressão do navegador normalmente repete a URL no rodapé. Ela é
    # a melhor evidência de que estamos diante de um artigo web e permite
    # distinguir a instituição responsável sem depender do OCR do logotipo.
    urls = re.findall(r"https?://[^\s<>]+", inicio)
    url_artigo = next((u.rstrip(".,;:)]}") for u in urls
                       if re.search(r"(?i)/(?:articles?|news)/", u)), "")
    fonte_web = ""
    if re.search(r"(?i)academic\.tyndalehouse\.com", url_artigo):
        fonte_web = "Tyndale House"
    elif re.search(r"(?i)(?:news\.)?americanbible\.org", url_artigo):
        fonte_web = "American Bible Society"
    elif url_artigo:
        dominio = re.sub(r"(?i)^https?://(?:www\.)?", "", url_artigo)
        fonte_web = dominio.split("/", 1)[0]

    # PDFs impressos pelo navegador conservam a manchete no cabeçalho de
    # todas as páginas. Ela é mais segura que o banner e que o primeiro
    # parágrafo, e também preserva o título completo quando o H1 foi abreviado.
    cabecalho_impressao = re.search(
        r"(?im)^\s*\d{2}/\d{2}/\d{4},\s*\d{1,2}:\d{2}\s+(.{8,180}?)\s*$",
        pagina_inicial)
    if cabecalho_impressao and (fonte_web or re.search(
            r"(?i)Receive accessible biblical scholarship|"
            r"American Bible Society News", pagina_inicial)):
        titulo_web = " ".join(cabecalho_impressao.group(1).split()).strip()
        # Cabeçalhos de sites acrescentam o nome da seção e da instituição.
        # O trecho anterior a "Articles" é a manchete bibliográfica.
        titulo_web = re.split(
            r"\s+\|\s+(?:Articles?|News|Blog)\b", titulo_web,
            maxsplit=1, flags=re.I)[0].strip(" -|–—")

    # Na Tyndale, o H1 aparece depois de ARTICLE e da data. Ele pode ser
    # diferente do título do cabeçalho do navegador e por isso prevalece.
    linhas = [" ".join(x.split()).strip() for x in pagina_inicial.splitlines()]
    indice_article = next((i for i, x in enumerate(linhas)
                           if x.upper() == "ARTICLE"), -1)
    bloco_apresentacao = ""
    if indice_article >= 0:
        pos = indice_article + 1
        while pos < len(linhas) and not linhas[pos]:
            pos += 1
        if pos < len(linhas) and re.fullmatch(
                r"(?i)(?:\d{1,2}(?:ST|ND|RD|TH)\s+)?"
                r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|"
                r"SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(?:19|20)\d{2}",
                linhas[pos]):
            pos += 1
        while pos < len(linhas) and not linhas[pos]:
            pos += 1
        titulo_h1 = []
        while pos < len(linhas) and linhas[pos]:
            if (re.match(r"(?i)^https?://", linhas[pos])
                    or re.search(
                        r"(?i)\b(?:follows|delves|looks|explores|unpacks|takes|"
                        r"considers|examines|asks|seeks|investigates|traces|"
                        r"discusses|reflects|outlines|explains|reviews)\b",
                        linhas[pos])):
                break
            titulo_h1.append(linhas[pos])
            pos += 1
        candidato_h1 = " ".join(titulo_h1).strip(" .,:;-|–—")
        if titulo_bibliograficamente_plausivel(candidato_h1):
            titulo_web = candidato_h1
        while pos < len(linhas) and not linhas[pos]:
            pos += 1
        apresentacao = []
        while pos < len(linhas) and linhas[pos]:
            apresentacao.append(linhas[pos])
            pos += 1
        bloco_apresentacao = " ".join(apresentacao)

    # A chamada introdutória costuma começar pelo autor ou mencioná-lo antes
    # de um verbo editorial. Só aceitamos nomes próprios imediatamente antes
    # desses verbos; o restante da frase nunca entra no campo de autoria.
    texto_autoria = bloco_apresentacao or pagina_inicial
    verbo_autoria = (r"follows|delves|looks|explores|unpacks|takes|considers|"
                     r"examines|asks|seeks|investigates|traces|discusses|"
                     r"reflects|outlines|explains|reviews|sets\s+out")
    nome_pessoa = (r"[A-Z][A-Za-zÀ-ÿ'’.-]+(?:[ \t]+(?:de|da|do|dos|das|"
                   r"van|von|[A-Z][A-Za-zÀ-ÿ'’.-]+)){1,4}")
    achado_autor = re.search(
        rf"\b({nome_pessoa})[ \t]+(?i:{verbo_autoria})\b", texto_autoria)
    if achado_autor:
        candidato_autor = achado_autor.group(1).strip()
        # A busca ignora maiúsculas apenas no verbo; o nome precisa conter
        # pelo menos duas palavras iniciadas em maiúscula no texto original.
        if len(re.findall(r"(?:^|\s)[A-Z][A-Za-zÀ-ÿ'’.-]+", candidato_autor)) >= 2:
            autor_web = sobrenome_virgula(candidato_autor)

    if fonte_web == "Tyndale House" and not titulo_web and nome:
        # O nome do arquivo é pista apenas para título, nunca para autoria.
        titulo_web = re.sub(r"(?i)\.pdf$", "", nome).replace("_", ":")
    cabecalho_web = re.search(
        r"(?ims)^\s*(.{12,300}?)\s*\n\s*Por\s+([^\n|]{3,80})\s*\|\s*"
        r"\d+\s+(?:minutos?|horas?|dias?|semanas?|meses?|anos?)\s+atr[aá]s\s*$",
        antes_resumo)
    if cabecalho_web:
        titulo_web = " ".join(cabecalho_web.group(1).split()).strip(" -|\u2022")
        autor_web = sobrenome_virgula(cabecalho_web.group(2).strip())
    if not autor_web:
        autor_rotulo = re.search(
            r"(?im)^\s*(?:autor(?:es)?|author(?:s)?)\s*[:\\-–—]\s*"
            r"([^\n|]{3,100})\s*$",
            antes_resumo)
        if autor_rotulo:
            candidato = re.sub(
                r"(?i)\s+(?:em|on)\s+\d{1,2}/\d{1,2}/(?:19|20)\d{2}.*$",
                "", autor_rotulo.group(1)).strip(" .,:;-")
            candidato = re.sub(r"(?i)\s*,?\s*(?:Ph\\.?D\\.?|D\\.?Min\\.?)$", "",
                               candidato).strip(" .,:;-")
            if autor_bibliograficamente_plausivel(candidato):
                autor_web = sobrenome_virgula(candidato)
    # Cabeçalho acadêmico clássico: autores antes do título e Abstract logo
    # depois. Guarda o primeiro responsável no campo principal da API.
    if not autor_web:
        autores_academicos = re.search(
            r"(?im)^\s*((?:[A-Z]\.){1,4}\s*[A-Z][A-Za-z'’-]+)\s*&\s*"
            r"((?:[A-Z]\.){1,4}\s*[A-Z][A-Za-z'’-]+)\s*$", antes_resumo)
        if autores_academicos:
            autor_web = sobrenome_virgula(autores_academicos.group(1))
    if not titulo_web and re.search(r"(?im)^\s*Abstract\s*$", inicio):
        linhas = inicio.splitlines()
        indice = next((i for i, linha in enumerate(linhas)
                       if linha.strip().lower() == "abstract"), -1)
        bloco = []
        if indice > 0:
            for linha in reversed(linhas[:indice]):
                limpa = " ".join(linha.split()).strip()
                if not limpa and bloco:
                    break
                if limpa:
                    bloco.append(limpa)
        candidato = " ".join(reversed(bloco)).strip()
        if (candidato and len(candidato) <= 240
                and not re.search(r"(?i)\bISSN\b|\bActa\s+Theologica\b|"
                                  r"^(?:[A-Z]\.){1,4}\s*\w+\s*&", candidato)):
            titulo_web = candidato
    ignorar = re.compile(r"(?i)\b(?:ISSN|ONLINE|IMPRESSO|VOL\.?|VOLUME|"
                         r"REVISTA|JOURNAL|DOI)\b")
    for bruta in antes_resumo.splitlines():
        linha = " ".join(bruta.split()).strip(" -|•")
        letras = [c for c in linha if c.isalpha()]
        if (len(letras) >= 12
                and sum(c.isupper() for c in letras) / len(letras) >= 0.72
                and not ignorar.search(linha)):
            candidatas.append(linha)
    titulo = titulo_web or (" ".join(candidatas[-3:])[:240]
                            if candidatas else "")
    mautor = re.search(
        r"(?im)^\s*(?:Me\.|MSc\.|Dr\.|Dra\.|Prof\.?|Profa\.?)\s*"
        r"([^\n\d]{5,80}?)\s*\d*\s*$", antes_resumo)
    autor = (autor_web or
             (sobrenome_virgula(mautor.group(1).strip()) if mautor else ""))
    mdata = re.search(
        r"(?i)\b(?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|"
        r"agosto|setembro|outubro|novembro|dezembro)\s*[|/-]?\s*((?:19|20)\d{2})",
        inicio)
    if not mdata:
        mdata = re.search(r"(?im)^\s*(?:\d{1,2}(?:ST|ND|RD|TH)\s+)?"
                          r"(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|"
                          r"AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+"
                          r"((?:19|20)\d{2})\s*$", inicio)
    if not mdata:
        mdata = re.search(
            r"(?im)^\s*(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|"
            r"AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{1,2},\s*"
            r"((?:19|20)\d{2})\s*$", inicio)
    if not mdata:
        mdata = re.search(r"(?m)\b((?:19|20)\d{2})\s+\d{1,3}\s*\(\d+\)\s*:",
                          inicio)
    missn = re.findall(r"(?i)ISSN\s*[:.-]?\s*(\d{4}[ -]?\d{3}[\dX])", inicio)
    editora = ""
    mrevista = re.search(r"(?i)\b(Revista\s+[A-ZÁ-Ú][A-Za-zÁ-ú ]{3,60})", inicio)
    if mrevista:
        editora = " ".join(mrevista.group(1).split()).strip()
        editora = re.sub(r"(?i)\s+vol(?:ume)?\.?\s*$", "", editora).strip()
    if re.search(r"(?i)academic\.tyndalehouse\.com/explore/articles/", inicio):
        editora = "Tyndale House"
    elif re.search(r"(?i)(?:news\.)?americanbible\.org/article/", inicio):
        editora = "American Bible Society"
    elif re.search(r"(?i)\bActa\s+Theologica\b", inicio):
        editora = "Acta Theologica"
    resultado = {
        "titulo": titulo,
        "autor": autor,
        "ano": mdata.group(1) if mdata else "",
        "editora": editora,
        "issn": "; ".join(dict.fromkeys(x.replace(" ", "") for x in missn)),
        "url": url_artigo,
        "fonte_web": fonte_web,
    }
    # A estrutura editorial da primeira página é mais específica que as
    # heurísticas gerais de caixa alta, que tendem a juntar título, cabeçalho
    # do periódico e nome do autor.
    for campo, valor in periodico.items():
        if valor:
            resultado[campo] = valor
    return resultado


def alertas_plausibilidade_metadados(titulo, autor, editora):
    """Impede que fragmentos de OCR sejam tratados como tombo confiavel."""
    alertas = []
    nt = identificar.normalizar(titulo or "")
    na = identificar.normalizar((autor or "").replace(",", " "))
    ne = identificar.normalizar(editora or "")
    motivo_ruido_conhecido = identificar_titulo_ruidoso(titulo)
    if motivo_ruido_conhecido:
        alertas.append(
            f"titulo consta na memoria de ruidos: {motivo_ruido_conhecido}")
    motivo_autor_ruidoso = identificar_autor_ruidoso(autor)
    if motivo_autor_ruidoso:
        alertas.append(
            f"autor consta na memoria de ruidos: {motivo_autor_ruidoso}")
    if re.search(r"\b(?:camara brasileira do livro|dados de catalogacao|c ip)\b", nt):
        alertas.append("titulo contaminado por texto da ficha catalografica")
    if re.search(
            r"(?i)\b(?:test\s+target|image\s+evaluation|microfiche|"
            r"microreproductions?|cihm|icmh|lura\s*document|"
            r"digitized\s+by\s+the\s+internet\s+archive)\b",
            titulo or ""):
        alertas.append("titulo parece página técnica de digitalização")
    if re.match(r"(?i)^\s*(?:categoria|assunto|classifica[çc][aã]o)\s*:",
                titulo or ""):
        alertas.append("titulo parece rotulo de categoria ou classificacao")
    if re.search(r"\.(?:indd|p65|docx?|pdf)\b", (titulo or ""), re.I):
        alertas.append("titulo parece nome de arquivo de editoração")
    if re.fullmatch(
            r"(?i)\s*(?:apresenta[çc][aã]o\s+do\s+powerpoint|"
            r"microsoft\s+(?:word|powerpoint)|untitled|sem\s+t[ií]tulo|"
            r"documento\s*\d*)\s*", titulo or ""):
        alertas.append("titulo parece metadado genérico do aplicativo de origem")
    if re.search(r"[$*]", titulo or ""):
        alertas.append("titulo contem simbolos suspeitos de OCR")
    if re.fullmatch(r"\s*(?:19|20)\d{2}\s*", titulo or ""):
        alertas.append("titulo contem somente um ano")
    if re.fullmatch(
            r"(?i)\s*(?:aula|estudo|li[çc][aã]o|classe)\s*"
            r"(?:n[ºo.]?\s*)?\d{1,3}\s*", titulo or ""):
        alertas.append("titulo didatico generico sem identificacao bibliografica")
    if re.search(r"(?i)\bCRB\s*[-–]?\s*\d", titulo or ""):
        alertas.append("titulo capturou o nome do catalogador da ficha")
    if re.search(
            r"(?i)\b(?:todos\s+os\s+direitos\s+reservados|"
            r"proibida\s+a\s+reprodu[çc][aã]o|reprodu[çc][aã]o\s+total\s+ou\s+parcial|"
            r"autoriza[çc][aã]o\s+pr[eé]via|lei\s+n?[.°º\s]*9?\.?610)\b",
            titulo or ""):
        alertas.append("titulo capturou aviso de direitos autorais")
    if re.search(
            r"(?i)(?:^|\b)(?:este|esse)\s+e-?book\s+(?:foi\s+)?"
            r"disponibilizado\b|"
            r"\btotalmente\s+gratuito\s+para\s+voc[êe]\b|"
            r"^\s*(?:fa[çc]a\s+(?:uma\s+)?doa[çc][aã]o|siga-nos|"
            r"clique\s+aqui|acesse|visite)\b|"
            r"\b(?:instagram|youtube|paypal)\.com\b|"
            r"\b(?:leia|aponte).{0,35}\bQR\s*Code\b",
            titulo or ""):
        alertas.append("titulo parece chamada promocional ou instrucao ao leitor")
    palavras_titulo = (titulo or "").split()
    if len(palavras_titulo) > 35 or len(titulo or "") > 240:
        alertas.append("titulo parece paragrafo do texto")
    if (len(palavras_titulo) >= 8 and re.search(
            r"(?i)\b(?:a|à|ao|aos|as|com|da|das|de|do|dos|e|em|na|nas|no|"
            r"nos|para|pela|pelas|pelo|pelos|por|the|of|to|with|and)\s*$",
            titulo or "")):
        alertas.append("titulo parece fragmento truncado do texto")
    conectores_unitarios = {"a", "o", "e", "y"}
    if sum(len(p.strip(".,;:()")) == 1
           and identificar.normalizar(p.strip(".,;:()")) not in conectores_unitarios
           for p in palavras_titulo) >= 2:
        alertas.append("titulo com fragmentos de OCR")
    if (re.match(r"^\s*[B-DF-HJ-NP-Z]\s+[A-ZÀ-Ü]", titulo or "")
            and len(palavras_titulo) >= 5):
        alertas.append("titulo com fragmento isolado no inicio")
    if ((titulo or "").count("#") >= 3
            or re.search(r"(?i)\bLivro\s+adotado\s+como\s+Manual\s+de\s+Estudo\b",
                         titulo or "")):
        alertas.append("titulo parece lista de colecao ou aviso editorial")
    # Endossos, dedicatórias e parágrafos iniciais costumam ser devolvidos
    # como título quando a capa não possui camada textual. Um título longo
    # ainda pode ser válido, mas não deve ter forma clara de frase narrativa.
    if (len(palavras_titulo) >= 10 and re.match(
            r"(?i)^\s*(?:por\s+causa|fa[çc]a|este\s+livro|o\s+novo\s+livro|"
            r"qualquer\s+pessoa|quando|porque|espero\s+que|dedico|agrade[çc]o)\b",
            titulo or "")):
        alertas.append("titulo parece frase do texto, endosso ou dedicatória")
    if titulo and titulo[:1].islower() and len(palavras_titulo) >= 7:
        alertas.append("titulo parece continuação de parágrafo")
    if (len(palavras_titulo) >= 12 and re.search(
            r"(?i)\b(?:apresenta[çc][aã]o|com\s+pref[aá]cio|pref[aá]cio\s+de)\b",
            titulo or "")):
        alertas.append("titulo incorporou chamada editorial da capa")
    ruido_autor = {
        "comentario", "biblico", "hermeneutica", "estudos", "conhecido",
        "testamento", "vangelho", "cristo", "capitulo", "sumario", "tcc",
        "revista", "pdf", "vocabulario", "bibliografia", "indice",
        "organizacao", "organizador", "coordenacao", "coordenador",
        "missionarios", "figuras", "livro", "digital", "ebook",
        "diario", "diarios", "sermon", "sermones", "tomo", "volume",
        "uso", "pessoal", "consentimento", "proprietario", "direitos",
        "isencao", "responsabilidade",
    }
    partes_autor = {p for p in na.split() if len(p) > 2}
    if (re.search(r"(?i)(?:^|,\s*)(?:por|de|do|da|organiza[çc][aã]o|"
                  r"coordena[çc][aã]o)\s*:?\s+", autor or "")
            or partes_autor & ruido_autor):
        alertas.append("autor parece fragmento de texto, função ou título")
    if autor and (len(na) < 5 or any(ch.isdigit() for ch in autor)):
        alertas.append("autor bibliograficamente implausivel")
    if (len((autor or "").split()) > 8 or re.search(
            r"(?i)\b(?:qualquer\s+pessoa|desde\s+que|leitura\s+incr[ií]vel|"
            r"deseja\s+prosperar|horas\s+que|novo\s+livro)\b", autor or "")):
        alertas.append("autor parece frase extraída do texto")
    if autor and re.search(
            r"(?i)\b(?:follows|delves|looks|explores|unpacks|takes|considers|"
            r"examines|asks|seeks|investigates|traces|discusses|reflects|"
            r"outlines|explains|reviews|starting\s+out)\b", autor):
        alertas.append("autor incorporou a chamada introdutória do artigo")
    if autor and re.search(r"[?:]", autor):
        alertas.append("autor contém pontuação típica de título ou frase")
    if autor and ("(" in autor or ")" in autor or re.search(
            r"(?i)\b(?:ora[çc][aã]o|eleitos|livres|editora|publica[çc][õo]es)\b",
            autor)):
        alertas.append("autor parece título, editora ou referência bibliográfica")
    # Uma folha de rosto mal segmentada frequentemente junta o nome do autor
    # ao titulo ("Atos Bob Utley") ou devolve somente o autor como titulo
    # ("J. C. Ryle"). Esses casos precisam de outra fonte ou revisao.
    ignorar = {"de", "da", "do", "das", "dos", "e", "and", "por",
               "organizador", "organizada", "editor"}
    tokens_titulo = {p for p in nt.split() if len(p) > 1 and p not in ignorar}
    tokens_autor = {p for p in na.split() if len(p) > 1 and p not in ignorar}
    if autor and tokens_autor and tokens_autor <= tokens_titulo:
        alertas.append("titulo parece conter ou repetir o nome do autor")
    partes_editora = {p for p in ne.split() if len(p) > 2}
    if re.search(r"[$*]", editora or ""):
        alertas.append("editora contem simbolos suspeitos de OCR")
    if editora and re.search(
            r"(?i)\b(?:com\s+a\s+devida\s+autoriza[çc][aã]o|"
            r"enigmas?\s+e|contradi[çc][õo]es|traduzido\s+por|"
            r"todos\s+os\s+direitos)\b", editora):
        alertas.append("editora parece trecho de uma frase editorial")
    editora_institucional = bool(re.search(
        r"(?i)\b(?:association|foundation|ministr(?:y|ies)|associa[çc][aã]o|"
        r"funda[çc][aã]o|instituto|institute)\b", editora or ""))
    if (autor and editora and not editora_institucional
            and len(partes_autor) >= 2 and (
            partes_autor <= partes_editora or partes_editora <= partes_autor)):
        alertas.append("editora coincide com o nome do autor")
    return list(dict.fromkeys(alertas))


def autor_bibliograficamente_plausivel(autor):
    """Rejeita autoria extraida quando ela e claramente um trecho do texto."""
    if not autor:
        return False
    return not any("autor" in alerta for alerta in
                   alertas_plausibilidade_metadados("", autor, ""))


def titulo_bibliograficamente_plausivel(titulo):
    """Distingue um titulo utilizavel de rotulos e fragmentos comuns de OCR."""
    if not titulo or len(titulo.strip()) < 3:
        return False
    return not any("titulo" in alerta for alerta in
                   alertas_plausibilidade_metadados(titulo, "", ""))


def titulo_parece_prosa_ou_artigo_inteiro(titulo):
    """Reconhece quando OCR devolveu corpo de texto no lugar do título."""
    alertas = alertas_plausibilidade_metadados(titulo, "", "")
    return any(
        marca in alerta
        for alerta in alertas
        for marca in (
            "titulo parece paragrafo do texto",
            "titulo parece continuação de parágrafo",
            "titulo parece fragmento truncado do texto",
            "titulo parece frase do texto",
            "titulo capturou aviso de direitos autorais",
        ))


def capa_tecnica_digitalizacao(capa_info):
    """Reconhece capas falsas criadas por microfilme ou digitalização."""
    if not isinstance(capa_info, dict) or not capa_info:
        return False
    textos = []
    for chave in ("titulo", "titulo_visual", "nmAutor0"):
        if capa_info.get(chave):
            textos.append(str(capa_info.get(chave)))
    textos.extend(str(x) for x in (capa_info.get("texto_ocr") or []))
    combinado = "\n".join(textos)
    normalizado = identificar.normalizar(combinado)
    if re.search(
            r"(?i)\b(?:test\s+target|image\s+evaluation|microfiche|"
            r"microreproductions?|cihm|icmh)\b", combinado):
        return True
    tokens = [p for p in normalizado.split() if p]
    if not tokens:
        return False
    tecnicos = {"test", "target", "image", "evaluation", "mt", "cihm",
                "icmh", "microfiche", "microfiches"}
    qtd_tecnicos = sum(1 for p in tokens if p in tecnicos)
    qtd_numericos = sum(1 for p in tokens if re.fullmatch(r"\d+(?:\.\d+)?", p))
    return qtd_tecnicos >= 2 and qtd_numericos >= 2


def editora_bibliograficamente_plausivel(editora):
    if not editora or len(editora.strip()) < 2:
        return False
    if re.search(r"(?i)^\[?\s*(?:s\.?\s*n\.?|sem\s+editora)\s*\]?$",
                 editora.strip()):
        return False
    if parece_nome_cidade_publicacao(editora):
        return False
    if editora.strip()[:1].islower():
        return False
    return not any("editora" in alerta for alerta in
                   alertas_plausibilidade_metadados("", "", editora))


def autores_rotulados_nas_paginas(paginas):
    """Recupera autores que a própria página de créditos identifica.

    É uma evidência muito mais segura que inferir nomes da capa. Aceitamos
    somente os rótulos explícitos ``Author/Authors/Autor/Autores`` e nomes
    bibliograficamente plausíveis; funções de projeto e agradecimentos não
    entram nesta camada.
    """
    texto = "\n".join((paginas or [])[:10] + (paginas or [])[-12:])
    achado = re.search(
        r"(?im)^\s*(?:authors?|autores?)\s*:\s*([^\n|]{3,180})\s*$", texto)
    if not achado:
        return []
    valor = re.split(r"\s{3,}", achado.group(1), maxsplit=1)[0]
    valor = re.sub(r"(?i)\s+(?:illustrations?|design|layout|production)\s*:.*$",
                   "", valor).strip(" .,:;-")
    nomes = re.split(r"\s*(?:;|\s+&\s+|\s+and\s+|\s+e\s+)\s*", valor,
                     flags=re.I)
    saida = []
    for nome in nomes:
        nome = " ".join(nome.split()).strip(" .,:;-")
        nome = re.sub(
            r"(?i),?\s+(?:OFM|OFMCap|SJ|SDB|OP|OSB|CSSR)\.?$", "", nome)
        if autor_bibliograficamente_plausivel(nome):
            normalizado = sobrenome_virgula(nome)
            if normalizado and normalizado not in saida:
                saida.append(normalizado)
    return saida


def escolher_editora_final(tipo_documento, editoras,
                            api_por_isbn_exato=False):
    """Aplica a precedência editorial apropriada a cada tipo documental."""
    if tipo_documento == "artigo" and editoras.get("artigo"):
        return editoras["artigo"]
    if tipo_documento in TIPOS_ACADEMICOS and editoras.get("academico"):
        return editoras["academico"]
    if api_por_isbn_exato and editoras.get("api"):
        return editoras["api"]
    return (editoras.get("cip") or editoras.get("copyright")
            or editoras.get("capa") or editoras.get("artigo")
            or editoras.get("academico") or editoras.get("api")
            or editoras.get("folha_word") or editoras.get("folha_rosto")
            or editoras.get("institucional", ""))


def limpar_titulo_com_editora_e_serie(titulo, editora):
    """Retira selo inicial e identificação de série anexados ao título."""
    valor = " ".join(str(titulo or "").split()).strip(" .,:;-")
    valor = re.sub(
        r"(?i)\s+No\.?\s*\d+[A-Z]?\s*[-–—]\s*[^:;]{2,80}\s+Series\s*$",
        "", valor).strip(" .,:;-")
    selo = re.sub(
        r"(?i)\s+(?:Institute|Instituto|Press|Books|Publications|"
        r"Publica[çc][õo]es)\s*$", "", str(editora or "")).strip()
    if selo and len(selo.split()) <= 3:
        valor = re.sub(rf"(?i)^\s*{re.escape(selo)}\s+(?=\S+\s+\S+)",
                       "", valor).strip(" .,:;-")
    return valor


def similaridade_titulos(a, b):
    a = identificar.normalizar(a or "")
    b = identificar.normalizar(b or "")
    if not a or not b:
        return 0.0
    sequencia = difflib.SequenceMatcher(None, a, b).ratio()
    ta = {x for x in a.split() if len(x) > 2}
    tb = {x for x in b.split() if len(x) > 2}
    tokens = len(ta & tb) / max(1, len(ta | tb))
    return max(sequencia, tokens)


def titulo_local_e_fragmento_do_confirmado(local, confirmado):
    """Reconhece capas ou OCR truncados diante de um ISBN exato."""
    local_n = identificar.normalizar(local or "")
    confirmado_n = identificar.normalizar(confirmado or "")
    if not local_n or not confirmado_n or local_n == confirmado_n:
        return False
    vazias = {"a", "as", "o", "os", "de", "da", "das", "do", "dos", "e",
              "em", "um", "uma", "que", "the", "of", "and"}
    tl = [p for p in local_n.split() if len(p) > 1 and p not in vazias]
    tc = [p for p in confirmado_n.split() if len(p) > 1 and p not in vazias]
    if len(tl) <= 2 and len(tc) >= 3:
        return (confirmado_n.startswith(local_n)
                or set(tl).issubset(set(tc)))
    comuns = set(tl) & set(tc)
    return len(tl) >= 3 and len(comuns) >= 2 and len(comuns) / len(tl) >= 0.6


def titulo_documental_sem_ruido(titulo_extraido, titulo_nome):
    """Prefere o nome limpo quando o extrator capturou sumário ou prosa.

    Documentos não têm necessariamente folha de rosto. Neles, promover o
    primeiro bloco visual pode transformar itens inteiros de um sumário em
    título. O nome do arquivo só vence quando é bibliograficamente plausível
    e o extraído traz um alerta objetivo de ruído.
    """
    if not titulo_bibliograficamente_plausivel(titulo_nome):
        return titulo_extraido, False
    alertas = alertas_plausibilidade_metadados(titulo_extraido, "", "")
    ruido = any(
        marca in alerta
        for alerta in alertas
        for marca in ("titulo com fragmentos de OCR", "titulo parece frase",
                      "titulo parece sumario", "titulo contem rotulo",
                      "titulo parece chamada promocional",
                      "titulo parece metadado genérico",
                      "titulo didatico generico",
                      "titulo consta na memoria de ruidos"))
    if not titulo_extraido or ruido:
        return titulo_nome, True
    return titulo_extraido, False


PALAVRAS_FRACAS_TITULO = {
    "a", "as", "o", "os", "um", "uma", "uns", "umas", "de", "da", "das",
    "do", "dos", "e", "em", "no", "na", "nos", "nas", "por", "para",
    "com", "sem", "ao", "aos", "the", "of", "and", "for", "in", "to",
    "by", "with", "el", "la", "los", "las", "un", "una", "del", "y",
}


def tokens_fortes_titulo(texto):
    return [
        p for p in identificar.normalizar(texto or "").split()
        if len(p) > 2 and p not in PALAVRAS_FRACAS_TITULO
        and not re.fullmatch(r"\d+", p)
    ]


def titulo_orientado_pelo_nome_arquivo(titulo_extraido, titulo_nome):
    """Usa o nome limpo do arquivo como bússola, não como fonte soberana.

    A capa e as primeiras páginas muitas vezes trazem só parte do título
    visível; o nome do arquivo, apesar de poluído por OCR/cópia/versão, costuma
    preservar a forma completa. Só promovemos o nome quando ele é plausível e
    contém os tokens fortes do título lido localmente.
    """
    titulo_nome = limpar_titulo_bibliografico(titulo_nome)
    if not titulo_bibliograficamente_plausivel(titulo_nome):
        return titulo_extraido, False
    extraido = limpar_titulo_bibliografico(titulo_extraido)
    if not extraido:
        return titulo_nome, True
    te = tokens_fortes_titulo(extraido)
    tn = tokens_fortes_titulo(titulo_nome)
    if len(te) < 2 or len(tn) < 2 or len(tn) <= len(te):
        return titulo_extraido, False
    conjunto_nome = set(tn)
    confirmados = [t for t in te if t in conjunto_nome]
    if len(confirmados) >= 2 and len(confirmados) / max(1, len(te)) >= 0.75:
        return titulo_nome, True
    return titulo_extraido, False


def limpar_editora_bibliografica(valor):
    valor = " ".join(str(valor or "").split()).strip(" ,.;:-")
    # Alguns registros legados da CBL trazem lixo antes do nome e um
    # asterisco de migração depois dele ("Aneas Edições Loyola*").
    # Canonicalizamos a entidade conhecida sem propagar esses artefatos.
    if "edicoes loyola" in identificar.normalizar(valor):
        return "Edições Loyola"
    valor = re.split(
        r"(?i)\s+(?:com\s+a\s+devida\s+autoriza[çc][aã]o|"
        r"tem,?\s+assim,?\s+(?:grande\s+)?prazer|"
        r"todos\s+os\s+direitos|traduzido\s+por)\b", valor, maxsplit=1)[0]
    valor = re.split(r"(?i)\s*[-–:]?\s*ISBN\b", valor, maxsplit=1)[0]
    valor = re.sub(r"\s*,\s*(?:1[5-9]|20)\d{2}\s*$", "", valor)
    return valor.strip(" ,.;:-")


def editora_institucional_nas_paginas(paginas):
    """Recupera editoras explicitamente declaradas nas paginas iniciais."""
    inicio = "\n".join((paginas or [])[:10] + (paginas or [])[-12:])
    assinatura = editora_por_assinatura_ocr(inicio)
    if assinatura:
        # O nome de uma editora dentro de nota ou referência bibliográfica
        # identifica a obra CITADA, não o PDF que estamos catalogando. O caso
        # real era "Editora Vida, 2009, pag. 809" numa nota de rodapé. Só
        # aceitamos a assinatura conhecida quando ao menos uma ocorrência
        # aparece fora da forma autor/título/cidade/editora/ano/página.
        linhas_assinatura = [
            linha for linha in inicio.splitlines()
            if identificar.normalizar(assinatura) in identificar.normalizar(linha)
        ]
        somente_citacoes = bool(linhas_assinatura) and all(
            re.search(
                r"(?i)(?:\b(?:19|20)\d{2}\b.{0,25}\b(?:p(?:ag)?s?\.?|"
                r"páginas?)\s*\d+|^[A-ZÀ-Ü][A-ZÀ-Ü'. -]+,\s*"
                r"[A-ZÀ-Ü])",
                linha)
            for linha in linhas_assinatura
        )
        if not somente_citacoes:
            return assinatura
    if re.search(r"(?i)Associa[çc][aã]o\s+de\s+Semin[aá]rios\s+"
                 r"Teol[oó]gicos\s+Evang[eé]licos|(?:^|\n)\s*ASTE\s*(?:\n|$)",
                 inicio):
        return "Associação de Seminários Teológicos Evangélicos (ASTE)"
    m = re.search(
        r"(?im)^\s*(?:Publicado(?:\s+no\s+Brasil)?\s+por|Publicado\s+pel[oa]\s*:|"
        r"Todos\s+os\s+direitos[^\n]{0,50}?reservados\s+por|"
        r"Todos\s+os\s+direitos\s+autorais\s+foram\s+cedidos\s+a)\s*:?\s*"
        r"([^\n]{3,100})", inicio)
    if m:
        return " ".join(m.group(1).split()).strip(" .;:")
    # Selo declarado diretamente na folha de rosto, sem o verbo publicar.
    for pagina in (paginas or [])[:8]:
        for linha in pagina.splitlines():
            valor = " ".join(linha.split()).strip(" .;:|-")
            if (3 <= len(valor) <= 80 and re.match(
                    r"(?i)^(?:editora|editorial|ediciones|edi[çc][õo]es|"
                    r"publicaciones|publica[çc][õo]es|"
                    r"[A-Z][A-Za-z&'. -]+\s+Press)\b", valor)
                    and not re.search(
                        r"\b(?:19|20)\d{2}\b|\bp(?:ag)?s?\.?\s*\d+",
                        valor, re.I)):
                return valor
    # Instituição repetida como rodapé identifica a responsabilidade pela
    # edição digital mesmo quando ela não usa a palavra "editora".
    linhas_normais = [" ".join(linha.split()).strip(" .;:|-")
                      for pagina in (paginas or [])[:12]
                      for linha in pagina.splitlines() if linha.strip()]
    contagem = collections.Counter(identificar.normalizar(x)
                                   for x in linhas_normais)
    for linha in linhas_normais:
        normal = identificar.normalizar(linha)
        if (contagem[normal] >= 3 and 3 <= len(linha.split()) <= 10
                and re.search(
                    r"(?i)\b(?:Association|Foundation|Ministr(?:y|ies)|"
                    r"Associa[çc][aã]o|Funda[çc][aã]o)\b", linha)):
            return linha
    # Patrocínio editorial explícito é fonte; o editor geral que aparece
    # depois continua registrado apenas em sua função correta.
    patrocinio = re.search(
        r"(?im)^\s*(?:(?:Edi[çc][aã]o|Edici[oó]n)\s+)?"
        r"(?:auspiciada|patrocinada)\s+por\s*$\s*"
        r"^\s*([^\n]{3,90}(?:Foundation|Association|Fundaci[oó]n|"
        r"Funda[çc][aã]o)[^\n]*)$",
        "\n".join((paginas or [])[:8]))
    if patrocinio:
        return " ".join(patrocinio.group(1).split()).strip(" .;:")
    # Institutos e selos podem se identificar sem o verbo "publicado":
    # "Lumko Institute / Lumko is the Pastoral Institute...". Exigimos que
    # o mesmo nome reapareça na descrição ou no aviso de permissão para não
    # transformar qualquer instituição mencionada no livro em editora.
    organizacoes = re.findall(
        r"(?im)^\s*([A-ZÀ-Ü][A-Za-zÀ-ÿ&'’. -]{1,70}\s+"
        r"(?:Institute|Instituto|Press|Books|Publications|Publica[çc][õo]es))\s*$",
        inicio)
    for organizacao in organizacoes:
        base = re.sub(
            r"(?i)\s+(?:Institute|Instituto|Press|Books|Publications|"
            r"Publica[çc][õo]es)\s*$", "", organizacao).strip()
        if base and re.search(
                rf"(?i)\b{re.escape(base)}\b.{{0,100}}(?:is\s+the|é\s+o|"
                rf"permission\s+in\s+writing\s+from|permiss[aã]o)", inicio):
            return " ".join(organizacao.split()).strip(" .;:")
    return ""


def deve_reclassificar_documento_como_livro(tipo_documento, documental,
                                             isbn_confirmado, api,
                                             paginas_pdf):
    """Corrige um documento genérico quando uma ficha exata prova o livro.

    Uma URL solta não pode vencer ISBN impresso, obra longa e um catálogo
    estruturado que devolve título, autor e editora. Tipos explicitamente
    reconhecidos (artigo, tese, revista etc.) não passam por esta regra.
    """
    if tipo_documento != "documento" or not isbn_confirmado:
        return False
    if (documental or {}).get("confianca") not in {"baixa", "media", "média"}:
        return False
    try:
        if int(paginas_pdf or 0) < 40:
            return False
    except (TypeError, ValueError):
        return False
    return bool(api.get("titulo") and api.get("autores")
                and api.get("editora"))


# ---------------------------------------------------------------------------
# BLOCO CIP - a ficha que o bibliotecario ja escreveu, impressa no livro
# ---------------------------------------------------------------------------
#
# Presente em 4 dos 12 livros do lote de teste, e de longe a fonte mais
# rica: autor ja em "Sobrenome, Nome", ISBN com a encadernacao declarada,
# assunto LCSH e o DDC - que e o campo cdd, hoje vazio em tudo.
#
#     Nombres: Tripp, Paul David, 1950- autor.
#     Titulo: Plomo : 12 principios ... / Paul David Tripp
#     Descripcion: Wheaton, Illinois : Crossway, 2020.
#     Identificadores: ISBN 9781433567636 (tapa dura) | ISBN ... (pdf)
#     Temas: LCSH: Liderazgo cristiano.
#     Clasificacion: LCC BV652.1 .T755 2020 | DDC 253-dc23
#
# ATENCAO ao titulo: estes PDFs sao traducao automatica, e o CIP foi
# traduzido junto - "Lead" virou "Plomo", o metal. Confiamos no CIP para
# autor, ISBN, DDC, cidade e editora (nomes proprios e numeros sobrevivem
# a traducao); para o titulo, nao.

CIP_INICIO = re.compile(
    r"(?:datos(?:\s+internacionales)?\s+de\s+catalogaci[óo]n\s+en\s+publicaci[óo]n|"
    r"dados(?:\s+internacionais)?\s+de\s+cataloga[çc][ãa]o"
    r"(?:\s+(?:na\s+publica[çc][ãa]o|interna\s+da\s+publica[çc][ãa]o))?|"
    r"CIP\s*[-–]?\s*Brasil\s*[-–:]?\s*cataloga[çc][ãa]o\s+na\s+fonte|"
    r"cataloging[\s-]*in[\s-]*publication|library of congress cataloging)", re.I)

EDITORAS_POR_ASSINATURA = (
    ("Sociedade Bíblica do Brasil", "sociedadebiblicadobrasil"),
    ("Editora Cultura Cristã", "editoraculturacrista"),
    ("Editora Fi", "editorafi"),
    ("JUERP - Junta de Educação Religiosa e Publicações", "juntadeeducacaoreligiosaepublicacoes"),
    ("Editora Vida", "editoravida"),
    ("Editora Mundo Cristão", "editoramundocristao"),
    ("Editora Hagnos", "editorahagnos"),
    ("Editora Fiel", "editorafiel"),
    ("Impacto Publicações", "impactopublicacoes"),
    ("CPAD", "casapublicadoradasassembleiasdedeus"),
    ("Thomas Nelson Brasil", "thomasnelsonbrasil"),
)


def normalizar_rotulos_numeros_ocr(texto):
    """Recompõe rótulos e números que a camada OCR separou caractere a caractere."""
    saida = texto or ""
    for rotulo in ("ISBN", "CDD", "CDU"):
        padrao = r"\s*".join(map(re.escape, rotulo))
        saida = re.sub(padrao, rotulo, saida, flags=re.I)
    # ISBNs, anos e quantidades às vezes chegam como "2 0 1 6". Quatro ou
    # mais algarismos evitam juntar números comuns de capítulos e páginas.
    saida = re.sub(
        r"(?<!\d)(?:\d\s+){3,}\d(?!\d)",
        lambda m: re.sub(r"\s+", "", m.group(0)), saida)
    return saida


def cdd_aproximado_por_cdu(classificacao):
    """Converte uma CDU religiosa em um CDD provável.

    CDU e CDD não são sistemas equivalentes. Para o nosso fluxo, porém, uma
    sugestão ampla é melhor do que deixar uma ficha parada quando a própria
    ficha catalográfica trouxe apenas CDU. A CDU original continua preservada
    em ``classificacao_original``.
    """
    texto = str(classificacao or "").strip()
    if not texto:
        return ""
    bruto = re.sub(r"(?i)^\s*CDU\s*[-:]?\s*", "", texto).strip()
    compacto = re.sub(r"\s+", "", bruto)
    compacto = compacto.replace(",", ".")

    regras = (
        # Regras específicas primeiro.
        (r"^27(?:[-:.]?1|/1|\(1\))", "230"),   # teologia cristã
        (r"^23(?:\b|[^\d])", "230"),
        (r"^27[-:.]?2", "220"),                # Bíblia no cristianismo
        (r"^22(?:\b|[^\d])", "220"),           # Bíblia
        (r"^27[-:.]?23", "232"),               # cristologia
        (r"^27[-:.]?24", "234"),               # salvação/graça
        (r"^27[-:.]?27", "231"),               # Deus
        (r"^27[-:.]?31", "241"),               # ética cristã
        (r"^27[-:.]?36", "248"),               # vida cristã/devocional
        (r"^27[-:.]?4", "240"),                # prática cristã
        (r"^27[-:.]?5", "250"),                # ministério/pastoral
        (r"^27[-:.]?7", "260"),                # igreja/eclesiologia
        (r"^27(?:[-:.]?9|\(091\))", "270"),    # história da igreja
        (r"^28(?:\b|[^\d])", "297"),           # islamismo
        (r"^29(?:\b|[^\d])", "290"),           # outras religiões
        # Regras gerais.
        (r"^2(?:\b|[^\d])", "200"),
        (r"^27", "230"),
    )
    for padrao, cdd in regras:
        if re.search(padrao, compacto, re.I):
            return cdd
    return ""


def aplicar_cdd_sugerido_por_cdu(dados):
    """Preenche CDD aproximado quando só existe CDU."""
    if not isinstance(dados, dict) or dados.get("cdd"):
        return dados
    original = str(dados.get("classificacao_original", "") or "").strip()
    if not re.match(r"(?i)^CDU\b", original):
        return dados
    cdd = cdd_aproximado_por_cdu(original)
    if cdd:
        dados["cdd"] = cdd
        dados["cdd_sugerido"] = cdd
        dados["fonte_cdd_sugerido"] = f"conversão aproximada de {original}"
    return dados


def extrair_classificacao_catalografica(texto):
    """Extrai CDD/CDU mesmo quando o OCR separa letras ou usa travessão."""
    m = re.search(
        r"(?i)\b(C\s*D\s*D|C\s*D\s*U|CDD|CDU)\s*[-:–—]?\s*"
        r"([0-9]{1,3}(?:[.\s-][0-9]+)*)",
        texto or "")
    if not m:
        return "", ""
    rotulo = re.sub(r"\s+", "", m.group(1).upper())
    numero = m.group(2).strip()
    return rotulo, numero


def editora_por_assinatura_ocr(texto):
    compacto = re.sub(r"\s+", "", identificar.normalizar(texto or ""))
    for nome, assinatura in EDITORAS_POR_ASSINATURA:
        if assinatura in compacto:
            return nome
    return ""


def ler_cip(t):
    """Extrai o bloco CIP. Devolve {} quando o livro nao traz um."""
    m = CIP_INICIO.search(t)
    if not m:
        return {}
    bloco = t[m.end(): m.end() + 2600]

    def campo(*rotulos):
        for r in rotulos:
            mm = re.search(rf"{r}\s*:?\s*(.+?)(?:\n\s*[A-ZÁ-Ú][a-zá-ú]+\s*:|\n\n|$)",
                           bloco, re.I | re.S)
            if mm:
                return " ".join(mm.group(1).split())[:300]
        return ""

    d = {"pagina_cip": None}

    # autor: ja vem normalizado, com data de nascimento e o papel escrito
    nomes = campo(r"Nombres", r"Nomes", r"Names")
    if nomes:
        a = re.split(r"\||;", nomes)[0]
        a = re.sub(r",?\s*\d{4}\s*-\s*\d{0,4}", "", a)      # tira as datas
        a = re.sub(r"(?i),?\s*(autor|author|editor|compilador)\.?\s*$", "", a)
        d["autor"] = a.strip(" .,;")

    # mencao de responsabilidade: "Titulo / Fulano; Beltrano, tradutor"
    titulo = campo(r"T[íi]tulo", r"Title")
    if titulo and " / " in titulo:
        resp = titulo.split(" / ", 1)[1]
        partes = [p.strip() for p in resp.split(";")]
        if partes and not d.get("autor"):
            d["autor"] = partes[0]
        for p in partes[1:]:
            if re.search(r"(?i)tradu|translat", p):
                d["tradutor"] = re.sub(r"(?i),?\s*tradu\w*\.?$", "", p).strip()

    # cidade e editora: "Wheaton, Illinois : Crossway, 2020."
    desc = campo(r"Descripci[óo]n", r"Descri[çc][ãa]o", r"Description")
    if desc:
        mm = re.match(r"\s*([^:|]{3,40}?)\s*:\s*([^,|]{2,45}?)\s*,\s*(\d{4})", desc)
        if mm:
            d["cidade"] = mm.group(1).split(",")[0].strip()
            d["editora"] = mm.group(2).strip()
            d["ano"] = mm.group(3)

    # ISBN COM a encadernacao declarada - resolve a regra da brochura sem
    # adivinhacao: "(tapa dura)" e capa dura, "(tp)" e trade paperback
    ident = campo(r"Identificadores", r"Identifiers")
    if ident:
        d["isbns"] = [(c["isbn"], c["rotulo"].lower())
                      for c in candidatos_isbn(ident)]

    # DDC -> o campo cdd, que hoje sai vazio em todos os registros
    clas = campo(r"Clasificaci[óo]n", r"Classifica[çc][ãa]o", r"Classification")
    if clas:
        mm = re.search(r"DDC\s*([0-9]{1,3}(?:\.[0-9]+)?)", clas, re.I)
        if mm:
            d["cdd"] = mm.group(1)

    temas = campo(r"Temas", r"Sujetos", r"Assuntos", r"Subjects")
    if temas:
        d["assuntos"] = "; ".join(
            s.strip(" .") for s in re.sub(r"(?i)lcsh:", "", temas).split("|")
            if s.strip())[:200]

    # ---- CIP brasileiro moderno -----------------------------------------
    # Exemplo real do lote:
    #   R695b Rodovalho, Robson.
    #   A beleza ... / Robson Rodovalho. - Brasilia :
    #   Sara Brasil Edicoes, 2011. 7a edicao. 120p.
    # O texto pode vir de uma pagina dupla e com a pontuacao deformada pelo
    # OCR, por isso a leitura e feita no bloco normalizado.
    plano = " ".join(bloco.split())
    eh_cip_brasileira = bool(re.search(
        r"dados(?:\s+internacionais)?\s+de\s+cataloga[çc][ãa]o", t, re.I))
    d["formato_cip"] = "brasileira" if eh_cip_brasileira else "internacional"
    pub = (re.search(
        r"([^/]{4,220}?)\s*/\s*(.{3,180}?)\s*[—\-]{1,2}\s*"
        r"([^:]{2,55}?)\s*:\s*([^,]{2,90}?)\s*,\s*((?:19|20)\d{2})\b",
        plano, re.I) if eh_cip_brasileira else None)
    if pub:
        titulo_cip = pub.group(1).strip(" .,:;-—")
        titulo_cip = re.sub(r"^\s*\(\s*CIP\s*\)\s*", "", titulo_cip,
                            flags=re.I)
        # Em fichas antigas, a expressão "CIP-Brasil. Catalogação na
        # fonte" pode ficar colada ao código e à entrada principal. O bloco
        # anterior ao código não pertence ao título.
        titulo_cip = re.sub(
            r"(?is)^.*?(?=\b[A-Z]\d{2,5}[a-z]?\s+"
            r"[A-ZÀ-Ü][\wÀ-ÿ'’-]+,\s*)", "", titulo_cip)
        responsabilidade_principal = re.split(
            r";|\s+e\s+", pub.group(2).strip(), maxsplit=1,
            flags=re.I)[0].strip(" .,:;-")
        entrada_principal = sobrenome_virgula(responsabilidade_principal)
        if entrada_principal:
            titulo_cip = re.sub(
                rf"(?i)^[A-Z]\d{{2,5}}[a-z]?\s+"
                rf"{re.escape(entrada_principal)}\.?\s*", "", titulo_cip)
        # remove o codigo de classificacao e a entrada principal do autor
        titulo_cip = re.sub(r"^[A-Z]\d+[a-z]?\s+[A-ZÁ-Ú][^.]{2,70}\.\s*",
                            "", titulo_cip)
        titulo_cip = re.sub(
            r"^[A-ZÀ-Ü][\wÀ-ÿ'’-]+,\s+[A-ZÀ-Ü][^./]{2,100}\.\s*",
            "", titulo_cip)
        if 2 <= len(titulo_cip.split()) <= 35:
            d["titulo"] = titulo_cip
        if not d.get("autor"):
            responsabilidade = re.split(r";|\s+e\s+", pub.group(2).strip())[0]
            responsabilidade = re.sub(
                r"(?i)\s*\((?:orgs?|eds?|coord(?:s|enadores?)?)\)\.?$", "",
                responsabilidade).strip(" .,:;-")
            d["autor"] = identificar.sobrenome_virgula(responsabilidade)
        d["cidade"] = re.sub(r",\s*[A-Z]{2}$", "", pub.group(3).strip())
        d["editora"] = pub.group(4).strip()
        d["ano"] = pub.group(5)

    # Ficha brasileira antiga, sem rótulos e com pontuação datilografada:
    #   CIP-Brasil-Catalogação na fonte
    #   M244d Título da obra. Autor. Goiânia. Kelps, 2007.
    # O ISBN e a paginação podem legitimamente estar vazios.
    if re.search(r"(?i)CIP\s*[-–]?\s*Brasil", t):
        d["formato_cip"] = "brasileira antiga"
        antiga = re.search(
            r"\b[A-Z]\d{2,5}[a-z]?\s+(.{5,220}?)\s*\.\s*"
            r"([A-ZÀ-Ü][A-Za-zÀ-ÿ' .-]{3,100}?)\s*\.\s*"
            r"([A-ZÀ-Ü][A-Za-zÀ-ÿ' .-]{2,50}?)\s*\.\s*"
            r"([^,.]{2,80}?)\s*,\s*((?:19|20)\d{2})\b",
            plano)
        if antiga:
            titulo_antigo = antiga.group(1).strip(" .,:;-")
            if titulo_bibliograficamente_plausivel(titulo_antigo):
                d["titulo"] = titulo_antigo
            d["autor"] = sobrenome_virgula(antiga.group(2).strip(" ."))
            d["cidade"] = antiga.group(3).strip(" .")
            d["editora"] = limpar_editora_bibliografica(
                antiga.group(4).strip(" ."))
            d["ano"] = antiga.group(5)
        sigla, numero = extrair_classificacao_catalografica(plano)
        if sigla:
            d["classificacao_original"] = f"{sigla} {numero.strip()}"
            if sigla == "CDD":
                d["cdd"] = numero.replace("-", ".").replace(" ", "")
            else:
                aplicar_cdd_sugerido_por_cdu(d)

    mm = re.search(r"\b(\d{1,5})\s*p(?:\.|\b)", plano, re.I)
    if mm:
        d["paginas"] = mm.group(1)
    mm = re.search(r"\b((?:[1-9]|[12]\d|30))\s*[ªºao]?\s*(?:edi[çc][ãa]o|edici[óo]n|edition)\b",
                   plano, re.I)
    if mm:
        d["edicao"] = mm.group(1)
    mm = re.search(r"\bCDD\s*([0-9]{1,3}(?:\.[0-9]+)?)", plano, re.I)
    if mm:
        d["cdd"] = mm.group(1)

    # ---- formato ANTIGO de CIP -------------------------------------------
    # Nao usa rotulos. O nome vem solto logo apos o cabecalho, o titulo
    # uniforme vem entre colchetes e o DDC aparece sem a sigla:
    #
    #     ... Biblioteca del Congreso Bavinck, Herman, 1854- 1921.
    #     [Gereformeerde dogmatiek. Ingles]
    #     Dogmatica reformada / Herman Bavinck; John Bolt, editor general
    #     ISBN 978-0-8010-2632-4 (tela: v. 1)
    #     BX9474.3.B38 2003 230'.42-cc21
    if not d.get("autor"):
        mm = re.match(r"\s*([A-ZÁ-Ú][\wá-úñ'’-]+),\s*([A-ZÁ-Ú][^\n,\[]{1,34}?),"
                      r"\s*\d{4}\s*[-–]", plano)
        if mm:
            d["autor"] = f"{mm.group(1)}, {mm.group(2).strip()}"

    if not d.get("tradutor") or not d.get("autor"):
        mm = re.search(r"([^.\[\]]{4,80})\s/\s([^.]{4,120}?)\.\s", plano)
        if mm:
            partes = [p.strip() for p in mm.group(2).split(";")]
            if partes and not d.get("autor"):
                d["autor"] = identificar.sobrenome_virgula(partes[0])
            for p in partes[1:]:
                if re.search(r"(?i)tradu|translat", p) and not d.get("tradutor"):
                    d["tradutor"] = re.sub(r"(?i),?\s*tradu\w*\.?$", "", p).strip()

    # titulo uniforme entre colchetes = o titulo na lingua original
    mm = re.search(r"\[([^\]]{4,70})\]", plano)
    if mm and not re.search(r"(?i)^(sic|ebook|libro)", mm.group(1)):
        d["titulo_uniforme"] = mm.group(1).strip()

    if not d.get("isbns"):
        d["isbns"] = [(c["isbn"], c["rotulo"].lower())
                      for c in candidatos_isbn(bloco)]

    if not d.get("cdd"):
        # numero de Dewey solto antes do "-dc21"/"-cc21"
        mm = re.search(r"\b(\d{3}(?:['’′]?\.\d+)?)\s*[-—–]{1,2}\s*[dc]c?\d", plano)
        if mm:
            d["cdd"] = mm.group(1).replace("′", "").replace("'", "").replace("’", "")

    if not d.get("ano"):
        # Nunca use o primeiro ano do bloco: em fichas antigas ele costuma
        # ser nascimento/falecimento do autor (1854-1921). Preferimos o ano
        # associado a copyright/publicacao e deixamos vazio sem essa ancora.
        ano = ano_publicacao(bloco)
        if ano:
            d["ano"] = str(ano)
    # O nome da bibliotecária aparece imediatamente abaixo do cabeçalho da
    # CIP e, em digitalizações desalinhadas, pode ocupar a posição esperada
    # para o título. Ele nunca é título nem autoria intelectual da obra.
    bibliotecaria = re.search(
        r"(?im)^\s*([A-ZÀ-Ü][^\n]{3,80}?)\s+CRB[-\s]?\d", bloco)
    if bibliotecaria and d.get("titulo"):
        nt = identificar.normalizar(d["titulo"])
        nb = identificar.normalizar(bibliotecaria.group(1))
        if nt and (nt == nb or nt in nb or nb in nt):
            d["titulo"] = ""
    return aplicar_cdd_sugerido_por_cdu(d)


def ler_dcip_institucional_paginas(paginas):
    """Lê a citação estruturada de uma DCIP de material didático.

    Algumas instituições não usam a ficha CIP tradicional. Elas imprimem
    uma referência completa logo abaixo de ``DCIP``. Como o cabeçalho e o
    código aparecem juntos, esta leitura não se confunde com a bibliografia
    do conteúdo.
    """
    for numero, texto in enumerate((paginas or [])[:10], 1):
        if not re.search(
                r"(?i)DADOS\s+DE\s+CATALOGA[ÇC][ÃA]O\s+INTERNA\s+"
                r"DA\s+PUBLICA[ÇC][ÃA]O\s*[-–—]?\s*DCIP", texto):
            continue
        plano = " ".join(texto.split())
        m = re.search(
            r"(?i)([A-ZÀ-Ü][A-Za-zÀ-ÿ ,.'-]{2,90})\s*\(ORG\)\.\s*"
            r"(.{3,180}?)\.\s*([A-ZÀ-Ü][A-Za-zÀ-ÿ .'-]{2,60})\s*:\s*"
            r"([^,]{2,90})\s*,\s*((?:19|20)\d{2})\.\s*"
            r"(\d{1,5})\s*pgs?\.?", plano)
        if not m:
            continue

        titulo = " ".join(m.group(2).split()).strip(" .,:;-")
        if titulo.isupper():
            minusculas = {"a", "as", "o", "os", "e", "de", "da", "das", "à",
                          "do", "dos", "em", "na", "no", "para"}
            palavras = titulo.lower().split()
            titulo = " ".join(
                p if i and p in minusculas else p[:1].upper() + p[1:]
                for i, p in enumerate(palavras))

        autor_bruto = " ".join(m.group(1).split()).strip(" .,:;-")
        autor = autor_bruto
        if identificar.normalizar(autor_bruto) == "logos instituto de teologia":
            autor = "Instituto de Teologia Logos"
        return {
            "titulo": titulo,
            "autor": autor,
            "cidade": " ".join(m.group(3).split()).title(),
            "editora": " ".join(m.group(4).split()).title().replace("Itl", "ITL"),
            "ano": m.group(5),
            "paginas": m.group(6),
            "pagina_cip": numero,
            "formato_cip": "DCIP institucional",
        }
    return {}


def ler_cip_paginas(paginas):
    """Localiza a CIP sem perder o numero da pagina que sustenta os dados."""
    for numero, texto in enumerate(paginas, 1):
        if not CIP_INICIO.search(texto):
            continue
        # Algumas fichas continuam na pagina seguinte (caso dos volumes da
        # Dogmatica). Duas paginas mantem contexto sem misturar o livro todo.
        trecho = texto
        if numero < len(paginas):
            trecho += "\n" + paginas[numero]
        d = ler_cip(trecho)
        if d:
            d["pagina_cip"] = numero
            return d
    return {}


def ler_ficha_catalografica_simplificada(paginas):
    """Reconhece fichas antigas que nao imprimem o cabecalho CIP.

    Muitas publicacoes brasileiras trazem apenas autor, descricao editorial,
    paginas e CDD dentro de um quadro. A presenca conjunta desses elementos e
    a trava que impede confundir uma referencia bibliografica comum.
    """
    for numero, texto in enumerate(paginas[:10], 1):
        sigla_texto, _numero_texto = extrair_classificacao_catalografica(texto)
        if sigla_texto != "CDD":
            continue
        plano = " ".join(texto.split())
        pub = re.search(
            r"(?i)([^.]{4,140})\.\s*"
            r"(?:(\d{1,2})\s*[ªa]?\s*edi[çc][ãa]o\.\s*)?"
            r"([A-ZÁ-Ú][^,]{2,45}),\s*([^,]{3,80}),\s*((?:19|20)\d{2})\."
            r"\s*(\d{1,5})\s*p\.?", plano)
        if not pub:
            continue
        autores = []
        for linha_autor in texto.splitlines():
            ma = re.search(
                r"\b([A-ZÁ-Ú][A-Za-zÁ-ú'.-]{2,}),\s*"
                r"([A-ZÁ-Ú][A-Za-zÁ-ú' .-]{2,60})\s*$", linha_autor)
            if ma:
                sobrenome_teste = identificar.normalizar(ma.group(1))
                nomes_teste = ma.group(2).strip(" .")
                if (sobrenome_teste not in {"igreja", "janeiro", "paulo",
                                             "titulo", "edicao"}
                        and not re.search(r"(?i)\b(?:junta|editora|editorial|"
                                          r"publica[çc]|press)\b", nomes_teste)):
                    autores.append((ma.group(1), nomes_teste))
        autor = ""
        if autores:
            sobrenome, nomes = autores[-1]
            autor = f"{sobrenome}, {' '.join(nomes.split())}".strip(" ,.;")
        titulo = pub.group(1).strip(" .")
        if autor:
            titulo = re.sub(r"(?i)^.*?" + re.escape(autor) + r"\s+", "", titulo)
        titulo = titulo[:1].upper() + titulo[1:]
        _sigla_cdd, numero_cdd = extrair_classificacao_catalografica(texto)
        assuntos = re.findall(r"(?:^|\s)\d+\.\s*([^\d]{3,80}?)(?=\s+\d+\.|\s+I\.\s*T[ií]tulo|$)",
                              plano)
        return {
            "titulo": titulo, "autor": autor,
            "edicao": (pub.group(2) + "ª edição") if pub.group(2) else "",
            "cidade": pub.group(3).strip(), "editora": pub.group(4).strip(),
            "ano": pub.group(5), "paginas": pub.group(6),
            "cdd": numero_cdd.replace("-", ".").replace(" ", ""),
            "assuntos": "; ".join(
                re.sub(r"(?i)\s+CDD\s*[-:].*$", "",
                       " ".join(x.split())).strip(" .")
                for x in assuntos[:5]),
            "pagina_cip": numero, "formato_cip": "ficha antiga sem cabeçalho",
        }
    return {}


def ler_ficha_catalografica_por_sinais(paginas):
    """Reconhece fichas sem cabeçalho pela convergência de sinais bibliográficos.

    Nenhum sinal isolado é suficiente. Isso permite ler fichas diagramadas
    como quadros ou com OCR espaçado sem transformar uma referência citada no
    prefácio em ficha da edição.
    """
    for numero, original in enumerate(paginas[:10], 1):
        texto = normalizar_rotulos_numeros_ocr(original)
        editora = editora_por_assinatura_ocr(original)
        # Forma brasileira sem cabecalho, comum em ebooks: a linha de
        # responsabilidade termina em "-- Cidade: Editora, ano". Ela e mais
        # forte que uma simples mencao posterior a outra editora.
        # A norma ISBD escreve ". - Cidade : Editora, ano", mas a composicao
        # real quase sempre cola o traco no ponto final da responsabilidade:
        #   "Cleverson Pereira Rodrigues.- Niteroi : Primeira Igreja..., 2024."
        # Exigir espaco antes do traco fazia a linha inteira escapar, e com
        # ela editora, cidade e ano - o livro parava em revisao por falta de
        # editora tendo a informacao escrita na propria ficha.
        # A cidade pode vir quebrada em duas linhas ("Sao Jose\ndos Campos"),
        # entao [^:] precisa continuar aceitando a quebra.
        publicacao = re.search(
            r"(?s)[\s.][—–-]\s*([^:]{2,90}?)\s*:\s*([^,\n]{2,80}?)\s*,\s*"
            r"((?:19|20)\d{2})\b", original)
        titulo_citacao = autor_citacao = ""
        if publicacao:
            antes = original[:publicacao.start()]
            citacao = re.search(
                r"(?s)([^\n]{2,120}(?:\n[^\n]{2,120}){0,3}?)\s*/\s*"
                r"([^\n.]{3,150})\.?\s*$", antes)
            if citacao:
                titulo_citacao = " ".join(citacao.group(1).split())
                # Remove a entrada principal que pode anteceder o titulo.
                titulo_citacao = re.sub(
                    r"^(?:[A-Z]\d{2,5}[a-z]?\s+)?"
                    r"[A-ZÀ-Ü][\wÀ-ÿ'.’-]+,\s*[A-ZÀ-Ü][^,]{1,60},\s*"
                    r"\d{4}\s*[-–]\s*",
                    "", titulo_citacao).strip(" .,:;-")
                autor_citacao = re.split(
                    r";|\s+(?:&|e|and)\s+", citacao.group(2), maxsplit=1,
                    flags=re.I)[0].strip()
        isbns = [(c["isbn"], c["rotulo"].lower())
                 for c in candidatos_isbn(texto)]
        mpag = re.search(r"\b(\d{1,5})\s*pp?\.?\b", texto, re.I)
        sigla_classe, numero_classe = extrair_classificacao_catalografica(texto)
        mautor = re.search(
            r"(?im)^\s*(?:[A-Z]\d{2,5}[a-z]?\s+)?"
            r"([A-ZÀ-Ü][\wÀ-ÿ'.’-]+),\s*"
            r"([A-ZÀ-Ü][^\n,;]{1,60})(?:;|\s*$)", original)
        autor = (f"{mautor.group(1)}, {' '.join(mautor.group(2).split())}"
                 if mautor else "")
        ano = ((int(publicacao.group(3)) if publicacao else None)
               or ano_desta_edicao(texto) or ano_publicacao(texto))
        if not ano:
            anos = [int(x) for x in re.findall(r"\b(?:19|20)\d{2}\b", texto)]
            ano = max(anos) if anos else None
        sinais = sum(bool(x) for x in (
            editora, isbns, mpag, sigla_classe, autor, ano,
            publicacao, titulo_citacao, autor_citacao))
        if sinais < 4 or not (autor or editora or publicacao):
            continue
        d = {
            "pagina_cip": numero,
            "formato_cip": "ficha reconhecida por sinais combinados",
        }
        if autor:
            d["autor"] = autor.strip(" .;")
        elif autor_citacao:
            d["autor"] = sobrenome_virgula(autor_citacao)
        if publicacao:
            d["cidade"] = " ".join(publicacao.group(1).split()).strip()
            d["editora"] = " ".join(publicacao.group(2).split()).strip()
            if titulo_citacao and titulo_bibliograficamente_plausivel(titulo_citacao):
                d["titulo"] = titulo_citacao
        elif editora:
            d["editora"] = editora
        if isbns:
            d["isbns"] = isbns
        if mpag:
            d["paginas"] = mpag.group(1)
        if sigla_classe:
            d["classificacao_original"] = (
                f"{sigla_classe} {numero_classe}")
            if sigla_classe == "CDD":
                d["cdd"] = numero_classe.replace("-", ".").replace(" ", "")
        if ano:
            d["ano"] = str(ano)
        return d
    return {}


def combinar_fichas_catalograficas(cabecalho, simplificada, sinais):
    """Une leitores complementares sem deixar uma regex fraca vencer outra forte."""
    resultado = dict(simplificada or {})
    resultado.update({k: v for k, v in (sinais or {}).items()
                      if v not in (None, "", [])})
    resultado.update({k: v for k, v in (cabecalho or {}).items()
                      if v not in (None, "", [])})
    titulo = resultado.get("titulo", "")
    autor_forte = ((sinais or {}).get("autor", "")
                   or resultado.get("autor", ""))
    if titulo:
        titulo = titulo.split("/", 1)[0].strip(" .,:;-")
        if autor_forte:
            titulo = re.sub(
                r"(?i)^\s*" + re.escape(autor_forte).replace(r"\ ", r"\s+")
                + r"\s+", "", titulo).strip(" .,:;-")
            autor_norm = identificar.normalizar(autor_forte)
            titulo_norm = identificar.normalizar(titulo)
            if titulo_norm.startswith(autor_norm):
                tokens_autor = autor_norm.split()
                partes_titulo = titulo.split()
                titulo = " ".join(partes_titulo[len(tokens_autor):]).strip(" .,:;-")
        if titulo_bibliograficamente_plausivel(titulo):
            resultado["titulo"] = titulo
        else:
            resultado.pop("titulo", None)
    return resultado


def ler_cip_ocr_visual_capa(capa_info):
    """Aproveita ficha CIP que só apareceu no OCR visual da capa/página.

    Alguns PDFs têm a primeira página como imagem: ``pdftotext`` devolve
    vazio, mas o leitor visual da capa enxerga a ficha catalográfica inteira.
    Sem esta ponte, a bancada mostrava a CIP completa e o motor mesmo assim
    deixava o livro em revisão.
    """
    linhas = []
    if isinstance(capa_info, dict):
        linhas = [str(x) for x in (capa_info.get("texto_ocr") or []) if str(x).strip()]
    texto = "\n".join(linhas)
    if not texto or not CIP_INICIO.search(texto):
        return {}
    cip = combinar_fichas_catalograficas(
        ler_cip_paginas([texto]),
        ler_ficha_catalografica_simplificada([texto]),
        ler_ficha_catalografica_por_sinais([texto]))
    if cip:
        cip["fonte_cip"] = "OCR visual da capa/página inicial"
        cip.setdefault("pagina_cip", 1)
    return cip


def cip_tem_identidade_bibliografica(cip):
    """Indica que a ficha CIP identifica a obra melhor que capa/folha inicial.

    Titulo e autor plausiveis sao o nucleo da identidade. A presenca de ao
    menos um dado editorial (editora, ano, ISBN ou classificacao) evita que
    uma simples citacao, capturada por engano, receba autoridade de CIP.
    """
    cip = cip or {}
    titulo = cip.get("titulo", "")
    autor = cip.get("autor", "")
    dado_editorial = any(cip.get(campo) for campo in (
        "editora", "ano", "isbns", "cdd", "classificacao_original"))
    return bool(
        titulo_bibliograficamente_plausivel(titulo)
        and autor_bibliograficamente_plausivel(autor)
        and dado_editorial)


ORIGENS_TITULO_CONVERGENTES = {
    "cip", "copyright", "folha de rosto", "linha de copyright", "capa",
    "folha de rosto do volume",
    "capa substituiu OCR implausivel", "metadado do PDF confirmado",
    "capa confirmada pelo nome do arquivo",
    "folha de rosto confirmada pelo nome do arquivo",
    "metadado do PDF confirmado pelo nome do arquivo",
    "capa substituiu OCR implausivel confirmada pelo nome do arquivo",
    "título da apresentação confirmada pelo nome do arquivo",
    "cabeçalho documental explícito confirmado pelo nome do arquivo",
    "API por ISBN confirmado na edição", "CBL por ISBN exato",
    "Google Books por título e autor", "fonte comercial de alta confiança",
    "folha de rosto estruturada do Word",
}
ORIGENS_AUTOR_CONVERGENTES = {
    "cip", "folha de rosto", "capa confirmada",
    "autor confirmado pela série de obras",
    "metadado do PDF confirmado",
    "capa confirmou autor do nome do arquivo",
    "copyright confirmado pelo PDF", "rotulo documental",
    "API por ISBN confirmado na edição", "Google Books por título e autor",
    "função editorial declarada no PDF",
}


def avaliar_convergencia_bibliografica(ficha):
    """Decide ausências editoriais por três evidências auditáveis.

    Livros antigos e edições do próprio autor frequentemente não possuem
    ISBN, CIP ou todos os elementos de uma ficha moderna. Eles não devem ficar
    presos somente porque uma data ou editora realmente não foi declarada.

    A convenção ``[s.d.]``/``[s.n.]`` só é aplicada quando convergem:
      1. título lido de fonte forte;
      2. autoria explicitamente identificada;
      3. ao menos uma chave desta publicação (ISBN confirmado, editora ou ano).

    Conflito, procedência derivada e pistas do nome do arquivo nunca são
    promovidos por esta camada. O resultado explica cada decisão para auditoria.
    """
    resultado = {
        "aprovada": False, "evidencias": [], "campos_convencionados": {},
        "motivo": "",
    }
    if ficha.get("tipo_documento", "livro") not in {"livro", "coletânea"}:
        resultado["motivo"] = "não se aplica a este tipo documental"
        return resultado
    if ficha.get("conflitos"):
        resultado["motivo"] = "há conflito bibliográfico pendente"
        return resultado
    procedencias = ficha.get("procedencia", []) or []
    if isinstance(procedencias, str):
        procedencias = [x.strip() for x in procedencias.split(";") if x.strip()]
    perigosas = {"tradução automática", "captura de site",
                 "cópia digital não comercial"}
    if perigosas.intersection(procedencias):
        resultado["motivo"] = "arquivo derivado não identifica uma edição publicada"
        return resultado

    titulo = ficha.get("titulo", "")
    autor = ficha.get("nmAutor0", "")
    origem_titulo = ficha.get("origem_titulo", "")
    origem_autor = ficha.get("origem_autor", "")
    if (not titulo_bibliograficamente_plausivel(titulo)
            or origem_titulo not in ORIGENS_TITULO_CONVERGENTES):
        resultado["motivo"] = "título sem fonte local/estruturada suficientemente forte"
        return resultado
    resultado["evidencias"].append(f"título: {origem_titulo}")
    if (not autor_bibliograficamente_plausivel(autor)
            or origem_autor not in ORIGENS_AUTOR_CONVERGENTES):
        resultado["motivo"] = "autoria sem identificação explícita suficientemente forte"
        return resultado
    resultado["evidencias"].append(f"autoria: {origem_autor}")

    publicacao = []
    if ficha.get("isbn") and ficha.get("isbn_confirmado_na_edicao"):
        publicacao.append("ISBN confirmado nesta edição")
    if editora_bibliograficamente_plausivel(ficha.get("editora", "")):
        publicacao.append(f"editora: {ficha['editora']}")
    data = str(ficha.get("data", "") or "").strip()
    if re.fullmatch(r"(?:1[5-9]|20)\d{2}", data):
        publicacao.append(f"ano editorial: {data}")
    if not publicacao:
        resultado["motivo"] = "falta uma chave independente da publicação"
        return resultado
    resultado["evidencias"].append("publicação: " + "; ".join(publicacao))

    # A ausência foi verificada por todas as camadas anteriores. A nota
    # catalográfica é explícita e jamais se confunde com dado encontrado.
    if not ficha.get("data"):
        resultado["campos_convencionados"]["data"] = "[s.d.]"
    if not ficha.get("editora"):
        resultado["campos_convencionados"]["editora"] = "[s.n.]"
    resultado["aprovada"] = True
    resultado["motivo"] = "três dimensões bibliográficas convergiram"
    return resultado


def derivacao_editorial_nao_publicada(texto):
    """Reconhece arquivo derivado que não deve herdar o ISBN da fonte."""
    texto = texto or ""
    if re.search(
            r"(?i)machine\s+translated\s+by\s+google|"
            r"traduzido\s+automaticamente\s+pelo\s+google", texto):
        return {
            "tipo": "tradução automática",
            "edicao": "tradução automática não publicada",
            "limpar_edicao_fonte": True,
        }
    if re.search(
            r"(?i)c[oó]pia\s+(?:digital\s+)?n[aã]o\s+comercial|"
            r"non[- ]commercial\s+(?:digital\s+)?copy", texto):
        return {
            "tipo": "cópia digital não comercial",
            "edicao": "cópia digital não comercial",
            "limpar_edicao_fonte": False,
        }
    return {}


# ---------------------------------------------------------------------------
# FOLHA DE ROSTO - as primeiras linhas do livro
# ---------------------------------------------------------------------------
#
# E a unica fonte de "Teologia Historica / William Cunningham": obra do
# seculo XIX, sem ISBN, sem CIP, sem pagina de creditos. A pagina 1 traz
# titulo e autor e nada mais.

# num ebook a "pagina 1" costuma ser o sumario, nao a folha de rosto
SUMARIO = re.compile(
    r"(?i)tabla de contenido|sum[áa]rio|table of contents|[íi]ndice|contents|"
    r"p[áa]gina del? t[íi]tulo|derechos de autor|dedicat|dedica[çc]|"
    r"prefaci|abreviatur|contraportada|media p[áa]gina")


def ler_folha_rosto(f, autor_conhecido="", pistas=()):
    """Le a pagina 1 como texto e deixa o identificar.py separar.

    Duas travas, ambas aprendidas errando: a pagina 1 de um ebook e quase
    sempre o SUMARIO (foi de la que sairam "1 2" e "Pagina de titulo
    Derechos de autor Dedicacion"), e o resultado so vale se corroborar
    algo que ja temos.
    """
    t = texto_pdftotext(f, 2)
    if len(t.strip()) < 40 or qualidade_ocr(t) < LIMIAR_OCR:
        t = texto_vision(f, 2) or t          # digitalizado: vai de Vision
    linhas = [l.strip() for l in t.splitlines() if l.strip()]
    if not linhas or len(linhas) > 40:
        return {}
    if sum(bool(SUMARIO.search(l)) for l in linhas[:12]) >= 2:
        return {}

    # Em muitos livros a pagina 1 traz o bloco CIP junto. O CIP e otimo
    # como ficha, mas pessimo como folha de rosto: dele saiu o titulo
    # "Friend, traductor. pags. cm. Contenido: v. 1". Quem le CIP e o
    # ler_cip(); aqui ele so atrapalha.
    if CIP_INICIO.search(t):
        corte = next((i for i, l in enumerate(linhas) if CIP_INICIO.search(l)), None)
        if corte is not None:
            linhas = linhas[:corte]
    linhas = [l for l in linhas
              if not re.search(r"(?i)p[áa]gs?\.\s*cm|traductor|tradutor[a]?\b|"
                               r"contenido\s*:|inclu[iy]e referencias|"
                               r"editor general|catalogaci", l)]
    # numero de pagina solto no comeco ("1 Teologia Historica")
    linhas = [re.sub(r"^\s*\d{1,3}\s+(?=\S)", "", l) for l in linhas]
    linhas = [l for l in linhas if l.strip() and not re.fullmatch(r"\d{1,3}", l.strip())]
    if not linhas:
        return {}

    r = identificar.separar(linhas[:25], autor_conhecido=autor_conhecido)

    sig = set()
    for p in pistas:
        sig |= {w for w in identificar.normalizar(p).split() if len(w) > 3}
    if sig and r.get("titulo"):
        tit = {w for w in identificar.normalizar(r["titulo"]).split() if len(w) > 3}
        if not (sig & tit):
            r["titulo"] = ""
    return r


def metadados_folha_rosto_editorial_antiga(paginas):
    """Extrai dados editoriais de folha de rosto antiga digitalizada.

    Obras devocionais antigas sem ISBN/CIP frequentemente trazem tudo numa
    única folha de rosto:

        THE BOOK OF REVELATION
        A SERIES OF OUTLINE STUDIES IN THE
        APOCALYPSE
        By
        JAMES H. McCONKEY
        42nd Thousand
        1921
        SILVER PUBLISHING COMPANY
        1018 Bessemer Building
        PITTSBURGH, PA., U. S. A.

    Essa informação não é "copyright" nem CIP, mas é a própria página
    editorial da edição. Deve preencher editora, cidade e ano quando o OCR
    visual a recupera.
    """
    for numero, texto in enumerate((paginas or [])[:8], 1):
        linhas = [" ".join(l.split()).strip(" .,:;")
                  for l in str(texto or "").splitlines()]
        linhas = [l for l in linhas if l]
        if len(linhas) < 5:
            continue

        editora = ""
        idx_editora = None
        for i, linha in enumerate(linhas):
            if re.search(
                    r"(?i)\b(?:publishing\s+company|publishing|publisher|"
                    r"press|book\s+house|books|publications)\b", linha):
                if not re.search(r"(?i)\b(?:free|write|address|sent|leaflet)\b",
                                 linha):
                    editora = limpar_editora_bibliografica(linha)
                    if editora.isupper():
                        editora = identificar.caixa_normal(editora)
                    idx_editora = i
                    break
        if not editora_bibliograficamente_plausivel(editora):
            continue

        ano = ""
        for linha in linhas[max(0, (idx_editora or 0) - 4):(idx_editora or 0) + 2]:
            m = re.search(r"\b((?:18|19|20)\d{2})\b", linha)
            if m:
                ano = m.group(1)
                break

        cidade = ""
        for linha in linhas[(idx_editora or 0) + 1:(idx_editora or 0) + 5]:
            # remove endereço antes de procurar a cidade
            if re.search(r"(?i)\b(?:building|street|st\.?|avenue|ave\.?|"
                         r"road|rd\.?|box|p\.?\s*o\.?)\b", linha):
                continue
            mcidade = re.match(
                r"(?i)^([A-Z][A-Z .'-]{2,40}),\s*"
                r"(?:[A-Z]{2}|[A-Z][a-z]{1,12}\.?)\b", linha)
            if mcidade:
                cidade = mcidade.group(1).title()
                cidade_norm = identificar.normalizar(cidade)
                if cidade_norm in {"pittsburge", "pittsburg", "pittsburgh"}:
                    cidade = "Pittsburgh"
                break

        autor = ""
        for i, linha in enumerate(linhas[:12]):
            if re.fullmatch(r"(?i)by|por|pelo|pela", linha) and i + 1 < len(linhas):
                candidato = linhas[i + 1]
                if autor_bibliograficamente_plausivel(candidato):
                    autor = sobrenome_virgula(candidato)
                break

        titulo = ""
        if autor:
            idx_by = next((i for i, linha in enumerate(linhas[:12])
                           if re.fullmatch(r"(?i)by|por|pelo|pela", linha)),
                          None)
            if idx_by and idx_by >= 1:
                cand_linhas = [
                    l for l in linhas[:idx_by]
                    if not re.search(r"(?i)^(?:the|a|an)?\s*$", l)
                    and not re.fullmatch(r"\d+(?:st|nd|rd|th)?\s+thousand",
                                         l, re.I)
                ]
                titulo = " ".join(cand_linhas[:4]).strip(" .,:;")
                titulo = limpar_titulo_bibliografico(titulo, autor)
                if not titulo_bibliograficamente_plausivel(titulo):
                    titulo = ""

        dados = {
            "pagina": numero,
            "editora": editora,
            "cidade": cidade,
            "ano": ano,
            "autor": autor,
            "titulo": titulo,
            "fonte": "folha de rosto editorial",
        }
        return {k: v for k, v in dados.items() if v not in ("", None)}
    return {}


# ---------------------------------------------------------------------------
# TITULO NA LINHA DE COPYRIGHT
# ---------------------------------------------------------------------------
#
# "El Manual de Billy Graham para Obreros Cristianos (c)2005 Billy Graham
# Evangelistic Association" - o titulo completo, literal, imediatamente
# antes do simbolo. A capa desse livro so mostra parte dele.

# a pagina de creditos e cheia de linhas que terminam em (c)ANO e nao sao o
# titulo: credito de versao biblica, aviso de direitos, boletim da editora.
NAO_E_TITULO = re.compile(
    r"(?i)biblia|bible|version|vers[ãa]o|versi[óo]n|reina|valera|nvi\b|niv\b|"
    r"esv\b|copyright|derechos|direitos|reservad|permis|boletin|bolet[ií]n|"
    r"newsletter|suscr[ií]b|inscre|todos os|all rights|usado con|used by|"
    r"traducci|tradu[çc][aã]o|textos?\s+em\s+portugu[êe]s|impreso|printed|"
    r"edici[oó]n electr|marca registrada")


def titulo_da_linha_copyright(t, pistas=()):
    """Titulo escrito imediatamente antes do (c)ANO.

    "El Manual de Billy Graham para Obreros Cristianos (c)2005 Billy Graham
    Evangelistic Association" - a capa desse livro so mostra parte do
    titulo; aqui ele esta inteiro.

    So aceitamos o candidato quando ele CORROBORA algo que ja temos (nome
    do arquivo, capa). Sem isso a funcao vira uma rede que pesca qualquer
    credito de versao biblica - foi o que aconteceu no primeiro teste.
    """
    sig = set()
    for p in pistas:
        sig |= {w for w in identificar.normalizar(p).split() if len(w) > 3}

    for m in re.finditer(
            r"^\s*([A-ZÁ-Ú][^\n©]{6,120}?)\s*(?:copyright\s*)?©\s*\d{4}",
            t, re.M | re.I):
        cand = " ".join(m.group(1).split()).strip(" .,;:-")
        if len(cand.split()) < 2 or NAO_E_TITULO.search(cand):
            continue
        if identificar.INSTITUICAO.search(cand) or identificar.RUIDO.match(cand):
            continue
        if identificar.autor_score(cand) >= 35:     # e nome de gente
            continue
        if sig:
            palavras = {w for w in identificar.normalizar(cand).split() if len(w) > 3}
            if not (sig & palavras):
                continue
        return cand
    return ""


def titulo_nas_paginas_iniciais(paginas, pistas=(), autor=""):
    """Procura o titulo por pagina, preservando proximidade e hierarquia.

    A pagina de rosto e a linha de creditos sao mais confiaveis que o nome
    do arquivo. Trabalhar pagina a pagina evita juntar um titulo ao nome de
    autor ou ao copyright que apareceu muitas paginas depois.
    """
    sig = set()
    for p in pistas:
        sig |= {w for w in identificar.normalizar(p).split() if len(w) > 3}
    sig_autor = {w for w in identificar.normalizar(autor).replace(",", " ").split()
                 if len(w) > 2}

    # Coleções antigas podem mostrar primeiro o título da série ("OBRAS DE
    # WESLEY") e somente depois o título bibliográfico do volume ("DIARIOS,
    # TOMO I"). O volume específico vence a série, mas apenas quando as duas
    # marcas coexistem na mesma folha, evitando promover menções de sumário.
    for numero, texto in enumerate(paginas[:15], 1):
        if not re.search(r"(?im)^\s*OBRAS\s+DE\s+[A-ZÁ-Ú][A-ZÁ-Ú .'-]+\s*$", texto):
            continue
        volumes = re.findall(
            r"(?im)^\s*([A-ZÁ-Ú][A-ZÁ-Ú .'’-]{2,70}),\s*"
            r"(TOMO\s+[IVXLCDM0-9]+)\s*$", texto)
        if volumes:
            titulo_volume, tomo = volumes[-1]
            titulo_volume = identificar.caixa_normal(titulo_volume.strip())
            numero_tomo = re.sub(r"(?i)^TOMO\s+", "", tomo).upper()
            return (f"{titulo_volume}, tomo {numero_tomo}", numero,
                    "folha de rosto do volume")

    # Primeiro percorremos todas as paginas em busca de declaracoes
    # editoriais explicitas; elas ganham de uma meia-folha de rosto curta.
    for numero, texto in enumerate(paginas[:15], 1):
        cp = ler_copyright(texto)
        if cp.get("titulo_edicao"):
            return cp["titulo_edicao"], numero, "copyright da edicao"

        # Serie em volumes: o volume e parte indispensavel do titulo.
        m = re.search(
            r"(?im)^\s*DOGM[ÁA]TICA\s+REFORMADA\s*$\s*"
            r"^\s*Vol(?:ume|umen)\s*([1-9][0-9]?)\s*:\s*([^\n]{3,100})",
            texto)
        if m:
            subt = re.sub(r"\s+(?:Herman\s+)?Bavinck\s*$", "", m.group(2),
                          flags=re.I).strip(" .")
            return f"Dogmática reformada: {subt}", numero, "folha de rosto"

        tc = titulo_da_linha_copyright(texto, pistas=pistas)
        if tc:
            return tc, numero, "linha de copyright"

        linhas = [" ".join(l.split()) for l in texto.splitlines() if l.strip()]
        for i, linha in enumerate(linhas):
            if re.search(r"(?i)(?:derechos de autor|direitos autorais|copyright)\s*©", linha):
                if i:
                    cand = linhas[i - 1].strip(" .,:;-")
                    palavras = {w for w in identificar.normalizar(cand).split()
                                if len(w) > 3}
                    if (3 <= len(cand) <= 140 and not NAO_E_TITULO.search(cand)
                            and (not sig or sig & palavras)):
                        return cand, numero, "linha anterior ao copyright"

    for numero, texto in enumerate(paginas[:15], 1):

        primeiras = [" ".join(l.split()) for l in texto.splitlines() if l.strip()]
        cabecalho = " ".join(primeiras[:3])
        if re.search(
                r"(?i)^(?:ENDOSSOS?|DEDICAT[ÓO]RIA|AGRADECIMENTOS?|PREF[ÁA]CIO|"
                r"APRESENTA[ÇC][ÃA]O|INTRODU[ÇC][ÃA]O|[ÍI]NDICE|SUM[ÁA]RIO)\b",
                cabecalho):
            continue

        linhas = [" ".join(l.split()).strip(" |") for l in texto.splitlines()]
        linhas = [l for l in linhas if l and not re.fullmatch(r"[ivxlcdm\d .-]+", l, re.I)]
        if not linhas or len(linhas) > 24 or SUMARIO.search(" ".join(linhas[:8])):
            continue

        # Numa folha de rosto, o titulo precede o autor conhecido.
        indice_autor = None
        if sig_autor:
            for i, linha in enumerate(linhas):
                pl = set(identificar.normalizar(linha).split())
                if len(sig_autor & pl) >= min(2, len(sig_autor)):
                    indice_autor = i
                    break
        limite = indice_autor if indice_autor is not None else min(5, len(linhas))
        candidatas = []
        for linha in linhas[:limite]:
            if (len(linha) < 3 or len(linha) > 100 or NAO_E_TITULO.search(linha)
                    or identificar.INSTITUICAO.search(linha)
                    or identificar.RUIDO.match(linha)
                    or linha.startswith(('"', '«'))):
                continue
            palavras = {w for w in identificar.normalizar(linha).split() if len(w) > 3}
            # Titulo quebrado em linhas: a primeira linha corrobora a pista
            # e as seguintes a completam ("Mais de um Século de" +
            # "Educação Metodista"). Exigir a pista em cada linha truncava-o.
            if sig and not (sig & palavras):
                continua_titulo = (candidatas and (
                    re.search(
                        r"(?i)\b(?:de|da|do|das|dos|del|of|the|and|e|y|para)\s*$",
                        candidatas[-1])
                    or re.match(r"(?i)^(?:vol(?:ume)?|tomo)\s*\d+\b", linha)))
                if not continua_titulo:
                    continue
            candidatas.append(linha)
        if candidatas:
            # Duas ou tres linhas consecutivas na capa/folha de rosto podem
            # ser titulo e subtitulo. Mantemos no maximo 160 caracteres.
            titulo = " ".join(candidatas[:4])
            return titulo[:160].strip(" :"), numero, "folha de rosto"
    return "", None, ""


def titulo_autor_por_byline_folha(titulo_folha):
    """Separa ``Título Pelo/Por Dr. Autor`` sem inverter os campos.

    Em folhetos e livros curtos, a folha de rosto frequentemente vem numa
    única linha, por exemplo ``Algo Inimaginável Pelo Dr. Barbet``. Sem esta
    regra, o final rotulado como autoria podia virar título e as primeiras
    palavras do título podiam virar autor.
    """
    texto = " ".join(str(titulo_folha or "").split()).strip(" .,:;|-")
    if not texto:
        return "", ""
    m = re.search(
        r"(?i)^(.{3,160}?)\s+"
        r"(?:pelo|pela|por|by)\s+"
        r"(?:(?:dr|dra|pr|pra|rev|reva|pastor|pastora)\.?\s+)?"
        r"((?:(?:[A-Z]\.\s*){1,4})?[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+"
        r"(?:\s+(?:[A-Z]\.|[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+)){0,5})\s*$",
        texto)
    if not m:
        return "", ""
    titulo = limpar_titulo_bibliografico(m.group(1))
    autor = " ".join(m.group(2).split()).strip(" .,:;-")
    if not titulo_bibliograficamente_plausivel(titulo):
        return "", ""
    # Autores de folhetos podem aparecer só pelo sobrenome após um honorífico
    # ("Dr. Barbet"). Aceitamos nome único aqui porque o rótulo é explícito.
    if not autor or identificar.INSTITUICAO.search(autor):
        return "", ""
    return titulo, sobrenome_virgula(autor)


def autor_byline_nas_paginas_iniciais(paginas, titulo=""):
    """Captura autoria em linha própria: ``by A. B. Bruce``."""
    titulo_norm = identificar.normalizar(titulo or "")
    for texto in list(paginas or [])[:5]:
        linhas = [" ".join(l.split()).strip(" .,:;-")
                  for l in texto.splitlines() if l.strip()]
        for i, linha in enumerate(linhas[:12]):
            m = re.match(
                r"(?i)^by\s+((?:(?:[A-Z]\.\s*){1,4})?"
                r"[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+(?:\s+(?:[A-Z]\.|"
                r"[A-ZÀ-Ü][A-Za-zÀ-ÿ'.-]+)){0,5})$",
                linha)
            if not m:
                continue
            antes = " ".join(linhas[max(0, i - 4):i])
            if titulo_norm:
                antes_norm = identificar.normalizar(antes)
                tokens_titulo = {p for p in titulo_norm.split() if len(p) > 3}
                tokens_antes = {p for p in antes_norm.split() if len(p) > 3}
                if tokens_titulo and len(tokens_titulo & tokens_antes) < min(
                        2, len(tokens_titulo)):
                    continue
            autor = " ".join(m.group(1).split()).strip()
            if autor_bibliograficamente_plausivel(autor):
                return sobrenome_virgula(autor)
    return ""


def autor_da_serie_obras(paginas, nome_arquivo=""):
    """Confirma no nome do arquivo o autor anunciado por uma série de obras.

    ``OBRAS DE WESLEY`` fornece apenas o sobrenome. Ele só vira autoria se o
    nome completo no arquivo terminar no mesmo sobrenome; assim uma série ou
    instituição não é inventada como pessoa.
    """
    for texto in list(paginas or [])[:15]:
        m = re.search(
            r"(?im)^\s*OBRAS\s+DE\s+([A-ZÁ-Ú][A-ZÁ-Ú'’-]{2,})\s*$", texto)
        if not m:
            continue
        sobrenome = m.group(1)
        nome_legivel = re.sub(r"[-_]+", " ", pathlib.Path(
            nome_arquivo or "").stem)
        nomes = re.findall(
            rf"\b([A-ZÁ-Ú][a-zá-ú'’-]+(?:\s+[A-ZÁ-Ú][a-zá-ú'’-]+){{0,2}}"
            rf"\s+{re.escape(sobrenome.title())})\b",
            nome_legivel)
        if nomes:
            return sobrenome_virgula(nomes[-1])
    return ""


def autor_folha_rosto_confirmado(paginas, autor_nome_arquivo="",
                                  pagina_titulo=None):
    """Recupera a autoria que a capa/folha de rosto escreveu sem rótulo.

    O erro recorrente era uma folha visual com ``TÍTULO`` e ``NOME DO
    AUTOR``: sem ISBN/CIP, o nome era incorporado ao título e a validação
    apenas detectava o estrago. Aqui a pessoa só ganha autoridade quando
    existe uma segunda evidência no próprio PDF (copyright, menção a autor
    do autor) ou quando o nome completo foi extraído do arquivo e confirmado
    na folha. A simples repetição foi deliberadamente excluída: títulos de
    capítulo e frases de sumário também se repetem. Assim não transformamos
    uma linha curta do título em autor.
    """
    paginas = list(paginas or [])
    if not paginas:
        return ""

    def tokens_nome(valor):
        return [p for p in identificar.normalizar(
            (valor or "").replace(",", " ")).split() if len(p) > 1]

    conhecido = tokens_nome(autor_nome_arquivo)
    candidatos = []
    # Autoria de livro aparece na capa/folha de rosto. Abrir quatro páginas
    # permitia que epígrafes e primeiras citações disputassem o campo.
    indices = list(range(min(2, len(paginas))))
    if pagina_titulo and 1 <= int(pagina_titulo) <= len(paginas):
        indice_titulo = int(pagina_titulo) - 1
        if indice_titulo not in indices:
            indices.append(indice_titulo)
    for numero in indices:
        texto = paginas[numero]
        linhas = [" ".join(l.split()).strip(" .,:;|-_")
                  for l in texto.splitlines() if l.strip()]
        for posicao, linha in enumerate(linhas[:12]):
            partes = linha.split()
            if not (2 <= len(partes) <= 5):
                continue
            anterior = linhas[posicao - 1] if posicao else ""
            if re.search(
                    r"(?i)^(?:editor(?:a)?(?:\s+general)?|edited\s+by|"
                    r"organiza[çc][aã]o|coordenador|tradutor)\b", anterior):
                continue
            if (identificar.INSTITUICAO.search(linha)
                    or identificar.RUIDO.match(linha)
                    or re.search(r"\d|[?!:;]", linha)
                    or identificar.autor_score(linha) < 15
                    or not autor_bibliograficamente_plausivel(linha)):
                continue
            tl = tokens_nome(linha)
            if len(tl) < 2:
                continue
            candidatos.append((numero, linha, tl))

    corpus = [identificar.normalizar(p) for p in paginas[:12]]

    # Se o arquivo ofereceu um nome, primeiro procure esse nome em TODAS as
    # candidatas. Antes, uma frase anterior podia vencer apenas por aparecer
    # primeiro, mesmo com o autor verdadeiro logo abaixo.
    if conhecido:
        for _pagina, linha, tl in candidatos:
            if set(conhecido) == set(tl):
                nome_formatado = (identificar.caixa_normal(linha)
                                  if linha == linha.upper() else linha)
                return sobrenome_virgula(nome_formatado)

    # A página já reconhecida como folha de rosto é uma evidência espacial.
    # Isso cobre livros precedidos por endossos sem procurar nomes no corpo.
    if pagina_titulo:
        indice_titulo = int(pagina_titulo) - 1
        for pagina_origem, linha, _tl in candidatos:
            if (pagina_origem == indice_titulo
                    and identificar.autor_score(linha) >= 25):
                nome_formatado = (identificar.caixa_normal(linha)
                                  if linha == linha.upper() else linha)
                return sobrenome_virgula(nome_formatado)

    for pagina_origem, linha, tl in candidatos:
        nome_formatado = (identificar.caixa_normal(linha)
                          if linha == linha.upper() else linha)
        assinatura = r"\s+".join(re.escape(p) for p in tl)
        ancora = any(re.search(
            rf"\b(?:autor(?:a|es)?|author|written\s+by|por|by|\u00a9)\b"
            rf"[^\n]{{0,90}}\b{assinatura}\b|"
            rf"\b{assinatura}\b[^\n]{{0,40}}\b(?:autor(?:a|es)?|author)\b",
            texto, re.I) for texto in corpus)
        if ancora:
            return sobrenome_virgula(nome_formatado)
    return ""


def metadados_pdf(f):
    """Titulo/autor embutidos no PDF, usados apenas como ultima evidencia."""
    try:
        s = subprocess.run(["pdfinfo", f], capture_output=True, text=True,
                           timeout=30).stdout
    except Exception:
        return {}
    d = {}
    for campo, chave in (("Title", "titulo"), ("Author", "autor"),
                         ("Creator", "criador"), ("Producer", "produtor")):
        m = re.search(rf"^{campo}:\s*(.+)$", s, re.M)
        if m:
            v = " ".join(m.group(1).split()).strip()
            if v and v.lower() not in ("unknown", "lenovo") and "@" not in v:
                if chave == "titulo":
                    # Ferramentas de diagramacao gravam o nome da revisao no
                    # campo Title. O prefixo anterior ainda pode ser o titulo
                    # real e nao deve ser perdido junto com ".indd".
                    v = re.sub(
                        r"(?i)\s+(?:revis[aã]o|rev\.?)[ \t]+v?\d[\w. -]*$",
                        "", v).strip()
                    # O Office costuma gravar o nome tecnico do arquivo no
                    # campo /Title ("Microsoft PowerPoint - ..."). Isso nao
                    # e titulo bibliografico e pode indevidamente vencer a
                    # capa ou a folha de rosto corretas.
                    if re.match(
                            r"(?i)^Microsoft\s+(?:PowerPoint|Word)\s*[-–—:]",
                            v):
                        continue
                d[chave] = v
    return d


def autor_confirmado_nas_paginas(paginas, candidato):
    """Confirma no miolo um autor sugerido pelo nome do arquivo."""
    if not candidato:
        return False
    partes = [w for w in identificar.normalizar(candidato.replace(",", " ")).split()
              if len(w) > 2]
    if len(partes) < 2:
        return False
    for texto in paginas[:12]:
        for linha in (identificar.normalizar(l) for l in texto.splitlines()
                      if l.strip()):
            if all(re.search(rf"\b{re.escape(p)}\b", linha) for p in partes):
                return True
    return False


# ---------------------------------------------------------------------------
# NOME DO ARQUIVO - rede de seguranca
# ---------------------------------------------------------------------------

def do_nome(nome):
    base = os.path.splitext(nome)[0]
    sufixo_copia_curto = bool(re.search(
        r"[-_]\d{1,2}$", base)
        and re.search(r"[A-ZÀ-Ü][a-zà-ÿ]+[-_]"
                      r"[A-ZÀ-Ü][a-zà-ÿ]+[-_]\d{1,2}$", base))
    base = re.sub(r"^\d{5,}[-_]", "", base)
    base = re.sub(r"[-_]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    # Marcadores de cópia/download não pertencem ao autor. Além de
    # poluir a ficha, impediam reconhecer nomes no fim do arquivo.
    base = re.sub(r"\s*\(\s*\d+\s*\)\s*$", "", base).strip()
    base = re.sub(r"\s+\d{5,}\s*$", "", base).strip()
    base = re.sub(
        r"(?i)\s+(?:ocr|scan|scanned|digitalizado|corrigido|revisado|"
        r"final|limpo|optimized|otimizado|compactado|pesquisavel|"
        r"pesquisável|copia|cópia|copy)\s*$", "", base).strip()
    base = re.sub(r"(?i)\s+v?s20\d{2}\s*$", "", base).strip()
    base = re.sub(r"(?i)\s+(?:pdf|docx?|epub|mobi)\s*$", "", base).strip()
    if sufixo_copia_curto:
        base = re.sub(r"\s+\d{1,2}\s*$", "", base).strip()
    # Marcadores de distribuição não são autor nem parte do título.
    # Sem esta limpeza, ``Livro Digital`` era invertido para o falso autor
    # ``Digital, Livro``.
    base = re.sub(r"(?i)\s+(?:livro\s+digital|e-?book)(?:\s+\d+)?\s*$",
                  "", base).strip()
    base = re.sub(
        r"(?i)^(?:evangelico|evangélico|scribd|z\s*lib(?:rary)?|"
        r"archive|internet\s+archive)\s+", "", base).strip()

    # "The Book Revelation by James H McConkey" ou arquivos OCR antigos em
    # inglês: o marcador "by" é forte o suficiente para separar título e
    # autoria já no nome do arquivo. Sem isso, o "by" podia ficar grudado ao
    # título ou a autoria podia permanecer vazia, fazendo o reprocessamento
    # repetir a mesma troca na bancada.
    m = re.match(r"(?i)^(.{3,180}?)\s+by\s+(.{3,90})$", base)
    if m:
        titulo = limpar_titulo_bibliografico(m.group(1))
        autor_natural = " ".join(m.group(2).split()).strip(" .,:;-")
        if (titulo_bibliograficamente_plausivel(titulo)
                and autor_bibliograficamente_plausivel(autor_natural)):
            return titulo, sobrenome_virgula(autor_natural)

    # "A B Bruce Training of the Twelve": coleções antigas podem trazer o
    # autor por iniciais antes do título, sem "by". Só aceitamos essa forma
    # quando há pelo menos uma inicial e um sobrenome, para não desmontar
    # títulos normais.
    m = re.match(
        r"^((?:[A-Za-z]\s+){2,4}[A-ZÀ-Üa-zà-ÿ]"
        r"[A-Za-zÀ-ÿ'’.-]{2,})\s+(.{3,180})$",
        base)
    if m:
        autor_natural = " ".join(
            p.upper() if len(p) == 1 else p.title()
            for p in m.group(1).split())
        titulo = limpar_titulo_bibliografico(m.group(2))
        if (titulo_bibliograficamente_plausivel(titulo)
                and autor_bibliograficamente_plausivel(autor_natural)):
            return titulo, sobrenome_virgula(autor_natural)

    # ``JOHN-PIPER-Exultacao...``: a transição de duas ou mais palavras
    # inteiramente maiúsculas para texto em caixa normal marca uma autoria
    # inicial. Exigimos essa transição para não desmontar títulos inteiros
    # escritos em caixa alta.
    m = re.match(
        r"^((?:[A-ZÀ-Ü][A-ZÀ-Ü'.]{1,}\s+){1,3})"
        r"(?=[A-ZÀ-Ü][a-zà-ÿ])(.+)$", base)
    if m:
        natural = " ".join(p.title() for p in m.group(1).split())
        return m.group(2).strip(), sobrenome_virgula(natural)

    # caso 1 - "SOBRENOME Nome Titulo...": autor em caixa alta no inicio
    m = re.match(r"^([A-ZÁ-Ú]{3,})\s+([A-Z][a-zá-ú]+(?:\s+[A-Z][a-zá-ú]+)?)\s+(.+)$", base)
    if m:
        return m.group(3).strip(), f"{m.group(1).title()}, {m.group(2)}"

    # caso 2 - "Titulo da Obra Nome Sobrenome": autor no fim.
    # Pega 2 ou 3 palavras capitalizadas no final. Nao e infalivel -
    # "Manual de Billy Graham" tem o nome no proprio titulo - mas um autor
    # provavel vale mais que campo vazio: o registro entra e se corrige
    # depois. A planilha marca a origem como "nome do arquivo" justamente
    # para essas linhas receberem um olhar.
    # Sem um separador inequívoco, capturar três palavras no fim roubava
    # a última palavra do título (``... Church Angela Pellicciari`` e
    # ``... Adoração Domicio Junior``). Dois nomes são uma pista segura;
    # sobrenomes com partícula continuam aceitos como uma unidade.
    m = re.search(r"\b([A-ZÁ-Ú][a-zá-úA-ZÁ-Ú'.]+\s+"
                  r"(?:(?:van|von|de|da|del)\s+)?"
                  r"[A-ZÁ-Ú][a-zá-úA-ZÁ-Ú'.]+)\s*$", base)
    if m:
        cand = m.group(1).strip()
        partes = cand.split()
        # Duas palavras (ou uma partícula interna), nenhuma palavra comum
        # de título.
        comuns = {"El","La","Los","Las","Un","Una","De","Del","O","A","Os","As",
                  "Do","Da","Dos","Das","Le","Les","Un","Une","The","Of","And",
                  "Volumen","Volume","Tomo","Parte","Manual","Curso","Guia",
                  "Biblia","Biblica","Biblico","Crista","Cristao","Igreja",
                  "Teologia","Calvinismo","Agostiniano","Reformada","Missional",
                  "Era","Digital","Tribulation","Revelation","Testament",
                  "Ministry","Service","Services","Doctrine","Scripture"}
        lexical_de_titulo = any(
            re.search(r"(?i)(?:ismo|logia)$", identificar.normalizar(p))
            for p in partes)
        if (2 <= len(partes) <= 3 and not lexical_de_titulo
                and not any(p in comuns for p in partes)):
            titulo = base[: m.start(1)].strip(" -–,")
            if len(titulo) >= 3:
                return titulo, f"{partes[-1]}, {' '.join(partes[:-1])}"

    return base, ""


# ---------------------------------------------------------------------------
# BASES PUBLICAS
# ---------------------------------------------------------------------------

def open_library(isbn):
    if not requests or not isbn:
        return {}
    try:
        r = requests.get("https://openlibrary.org/api/books",
                         params={"bibkeys": f"ISBN:{isbn}", "format": "json",
                                 "jscmd": "data"}, timeout=20)
        d = r.json().get(f"ISBN:{isbn}")
        if not d:
            return {}
        return {
            "titulo":   d.get("title", ""),
            "subtitulo": d.get("subtitle", ""),
            "autores":  "; ".join(a.get("name", "") for a in d.get("authors", [])),
            "editora":  "; ".join(p.get("name", "") for p in d.get("publishers", [])),
            "ano":      (re.search(r"(\d{4})", d.get("publish_date", "")) or [None, ""])[1]
                        if d.get("publish_date") else "",
            "paginas":  str(d.get("number_of_pages", "") or ""),
            "assuntos": "; ".join(s.get("name", "") for s in d.get("subjects", [])[:3]),
            "fonte": "OpenLibrary",
        }
    except Exception:
        return {}

def google_books(isbn):
    if not requests or not isbn:
        return {}
    try:
        r = requests.get("https://www.googleapis.com/books/v1/volumes",
                         params={"q": f"isbn:{isbn}"}, timeout=20)
        j = r.json()
        if j.get("error") or not j.get("totalItems"):
            return {}
        v = j["items"][0]["volumeInfo"]
        return {
            "titulo":   v.get("title", ""),
            "subtitulo": v.get("subtitle", ""),
            "autores":  "; ".join(v.get("authors", [])),
            "editora":  v.get("publisher", ""),
            "ano":      (v.get("publishedDate", "") or "")[:4],
            "paginas":  str(v.get("pageCount", "") or ""),
            "assuntos": "; ".join(v.get("categories", [])[:3]),
            "fonte": "GoogleBooks",
        }
    except Exception:
        return {}


def _controle_para_pdf(caminho):
    atual = pathlib.Path(caminho).resolve().parent
    for _ in range(6):
        controle = atual / "_controle"
        if controle.is_dir():
            return controle
        if atual.parent == atual:
            break
        atual = atual.parent
    return None


def cache_disponivel_localmente(arquivo):
    """Cache remoto nao pode bloquear o preparo; a fonte continua opcional."""
    try:
        return not (sys.platform == "darwin"
                    and getattr(pathlib.Path(arquivo).stat(), "st_flags", 0)
                    & SF_DATALESS)
    except OSError:
        return False


def carregar_fontes_comerciais(caminho):
    """Carrega apenas pesquisas previamente aprovadas pelo conciliador.

    A navegacao e deliberadamente separada da leitura do PDF: assim um
    bloqueio, CAPTCHA ou mudanca no marketplace nunca paralisa o preparo.
    """
    controle = _controle_para_pdf(caminho)
    pasta = controle / "cache-pesquisa-web" if controle else None
    if not pasta or not pasta.is_dir():
        return {"estante": {}, "amazon": {}, "pacotes": []}
    nome = pathlib.Path(caminho).name
    chave_cache = str(pasta.resolve())
    if chave_cache not in _CACHE_FONTES_COMERCIAIS:
        por_arquivo = collections.defaultdict(list)
        for arquivo in pasta.glob("*.json"):
            try:
                # Um placeholder do Dropbox pode bloquear no read() por
                # minutos. A pesquisa comercial continua sendo reaproveitada
                # assim que o cache estiver disponível localmente.
                if not cache_disponivel_localmente(arquivo):
                    continue
                pacote = json.loads(arquivo.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            arquivo_alvo = pacote.get("arquivo", "")
            if arquivo_alvo:
                por_arquivo[arquivo_alvo].append(pacote)
        _CACHE_FONTES_COMERCIAIS[chave_cache] = dict(por_arquivo)
    # O indice e montado uma vez por execução. Antes, cada novo PDF reabria
    # todos os 371 arquivos de cache, multiplicando o custo pelo tamanho do lote.
    pacotes = list(_CACHE_FONTES_COMERCIAIS[chave_cache].get(nome, []))

    estante = {}
    amazon = {}
    for pacote in sorted(pacotes, key=lambda p: p.get("consultado_em", "")):
        d_estante = pacote.get("detalhes_estante") or {}
        avaliacao_estante = d_estante.get("avaliacao") or {}
        estante_aprovada = (not avaliacao_estante or
                            bool(avaliacao_estante.get("aprovado")))
        if d_estante.get("confianca") == "alta" and estante_aprovada:
            estante = dict(d_estante)
        d_amazon = pacote.get("detalhes_amazon") or {}
        pontos = float(pacote.get("pontuacao_amazon") or 0)
        avaliacao_amazon = d_amazon.get("avaliacao") or {}
        amazon_aprovada = (not avaliacao_amazon or
                           bool(avaliacao_amazon.get("aprovado")))
        isbn_alvo = pacote.get("isbn", "")
        isbn_confirmado = bool(d_amazon and isbn_alvo and
                               isbns_equivalentes(
                                   isbn_alvo, d_amazon.get("isbn_10", ""),
                                   d_amazon.get("isbn_13", "")))
        if d_amazon and amazon_aprovada and (pontos >= 0.72 or isbn_confirmado):
            ano = (re.search(r"\b((?:19|20)\d{2})\b",
                             d_amazon.get("data_publicacao", ""))
                   or [None, ""])[1]
            paginas = (re.search(r"\b(\d{1,5})\b", d_amazon.get("paginas", ""))
                       or [None, ""])[1]
            autoria = limpar_autoria_comercial(
                d_amazon.get("autoria_pagina", ""))
            amazon = {
                "titulo": d_amazon.get("titulo_pagina", ""),
                "autores": autoria, "editora": d_amazon.get("editora", ""),
                "ano": ano, "paginas": paginas,
                "edicao": d_amazon.get("edicao", ""),
                "volume": d_amazon.get("volume", ""),
                "isbn_10": d_amazon.get("isbn_10", ""),
                "isbn_13": d_amazon.get("isbn_13", ""),
                "fonte": "Amazon (edição comercial)",
                "url": d_amazon.get("url", ""), "pontuacao": pontos,
                "isbn_confirmado": isbn_confirmado,
                "confianca": "alta" if pontos >= 0.90 or isbn_confirmado
                else "auxiliar",
            }
    return {"estante": estante, "amazon": amazon, "pacotes": pacotes}


def limpar_autoria_comercial(valor):
    """Extrai somente o nome de textos como 'Edição ... por X (Autor)'."""
    texto = " ".join(str(valor or "").split()).strip()
    achado = re.search(
        r"(?i)\b(?:por|by)\s+(.+?)\s*\((?:autor|author|editor|"
        r"organizador|organizer)\)", texto)
    if achado:
        return achado.group(1).strip(" ,-:")
    texto = re.sub(r"(?i)^edi[çc][aã]o\s+\S+\s+(?:por|by)\s+", "", texto)
    return re.sub(
        r"(?i)\s*\((?:autor|author|editor|organizador|organizer)\).*$",
        "", texto).strip()


def conciliar_fontes_comerciais(evidencias, ano_local="", paginas_pdf=""):
    """Estante antiga primeiro; Amazon completa somente campos vazios."""
    estante = evidencias.get("estante") or {}
    amazon = evidencias.get("amazon") or {}
    base = dict(estante) if estante else (
        dict(amazon) if amazon.get("confianca") == "alta" else {})
    if estante and amazon:
        for campo in ("titulo", "autores", "editora", "ano", "paginas",
                      "edicao", "volume"):
            if not base.get(campo):
                base[campo] = amazon.get(campo, "")
        if amazon.get("isbn_confirmado"):
            base["isbn_confirmado"] = True
    # A edicao do PDF vence sempre. Uma reimpressao comercial diferente pode
    # confirmar autor/editora, mas nao pode trocar ano ou paginacao.
    if ano_local and base.get("ano") and str(base["ano"]) != str(ano_local):
        base["ano_divergente"] = base.pop("ano")
    try:
        if (paginas_pdf and base.get("paginas") and
                abs(int(base["paginas"]) - int(paginas_pdf)) >
                max(5, int(paginas_pdf) * 0.20)):
            base["paginas_divergentes"] = base.pop("paginas")
    except (TypeError, ValueError):
        pass
    return base


def rejeicoes_fontes_bibliograficas(fontes_comerciais=None, bnf_candidatos=None,
                                    bnf_escolhido=None, motivo_bnf="",
                                    ia_candidatos=None, ia_escolhido=None,
                                    motivo_ia="", consultas_academicas=None):
    """Registra por que candidatos consultados nao viraram metadado final."""
    rejeicoes = []
    fontes_comerciais = fontes_comerciais or {}
    for pacote in fontes_comerciais.get("pacotes", []) or []:
        alvo = pacote.get("arquivo", "")
        d_estante = pacote.get("detalhes_estante") or {}
        if d_estante:
            motivos = []
            avaliacao = d_estante.get("avaliacao") or {}
            if avaliacao and not avaliacao.get("aprovado"):
                bruto = (avaliacao.get("motivos") or avaliacao.get("motivo")
                         or avaliacao.get("razoes") or "avaliacao reprovada")
                if isinstance(bruto, list):
                    motivos.extend(str(x) for x in bruto if x)
                else:
                    motivos.append(str(bruto))
            if d_estante.get("confianca") and d_estante.get("confianca") != "alta":
                motivos.append(f"confianca {d_estante.get('confianca')}")
            if not any(d_estante.get(c) for c in (
                    "titulo", "autores", "editora", "isbn", "ano", "paginas")):
                motivos.append("anuncio sem metadados bibliograficos")
            if motivos:
                rejeicoes.append({
                    "fonte": "Estante Virtual",
                    "titulo": d_estante.get("titulo", ""),
                    "url": d_estante.get("url", ""),
                    "arquivo": alvo,
                    "motivo": "; ".join(dict.fromkeys(motivos)),
                })
        d_amazon = pacote.get("detalhes_amazon") or {}
        if d_amazon:
            motivos = []
            avaliacao = d_amazon.get("avaliacao") or {}
            if avaliacao and not avaliacao.get("aprovado"):
                bruto = (avaliacao.get("motivos") or avaliacao.get("motivo")
                         or avaliacao.get("razoes") or "avaliacao reprovada")
                if isinstance(bruto, list):
                    motivos.extend(str(x) for x in bruto if x)
                else:
                    motivos.append(str(bruto))
            isbn_alvo = pacote.get("isbn", "")
            isbn_amazon = d_amazon.get("isbn_13", "") or d_amazon.get("isbn_10", "")
            if isbn_alvo and isbn_amazon and not isbns_equivalentes(
                    isbn_alvo, d_amazon.get("isbn_10", ""),
                    d_amazon.get("isbn_13", "")):
                motivos.append("ISBN diferente")
            pontos = float(pacote.get("pontuacao_amazon") or 0)
            if pontos and pontos < 0.72:
                motivos.append(f"pontuacao baixa {pontos:.2f}")
            if not any(d_amazon.get(c) for c in (
                    "titulo_pagina", "autoria_pagina", "editora",
                    "isbn_10", "isbn_13", "data_publicacao", "paginas")):
                motivos.append("pagina sem metadados bibliograficos")
            if motivos:
                rejeicoes.append({
                    "fonte": "Amazon",
                    "titulo": d_amazon.get("titulo_pagina", ""),
                    "url": d_amazon.get("url", ""),
                    "arquivo": alvo,
                    "motivo": "; ".join(dict.fromkeys(motivos)),
                })
    if bnf_candidatos and not bnf_escolhido:
        rejeicoes.append({
            "fonte": "BnF",
            "titulo": "",
            "motivo": motivo_bnf or f"{len(bnf_candidatos)} candidatos sem escolha segura",
        })
    if ia_candidatos and not ia_escolhido:
        rejeicoes.append({
            "fonte": "Internet Archive",
            "titulo": "",
            "motivo": motivo_ia or f"{len(ia_candidatos)} candidatos sem escolha segura",
        })
    for fonte, consultada, escolhida in consultas_academicas or []:
        if consultada and not escolhida:
            rejeicoes.append({
                "fonte": fonte,
                "titulo": "",
                "motivo": "sem candidato suficientemente convergente",
            })
    return rejeicoes[:30]


def editora_confirmada_na_capa(linhas, candidatos=()):
    texto = "\n".join(linhas or [])
    nt = identificar.normalizar(texto)
    for candidato in candidatos:
        nc = identificar.normalizar(candidato or "")
        tokens = [x for x in nc.split() if len(x) > 2 and x not in
                  {"editora", "editorial", "edicoes", "press", "publicacoes"}]
        if nc and (nc in nt or (tokens and all(x in nt for x in tokens))):
            return candidato
    for linha in linhas or []:
        if re.search(r"(?i)\b(?:editora|editorial|edi[çc][õo]es|"
                     r"publica[çc][õo]es|university press)\b", linha):
            valor = " ".join(linha.split()).strip(" .,:;|-_")
            if 3 <= len(valor) <= 70:
                return valor
    return ""


# ---------------------------------------------------------------------------
# MONTAGEM
# ---------------------------------------------------------------------------

def sobrenome_virgula(nome):
    """Converte 'John MacArthur' em 'MacArthur, John' - formato do Biblio."""
    nome = " ".join(nome.split())
    if not nome or "," in nome:
        return nome
    p = nome.split()
    return f"{p[-1]}, {' '.join(p[:-1])}" if len(p) > 1 else nome


def primeiro_autor(nome):
    """Separa o primeiro autor sem desmontar sobrenomes compostos."""
    nome = " ".join((nome or "").split())
    return re.split(r"\s+(?:&|e|y|and)\s+", nome, maxsplit=1,
                    flags=re.I)[0].strip()


def separar_autores(nome):
    """Devolve coautores explícitos sem fundi-los num único nome invertido."""
    texto = " ".join(str(nome or "").split()).strip(" ,;")
    if not texto:
        return []
    partes = re.split(r"\s*;\s*|\s+(?:&|e|y|and)\s+", texto,
                      flags=re.I)
    return [p.strip(" ,;") for p in partes if p.strip(" ,;")]


def limpar_titulo_bibliografico(titulo, autor=""):
    """Remove byline e repetições mecânicas sem reescrever o título."""
    valor = " ".join(str(titulo or "").split()).strip(" .,:;-\"“”")
    if not valor:
        return ""
    valor = re.sub(r"(?i)\s+(?:by|por)$", "", valor).strip(" .,:;-")
    # Sufixos técnicos vindos de nome de arquivo/versão não pertencem ao
    # título bibliográfico. Ex.: ``107 FILMES ERA DIGITAL_VS2025``.
    valor = re.sub(r"(?i)(?:[_\s-]+v?s20\d{2})$", "", valor).strip(" .,:;-_")
    valor, _edicao_no_titulo = separar_edicao_embutida_titulo(valor)
    # Amazon e páginas de crédito às vezes devolvem ``Título, by Autor``.
    byline = re.search(r"(?i)\s*,?\s+(?:by|por)\s+(.{3,90})$", valor)
    if byline:
        candidato = byline.group(1).strip(" .,:;-")
        na = identificar.normalizar((autor or "").replace(",", " "))
        nc = identificar.normalizar(candidato)
        ta = {p for p in na.split() if len(p) > 1}
        tc = {p for p in nc.split() if len(p) > 1}
        if not na or na in nc or nc in na or (ta and ta == tc):
            valor = valor[:byline.start()].strip(" .,:;-")

    # Folhas de rosto diagramadas em blocos frequentemente juntam a linha do
    # autor ao título. Quando o nome completo já foi confirmado por CIP,
    # copyright ou fonte estruturada, retiramos sua ocorrência exata apenas
    # nas bordas do título; nomes que fazem parte do assunto permanecem.
    palavras_valor = valor.split()
    autor_n = identificar.normalizar((autor or "").replace(",", " ")).split()
    variantes_autor = []
    if len(autor_n) >= 2:
        variantes_autor.append(autor_n)
        # "Piper, John" deve reconhecer a linha visual "JOHN PIPER".
        variantes_autor.append(autor_n[1:] + autor_n[:1])
    norm_valor = [identificar.normalizar(p) for p in palavras_valor]
    for variante in variantes_autor:
        n = len(variante)
        restantes = len(palavras_valor) - n
        # Títulos legítimos de uma só palavra são comuns (Romanos,
        # Israelitas, Gálatas). A trava antiga exigia duas palavras e, por
        # isso, mantinha ``ROMANOS Michael J. Gorman`` inteiro. Ainda
        # recusamos resultado vazio e palavra residual muito curta.
        if restantes < 1:
            continue
        if norm_valor[:n] == variante:
            candidato = " ".join(palavras_valor[n:]).strip(" .,:;-")
            if len(identificar.normalizar(candidato)) >= 4:
                palavras_valor = palavras_valor[n:]
                valor = candidato
                break
        if norm_valor[-n:] == variante:
            candidato = " ".join(palavras_valor[:-n]).strip(" .,:;-")
            if len(identificar.normalizar(candidato)) >= 4:
                palavras_valor = palavras_valor[:-n]
                valor = candidato
                break

    palavras = valor.split()
    normalizadas = [identificar.normalizar(p) for p in palavras]
    for tamanho in range(min(6, len(palavras) // 2), 1, -1):
        if normalizadas[:tamanho] == normalizadas[tamanho:2 * tamanho]:
            palavras = palavras[:tamanho] + palavras[2 * tamanho:]
            valor = " ".join(palavras)
            break
    # Marcas decorativas e numeração solta da capa ("5a-", "7-") não
    # pertencem ao título. Preservamos volumes e edições declarados.
    palavras = valor.split()
    if (len(palavras) >= 5
            and re.fullmatch(r"\d{1,2}[A-Za-z]?[-–.]?", palavras[-1])
            and identificar.normalizar(palavras[-2]) not in {
                "volume", "vol", "tomo", "parte", "edicao"}):
        valor = " ".join(palavras[:-1]).strip(" .,:;-")
    return valor


def separar_edicao_embutida_titulo(titulo):
    """Remove edição colada no fim do título e devolve a edição separada."""
    valor = " ".join(str(titulo or "").split()).strip(" .,:;-\"“”")
    if not valor:
        return "", ""
    m = re.search(
        r"(?i)(?:[,;:–—-]|\s)+"
        r"((?:\d{1,2}|primeira|segunda|terceira|quarta|quinta|sexta|"
        r"s[eé]tima|oitava|nona|d[eé]cima))"
        r"[\s.ªºoa]*"
        r"(?:edi[çc][ãa]o|ed\.?|edition)\s*$",
        valor)
    if not m:
        return valor, ""
    base = valor[:m.start()].strip(" .,:;-\"“”")
    if len(identificar.normalizar(base)) < 4:
        return valor, ""
    bruto = identificar.normalizar(m.group(1))
    ordinais = {
        "primeira": "1", "segunda": "2", "terceira": "3",
        "quarta": "4", "quinta": "5", "sexta": "6",
        "setima": "7", "sétima": "7", "oitava": "8",
        "nona": "9", "decima": "10", "décima": "10",
    }
    numero = ordinais.get(bruto, re.sub(r"\D", "", m.group(1)))
    edicao = f"{numero}ª edição" if numero else "edição"
    return base, edicao


def estrutura_de_livro(paginas):
    """Reconhece obra longa mesmo quando sua origem foi DOC/DOCX."""
    texto = "\n".join((paginas or [])[:30])
    capitulos = len(re.findall(r"(?im)^\s*cap[ií]tulo\s+(?:\d+|[ivxlcdm]+|um|dois)",
                               texto))
    secoes = sum(bool(re.search(padrao, texto, re.I | re.M)) for padrao in (
        r"^\s*sum[aá]rio\b|^\s*conte[uú]do\b",
        r"^\s*pref[aá]cio\b|^\s*introdu[çc][aã]o\b",
        r"^\s*bibliografia\b|^\s*[ií]ndice\b",
    ))
    return capitulos >= 2 or (capitulos >= 1 and secoes >= 2)


def autores_com_papeis(autores, texto):
    """Distingue autor, editor, organizador e tradutor declarados na obra."""
    if re.search(r"(?i)\b(?:format|formato)\s*:", autores or ""):
        autores = limpar_autoria_comercial(autores)
    nomes = [x for x in separar_autores(autores)
             if autor_bibliograficamente_plausivel(x)]
    papeis = {}
    padroes = (
        (r"(?im)^\s*([^\n|]{3,80}?)\s*\((editor|organizador|coordenador)\)\s*[-.]?$",
         None),
        (r"(?im)^\s*(editor|organiza[çc][aã]o|coordena[çc][aã]o|tradu[çc][aã]o)"
         r"\s*(?:de|por)?\s*:\s*([^\n|]{3,80})$", "invertido"),
    )
    for padrao, modo in padroes:
        for achado in re.finditer(padrao, texto or ""):
            if modo == "invertido":
                papel, nome = achado.group(1), achado.group(2)
            else:
                nome, papel = achado.group(1), achado.group(2)
            papel_n = identificar.normalizar(papel)
            rotulo = ("Editor" if "editor" in papel_n else
                      "Organizador" if "organiz" in papel_n else
                      "Coordenador" if "coorden" in papel_n else "Tradutor")
            nome_n = identificar.normalizar(nome)
            for candidato in nomes:
                cn = identificar.normalizar(candidato.replace(",", " "))
                if cn and (cn in nome_n or nome_n in cn
                           or set(cn.split()) & set(nome_n.split())):
                    papeis[candidato] = rotulo
    # Capas anglófonas usam construções sem dois-pontos: ``Edited by`` e
    # ``Foreword by``. A função explícita impede que prefaciadores entrem
    # como autores principais apenas porque o catálogo externo os listou.
    funcoes_por = (
        (r"(?im)^\s*Edited\s+by\s+([^\n|]{3,90})\s*$", "Editor"),
        (r"(?im)^\s*Foreword\s+by\s+([^\n|]{3,90})\s*$", "Prefácio"),
        (r"(?im)^\s*Translated\s+by\s+([^\n|]{3,90})\s*$", "Tradutor"),
    )
    for padrao, rotulo in funcoes_por:
        for achado in re.finditer(padrao, texto or ""):
            nome_n = identificar.normalizar(achado.group(1))
            for candidato in nomes:
                cn = identificar.normalizar(candidato.replace(",", " "))
                if cn and (cn in nome_n or nome_n in cn
                           or len(set(cn.split()) & set(nome_n.split())) >= 2):
                    papeis[candidato] = rotulo
    tem_editor = any(x in {"Editor", "Organizador", "Coordenador"}
                     for x in papeis.values())
    return [{"nome": sobrenome_virgula(nome),
             "desc": papeis.get(nome, "Colaborador" if tem_editor else "Autor")}
            for nome in nomes]


def avaliar_paginacao_edicao(paginas_arquivo, paginas_edicao,
                              origem_refluida=False, pagina_dupla=False):
    """Separa paginação catalográfica da paginação do arquivo digital."""
    resultado = {"paginas_arquivo": paginas_arquivo,
                 "paginas_edicao": str(paginas_edicao or ""),
                 "paginacao_refluida": False,
                 "paginacao_dupla": False, "conflito": ""}
    try:
        arquivo, edicao = int(paginas_arquivo), int(paginas_edicao)
    except (TypeError, ValueError):
        return resultado
    falta = edicao - arquivo
    if falta > 0 and falta / edicao > 0.25:
        if origem_refluida:
            resultado["paginacao_refluida"] = True
        elif (pagina_dupla and arquivo > 0
              and 1.65 <= edicao / arquivo <= 2.15):
            # Scans de acervo frequentemente guardam duas páginas impressas
            # em cada folha horizontal. Capas, guardas e anúncios explicam a
            # pequena diferença entre ``arquivo * 2`` e a paginação do livro.
            resultado["paginacao_dupla"] = True
        else:
            resultado["conflito"] = (
                f"PDF pode estar incompleto: {arquivo} paginas, "
                f"a edicao tem {edicao}")
    return resultado


def diagnosticar_parcialidade_pdf(paginas):
    """Detecta lacunas objetivas na paginação impressa do próprio PDF.

    Não usa o tamanho curto como prova: folhetos completos podem ter poucas
    páginas. A marca só é emitida quando várias páginas revelam uma
    sequência editorial e ela começa adiante ou contém um salto real.
    """
    observadas = []
    for indice, pagina in enumerate(paginas or [], 1):
        numeros_indd = re.findall(r"(?i)\.indd\s+(\d{1,4})\b", pagina or "")
        if numeros_indd:
            observadas.append((indice, int(numeros_indd[-1]), "InDesign"))
            continue
        linhas = [" ".join(x.split()) for x in (pagina or "").splitlines()]
        bordas = [x for x in linhas[:4] + linhas[-4:] if x]
        isolados = [int(x) for x in bordas if re.fullmatch(r"\d{1,4}", x)]
        if isolados:
            observadas.append((indice, isolados[-1], "número impresso"))

    if len(observadas) < 3:
        return {"parcial": False, "motivo": "", "paginas_impressas": ""}
    numeros = [numero for _indice, numero, _fonte in observadas]
    saltos = [
        (anterior[1], atual[1])
        for anterior, atual in zip(observadas, observadas[1:])
        if (anterior[2] == atual[2] == "InDesign"
            and atual[1] - anterior[1] > 1)
    ]
    primeira_indice, primeira_util = next(
        ((indice, numero) for indice, numero, _fonte in observadas
         if numero > 1),
        (observadas[0][0], observadas[0][1]))
    motivo = ""
    if saltos:
        a, b = saltos[0]
        motivo = f"paginação impressa salta de {a} para {b}"
    # Paginas preliminares sem numero sao normais. So ha evidencia de um
    # prefixo ausente quando uma das primeiras folhas do proprio arquivo ja
    # traz numeracao adiantada. Se o primeiro numero aparece mais tarde, a
    # diferenca e explicada por capa, creditos, sumario e outras preliminares.
    elif (primeira_indice <= 4 and primeira_util >= 5
          and primeira_util - primeira_indice >= 4):
        motivo = f"primeira paginação impressa identificada é {primeira_util}"
    return {
        "parcial": bool(motivo),
        "motivo": motivo,
        "paginas_impressas": ";".join(str(n) for n in numeros),
    }


TIPOS_SEM_CODIGO_BARRAS = {
    "tese", "dissertação", "trabalho acadêmico", "artigo", "documento",
    "apostila", "sermão", "trecho", "resumo", "revista", "periódico",
    "boletim", "jornal", "apresentação", "arquivo inválido",
}
TIPOS_CADASTRO_ESPECIFICO = {
    "tese", "dissertação", "trabalho acadêmico", "artigo", "documento",
    "apostila", "sermão", "trecho", "resumo", "revista", "periódico",
    "boletim", "jornal", "apresentação",
}

# PowerPoint e congêneres. Uma apresentação NUNCA é livro: não tem ISBN,
# não tem editora e frequentemente não tem autor declarado. Sete arquivos
# .ppt/.pptx ficaram parados em 00-ENTRADA porque nada na esteira os
# convertia - e o Biblio só aceita PDF.
EXTENSOES_APRESENTACAO = {".ppt", ".pptx", ".pps", ".ppsx", ".odp"}


def origem_e_apresentacao(arquivos_origem):
    """A procedência decide o tipo: quem veio de .pptx é apresentação."""
    return any(pathlib.Path(str(p)).suffix.lower() in EXTENSOES_APRESENTACAO
               for p in (arquivos_origem or []))


def _revisao_define_tipo(rev):
    """Decisão humana aprovada sobre o tipo vence a procedência do arquivo."""
    return bool((rev or {}).get("aprovado")
                and (rev.get("campos", {}) or {}).get("tipo_documento"))


def deve_ler_codigo_barras(tipo_documento):
    """Restringe a leitura cara da capa/contracapa a livros e coletâneas."""
    return tipo_documento not in TIPOS_SEM_CODIGO_BARRAS

def processar(caminho, usar_api=True, capa="", paginas=None,
              revisao_caminho=None, nome_origem=None):
    nome = os.path.basename(str(nome_origem or caminho))
    linha = {"arquivo": nome, "conflitos": [], "pendencias": [], "capa": capa}
    rev = revisao_manual(revisao_caminho or caminho)
    arquivos_origem = (rev.get("campos", {}).get(
        "arquivos_origem_importacao", []) if rev else [])
    origem_word = any(pathlib.Path(str(p)).suffix.lower() in {".doc", ".docx"}
                      for p in arquivos_origem)
    origem_apresentacao = origem_e_apresentacao(arquivos_origem)

    paginas = paginas if paginas is not None else paginas_pdftotext(caminho)
    diagnostico = diagnosticar_ocr(caminho, paginas)
    t = "\n".join(paginas[:PAGS_BIBLIOGRAFICAS])
    MOTOR["ultimo"] = "camada do PDF" if t.strip() else "nenhum"
    if len(t.strip()) <= MIN_OCR or qualidade_ocr(t) < LIMIAR_OCR:
        t = texto_inicio(caminho, PAGS_BIBLIOGRAFICAS)
    linha["tem_ocr"] = "sim" if diagnostico["paginas_pesquisaveis"] else "NAO"
    linha["status_ocr"] = diagnostico["status"]
    linha["situacao_ocr"] = diagnostico["status"]
    linha["cobertura_ocr"] = diagnostico["cobertura_pesquisavel"]
    linha["paginas_texto_fraco"] = ",".join(
        str(x) for x in diagnostico["paginas_texto_fraco"])
    linha["paginas_sem_texto"] = ",".join(
        str(x) for x in diagnostico["paginas_sem_texto"])
    linha["motor_texto"] = MOTOR["ultimo"]
    linha["qualidade_ocr"] = diagnostico["qualidade_mediana"]
    linha["paginas_pdf"] = n_paginas(caminho)

    # A classificação textual preliminar é barata e evita renderizar capa e
    # contracapa a 300 dpi em relatórios, artigos, apostilas e outros materiais
    # destinados a uma API específica. Se a camada textual for insuficiente,
    # mantemos a leitura: o reconhecimento visual posterior ainda pode decidir.
    doc = metadados_pdf(caminho)
    tipo_preliminar, _ = tipo_documento_e_autor(
        t, paginas, metadados=doc, nome=nome, origem_word=origem_word)

    # Primeira chave bibliográfica: lê o EAN/ISBN na contracapa (e, se
    # necessário, na capa). Não é OCR e não impede livros antigos sem código.
    if deve_ler_codigo_barras(tipo_preliminar):
        barras = ler_isbn_codigo_barras(caminho, linha["paginas_pdf"])
    else:
        barras = {"isbns": [], "paginas_examinadas": [], "deteccoes": [],
                  "ignorado": f"tipo preliminar: {tipo_preliminar}"}
    linha["isbn_codigo_barras"] = "; ".join(barras["isbns"])

    # Capas, CIP e copyright frequentemente sao imagens, embora todo o miolo
    # tenha uma camada textual perfeita. Complementamos apenas essas paginas;
    # isso nao refaz OCR nem altera o PDF.
    complemento_vision = paginas_bibliograficas_vision(
        caminho, paginas, min(6, PAGS_BIBLIOGRAFICAS))
    for numero, texto_visual in complemento_vision.items():
        paginas[numero - 1] = texto_visual
    if complemento_vision:
        t = "\n".join(paginas[:PAGS_BIBLIOGRAFICAS])
        linha["motor_texto"] = "camada do PDF + OCR bibliográfico seletivo"
    paginas_selecionadas = selecionar_paginas_bibliograficas(paginas)
    numeros_bibliograficos = [numero for numero, _texto in paginas_selecionadas]
    paginas_bibliograficas = [texto for _numero, texto in paginas_selecionadas]
    t_bibliografico = normalizar_rotulos_numeros_ocr(
        "\n".join(paginas_bibliograficas))
    ano = (ano_desta_edicao(t_bibliografico)
           or ano_publicacao(t_bibliografico)
           or ano_romano_editorial(t_bibliografico))
    cp  = ler_copyright(t_bibliografico)
    copyright_original = copyright_parece_da_edicao_original(cp)
    cip = combinar_fichas_catalograficas(
        ler_cip_paginas(paginas_bibliograficas),
        ler_ficha_catalografica_simplificada(paginas_bibliograficas),
        ler_ficha_catalografica_por_sinais(
            paginas[:PAGS_BIBLIOGRAFICAS]))
    ficha_rotulada = ler_ficha_tecnica_rotulada_paginas(
        paginas_bibliograficas)
    if ficha_rotulada:
        for campo, valor in ficha_rotulada.items():
            if valor not in (None, "", []) and not cip.get(campo):
                cip[campo] = valor
    dc_institucional = ler_dcip_institucional_paginas(
        paginas[:PAGS_BIBLIOGRAFICAS])
    if dc_institucional:
        cip.update({k: v for k, v in dc_institucional.items()
                    if v not in (None, "", [])})
    cip_identifica_edicao = cip_tem_identidade_bibliografica(cip)
    tit_nome, aut_nome = do_nome(nome)
    autor_serie = autor_da_serie_obras(paginas, nome)
    autor_folha_confirmado = autor_folha_rosto_confirmado(
        paginas, autor_serie or aut_nome)
    tit_pag, pag_tit, motivo_tit_pag = titulo_nas_paginas_iniciais(
        paginas, pistas=[tit_nome, nome],
        autor=cip.get("autor") or autor_folha_confirmado or aut_nome)
    folha_editorial = metadados_folha_rosto_editorial_antiga(
        paginas_bibliograficas)
    if not autor_folha_confirmado and pag_tit:
        autor_folha_confirmado = autor_folha_rosto_confirmado(
            paginas, aut_nome, pagina_titulo=pag_tit)
    tipo_documento, autor_rotulado = tipo_documento_e_autor(
        t, paginas, metadados=doc, nome=nome, origem_word=origem_word)
    autor_byline_folha = autor_byline_nas_paginas_iniciais(
        paginas, tit_pag or tit_nome)
    if (not autor_rotulado and autor_byline_folha
            and tipo_documento in {"livro", "coletânea"}):
        autor_rotulado = autor_byline_folha
    if (not autor_rotulado and autor_folha_confirmado
            and tipo_documento in {"livro", "coletânea"}):
        autor_rotulado = autor_folha_confirmado
    if (not autor_rotulado and autor_serie
            and tipo_documento in {"livro", "coletânea"}):
        autor_rotulado = autor_serie
    if (not autor_rotulado and folha_editorial.get("autor")
            and tipo_documento in {"livro", "coletânea"}):
        autor_rotulado = folha_editorial["autor"]
    autores_creditos = autores_rotulados_nas_paginas(paginas_bibliograficas)
    if (tipo_documento in {"livro", "coletânea"}
            and autores_creditos and not autor_rotulado):
        autor_rotulado = autores_creditos[0]
    documental = metadados_documentais_rotulados(
        paginas, doc, nome=nome, origem_word=origem_word)
    academico = (metadados_academicos_paginas(paginas)
                 if tipo_documento in TIPOS_ACADEMICOS else {})
    if academico.get("tipo_documento"):
        tipo_documento = academico["tipo_documento"]
    if academico.get("titulo"):
        tit_pag, pag_tit, motivo_tit_pag = (
            academico["titulo"], 1, "folha de rosto acadêmica")
    if academico.get("autor"):
        autor_rotulado = academico["autor"]
    if documental.get("titulo") and not academico:
        tit_pag, pag_tit, motivo_tit_pag = (
            documental["titulo"], 1, "cabeçalho documental explícito")
    if documental.get("autor") and not academico:
        autor_rotulado = documental["autor"]
    if re.search(r"(?i)(?:^|[-_\s])apostila(?:[-_\s.]|$)", nome):
        tipo_documento = "apostila"
        autor_rotulado = ""
    # A procedencia vence a leitura: um slide com muito texto pode parecer
    # apostila ou artigo, mas quem veio de .pptx e apresentacao. Aqui o
    # formato do arquivo E a evidencia - nao ha inferencia envolvida.
    # O autor fica como veio: se a apresentacao declara um, aproveitamos;
    # se nao declara, o tipo dispensa a exigencia (so titulo e obrigatorio).
    if origem_apresentacao and not _revisao_define_tipo(rev):
        tipo_documento = "apresentação"
    artigo = (metadados_artigo_paginas(paginas, nome=nome)
              if tipo_documento == "artigo" else {})
    if artigo.get("titulo"):
        tit_pag, pag_tit, motivo_tit_pag = (
            artigo["titulo"], 1, "cabeçalho de artigo")
    if artigo.get("autor"):
        autor_rotulado = artigo["autor"]

    # Tradução automática e cópia explicitamente não comercial são
    # documentos derivados, não novas edições publicadas. Essa distinção
    # precisa ocorrer antes das pesquisas externas para que o ISBN citado na
    # fonte não transforme o derivado em livro comercial.
    derivacao_editorial = ({}
                           if rev.get("aprovado")
                           else derivacao_editorial_nao_publicada(
                               t_bibliografico))
    if (derivacao_editorial
            and tipo_documento in {"livro", "coletânea"}):
        tipo_documento = "documento"

    # Todos os ISBNs permanecem ligados a pagina, formato e volume. A escolha
    # ocorre depois; nunca mais usamos simplesmente o primeiro ISBN da CIP.
    isbn_cands = [
        {"isbn": isbn, "rotulo": "EAN da capa/contracapa", "ctx": "",
         "linha": "", "formato": "impresso", "volume": "",
         "pagina": next((d.get("pagina") for d in barras["deteccoes"]
                          if isbn_valido(d.get("valor", "")) == isbn), None),
         "origem": "codigo de barras"}
        for isbn in barras["isbns"]
    ]
    isbn_cands.extend(candidatos_isbn_paginas(
        paginas_bibliograficas, numeros_paginas=numeros_bibliograficos))
    isbn_opf = isbn_valido((rev.get("campos", {}) if rev else {}).get("isbn", ""))
    if isbn_opf:
        isbn_cands.append({
            "isbn": isbn_opf, "rotulo": "metadado estruturado OPF",
            "ctx": "", "linha": "", "formato": "impresso", "volume": "",
            "pagina": None, "origem": "arquivo OPF",
        })
    # Quando a camada de texto falha, o operador pode ter conservado o ISBN
    # no nome do arquivo. Ele e uma chave exata e segura para recuperar a
    # ficha; titulo ou autor do nome continuam sendo apenas pistas frageis.
    isbns_vistos = {c["isbn"] for c in isbn_cands}
    for candidato in candidatos_isbn(nome):
        if candidato["isbn"] not in isbns_vistos:
            candidato = dict(candidato)
            candidato["pagina"] = None
            candidato["origem"] = "nome do arquivo"
            isbn_cands.append(candidato)
            isbns_vistos.add(candidato["isbn"])
    linha["isbn"], linha["isbn_motivo"] = escolher_isbn(isbn_cands, nome, ano)

    # ------------------------------------------------------------------
    # Nenhum ISBN valido: antes de desistir, RELER A IMAGEM.
    #
    # O caso que originou isto: "Eu, um Discipulador" traz 978-65-01-24846-2
    # impresso na pagina 3. O pdftotext leu "07" no lugar de "01", o numero
    # nao fechou o verificador, foi descartado em silencio, e a ficha saiu
    # com "sem ISBN - nao localizado". Um digito mal lido bastou.
    #
    # A imagem e evidencia; enumerar correcoes e palpite. Por isso a
    # releitura vem primeiro e a enumeracao so registra candidatos para
    # conferencia - nunca adota sozinha.
    # ------------------------------------------------------------------
    if not linha["isbn"] and conferir_identidade:
        conferencia = conferir_identidade.conferir_isbn(
            caminho, t,
            paginas_candidatas=numeros_bibliograficos or (),
            pagina_cip=cip.get("pagina_cip"))
        linha["isbn_conferencia"] = conferencia
        if conferencia["isbn"]:
            linha["isbn"] = conferencia["isbn"]
            linha["isbn_motivo"] = conferencia["motivo"]
            isbn_cands.append({
                "isbn": conferencia["isbn"], "rotulo": "releitura da imagem",
                "ctx": "", "linha": "", "formato": "impresso", "volume": "",
                "pagina": (conferencia["paginas_relidas"] or [None])[0],
                "origem": "imagem da pagina",
            })
            if conferencia["divergencia"]:
                linha["conflitos"].append(
                    f"ISBN: {conferencia['divergencia']} - a imagem foi "
                    f"adotada; conferir se o livro nao foi impresso com erro")
        else:
            linha["isbn_motivo"] = conferencia["motivo"]
            if conferencia["candidatos"]:
                lista = ", ".join(c["isbn"] for c in conferencia["candidatos"][:6])
                linha["conflitos"].append(
                    f"ISBN impresso ilegivel; correcoes possiveis: {lista}")
            elif conferencia["suspeitos"]:
                linha["conflitos"].append(
                    f"ISBN impresso ilegivel: {conferencia['suspeitos'][0]}")

    linha["isbn_confirmado_na_edicao"] = isbn_confirmado_na_edicao(
        linha["isbn"], isbn_cands, volume_edicao_do_nome(nome))

    api = {}
    api_geral = {}
    cbl = {}
    bnf = {}
    bnf_candidatos = []
    motivo_bnf = ""
    ia = {}
    ia_candidatos = []
    motivo_ia = ""
    loc = {}
    hathitrust = {}
    crossref = {}
    openalex = {}
    core_academico = {}
    grobid = {}
    fonte_academica = {}
    consulta_oatd = ""
    consulta_titulo_autor = {}
    idi = idioma_do_texto(t)
    tipo_antes_grobid = tipo_documento
    tit_pag_antes_grobid = tit_pag
    pag_tit_antes_grobid = pag_tit
    motivo_tit_antes_grobid = motivo_tit_pag
    autor_antes_grobid = autor_rotulado
    reclassificacao_grobid_provisoria = False
    consultou_crossref = False
    consultou_openalex = False
    consultou_core = False

    # O GROBID e uma camada local especializada em cabecalhos academicos.
    # Ele vem antes das bases externas porque fornece uma consulta melhor,
    # mas nao se torna autoridade sozinho. Para reclassificar algo que parecia
    # livro, exigimos DOI identico no PDF, titulo utilizavel e autoria.
    texto_academico = "\n".join(paginas[:8] + paginas[-8:])
    if consultar_grobid:
        cache_grobid = (fontes_biblio.pasta_cache_para_pdf(caminho)
                        if fontes_biblio else
                        pathlib.Path(caminho).resolve().parent
                        / "_controle" / "cache-fontes")
        grobid = consultar_grobid.consultar(
            caminho, tipo_documento, texto_academico,
            linha["paginas_pdf"], cache_grobid)
        linha["grobid_status"] = grobid.get("motivo", "")
        if grobid.get("consultado"):
            dois_pdf = set(consultar_grobid.dois_no_texto(texto_academico))
            doi_grobid = consultar_grobid.normalizar_doi(grobid.get("doi", ""))
            doi_confirmado = bool(doi_grobid and doi_grobid in dois_pdf)
            titulo_grobid = limpar_titulo_bibliografico(
                grobid.get("titulo", ""))
            titulo_periodico = identificar_periodico_conhecido(titulo_grobid)
            titulo_periodico_n = identificar.normalizar(titulo_periodico)
            titulo_grobid_n = identificar.normalizar(titulo_grobid)
            titulo_e_periodico = bool(
                titulo_periodico_n and
                (titulo_grobid_n == titulo_periodico_n
                 or titulo_grobid_n.startswith(titulo_periodico_n + " ")))
            titulo_grobid_ok = bool(
                grobid.get("titulo_aceitavel")
                and titulo_bibliograficamente_plausivel(titulo_grobid)
                and not titulo_e_periodico)
            autores_grobid = [a for a in grobid.get("autores", [])
                              if autor_bibliograficamente_plausivel(a)]
            reparos_autor_grobid = []
            autores_grobid_reparados = []
            for autor_grobid in autores_grobid:
                autor_reparado, motivo_reparo = (
                    consultar_grobid.reparar_autor_truncado(
                        autor_grobid, texto_academico))
                autores_grobid_reparados.append(autor_reparado)
                if motivo_reparo:
                    reparos_autor_grobid.append(motivo_reparo)
            autores_grobid = autores_grobid_reparados
            if reparos_autor_grobid:
                grobid["reparos_autor"] = reparos_autor_grobid

            if (grobid.get("reclassificar_artigo") and doi_confirmado
                    and autores_grobid and (titulo_grobid_ok or usar_api)):
                tipo_documento = "artigo"
                artigo = artigo or {}
                reclassificacao_grobid_provisoria = not titulo_grobid_ok
                # A busca Crossref por DOI nao depende deste titulo. Ele e
                # apenas uma semente temporaria e sera substituido quando o
                # DOI exato devolver o registro estruturado.
                if reclassificacao_grobid_provisoria:
                    artigo["titulo"] = titulo_grobid
            destino_grobid = (artigo if tipo_documento == "artigo" else
                              academico if tipo_documento in TIPOS_ACADEMICOS
                              else None)
            if destino_grobid is not None:
                titulo_atual = limpar_titulo_bibliografico(
                    destino_grobid.get("titulo", ""))
                if (titulo_grobid_ok
                        and (not titulo_bibliograficamente_plausivel(titulo_atual)
                             or doi_confirmado)):
                    destino_grobid["titulo"] = titulo_grobid
                if autores_grobid:
                    destino_grobid["autores_academicos"] = autores_grobid
                    if not destino_grobid.get("autor"):
                        destino_grobid["autor"] = sobrenome_virgula(
                            autores_grobid[0])
                if grobid.get("abstract") and not destino_grobid.get("abstract"):
                    destino_grobid["abstract"] = grobid["abstract"]
                if (grobid.get("palavras_chave")
                        and not destino_grobid.get("palavras_chave")):
                    destino_grobid["palavras_chave"] = "; ".join(
                        grobid["palavras_chave"])
                if grobid.get("periodico") and not destino_grobid.get("editora"):
                    destino_grobid["editora"] = grobid["periodico"]
                if destino_grobid.get("titulo"):
                    tit_pag, pag_tit, motivo_tit_pag = (
                        destino_grobid["titulo"], 1,
                        "cabeçalho acadêmico local (GROBID)")
                if destino_grobid.get("autor"):
                    autor_rotulado = destino_grobid["autor"]
    else:
        linha["grobid_status"] = "módulo GROBID indisponível"

    # Artigos são consultados por DOI quando presente; sem DOI, título e
    # autor precisam formar uma correspondência forte. A fonte externa só
    # completa campos ausentes e nunca vence um cabeçalho local coerente.
    if (usar_api and fontes_biblio and tipo_documento == "artigo"
            and artigo.get("titulo")):
        consultou_crossref = True
        mdoi = re.search(r"(?i)\b(?:doi\s*:\s*|https?://doi\.org/)?"
                         r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", texto_academico)
        doi_consulta = (grobid.get("doi", "")
                        if (consultar_grobid and grobid.get("doi") in
                            set(consultar_grobid.dois_no_texto(texto_academico)))
                        else mdoi.group(1).rstrip(".,;)") if mdoi else "")
        crossref = fontes_biblio.consultar_crossref_artigo(
            artigo.get("titulo", ""), artigo.get("autor", ""),
            fontes_biblio.pasta_cache_para_pdf(caminho),
            doi=doi_consulta)
        if crossref:
            doi_exato = bool(
                doi_consulta and consultar_grobid
                and consultar_grobid.normalizar_doi(crossref.get("doi", ""))
                == consultar_grobid.normalizar_doi(doi_consulta))
            for destino, origem in (("titulo", "titulo"), ("autor", "autores"),
                                    ("ano", "ano"), ("editora", "editora"),
                                    ("issn", "issn")):
                # DOI exato e autoridade superior ao cabecalho probabilistico
                # do GROBID. Sem DOI, a fonte apenas completa ausencias.
                if ((doi_exato or not artigo.get(destino))
                        and crossref.get(origem)):
                    if destino == "autor":
                        autores_crossref = [x.strip() for x in
                                            crossref[origem].split(";")
                                            if x.strip()]
                        artigo["autores_academicos"] = autores_crossref
                        artigo[destino] = (sobrenome_virgula(
                            autores_crossref[0]) if autores_crossref else "")
                    else:
                        artigo[destino] = crossref[origem]
            if artigo.get("titulo"):
                tit_pag, pag_tit, motivo_tit_pag = (
                    artigo["titulo"], 1, "cabeçalho de artigo confirmado")
            if artigo.get("autor"):
                autor_rotulado = artigo["autor"]
        if reclassificacao_grobid_provisoria:
            tipo_crossref = str(crossref.get("tipo_fonte", "")).lower()
            if tipo_crossref not in {
                    "journal-article", "proceedings-article",
                    "posted-content", "report"}:
                tipo_documento = tipo_antes_grobid
                artigo = {}
                tit_pag = tit_pag_antes_grobid
                pag_tit = pag_tit_antes_grobid
                motivo_tit_pag = motivo_tit_antes_grobid
                autor_rotulado = autor_antes_grobid
    # OpenAlex complementa o Crossref e também cobre teses/dissertações.
    # CORE é uma terceira camada opcional. Sem as respectivas chaves, ambas
    # são simplesmente ignoradas e o preparo local continua normalmente.
    if (usar_api and fontes_biblio
            and (tipo_documento == "artigo" or tipo_documento in TIPOS_ACADEMICOS)):
        titulo_academico = limpar_titulo_bibliografico(
            (artigo.get("titulo", "") if tipo_documento == "artigo" else
             academico.get("titulo", "")) or tit_pag or doc.get("titulo", "")
             or tit_nome)
        autor_academico = (
            artigo.get("autor", "") if tipo_documento == "artigo" else
            academico.get("autor", "")) or autor_rotulado or aut_nome
        cache_academico = fontes_biblio.pasta_cache_para_pdf(caminho)
        if (titulo_bibliograficamente_plausivel(titulo_academico)
                and (not autor_academico
                     or autor_bibliograficamente_plausivel(autor_academico))):
            if not crossref:
                consultou_openalex = True
                openalex = fontes_biblio.consultar_openalex_academico(
                    titulo_academico, autor_academico, tipo_documento,
                    cache_academico)
            if not (crossref or openalex):
                consultou_core = True
                core_academico = fontes_biblio.consultar_core_academico(
                    titulo_academico, autor_academico, tipo_documento,
                    cache_academico)
            fonte_academica = crossref or openalex or core_academico
        if tipo_documento in TIPOS_ACADEMICOS:
            consulta_oatd = fontes_biblio.link_oatd(
                titulo_academico, autor_academico)
        if fonte_academica:
            destino = artigo if tipo_documento == "artigo" else academico
            for campo_destino, campo_fonte in (
                    ("titulo", "titulo"), ("autor", "autores"),
                    ("ano", "ano"), ("editora", "editora"),
                    ("instituicao", "instituicao"), ("issn", "issn")):
                if not destino.get(campo_destino) and fonte_academica.get(campo_fonte):
                    destino[campo_destino] = fonte_academica[campo_fonte]
            if destino.get("titulo"):
                tit_pag, pag_tit, motivo_tit_pag = (
                    destino["titulo"], 1, "fonte acadêmica internacional")
            if destino.get("autor"):
                autor_rotulado = sobrenome_virgula(
                    destino["autor"].split(";")[0].strip())
    if usar_api and linha["isbn"]:
        leitura_local_fraca = (diagnostico["status"] != "OCR aprovado"
                               or MOTOR["ultimo"] in ("nenhum", "camada do PDF (fraca)"))
        dados_locais_incompletos = not (
            (cp.get("titulo_edicao") or cip.get("titulo") or tit_pag or doc.get("titulo"))
            and (cip.get("autor") or doc.get("autor") or autor_do_copyright(t)[0])
            and (cp.get("editora") or cip.get("editora"))
            and (ano or cip.get("ano")))
        if (consultar_cbl and consultar_cbl.isbn_brasileiro(linha["isbn"])
                and (leitura_local_fraca or dados_locais_incompletos or not api_geral)):
            cbl = consultar_cbl.consultar(
                linha["isbn"], consultar_cbl.pasta_cache_para_pdf(caminho))
        isbn_francofono = (linha["isbn"].startswith("9782")
                           or (len(linha["isbn"]) == 10
                               and linha["isbn"].startswith("2")))
        if (fontes_biblio and (idi == "fre" or isbn_francofono)
                and (leitura_local_fraca or dados_locais_incompletos)):
            cache_fontes = fontes_biblio.pasta_cache_para_pdf(caminho)
            bnf_candidatos = fontes_biblio.consultar_bnf(
                linha["isbn"], cache_fontes)
            bnf, motivo_bnf = fontes_biblio.resolver_candidatos(
                bnf_candidatos, ano=ano or cip.get("ano", ""),
                paginas=cip.get("paginas", "") or linha["paginas_pdf"],
                titulo=cp.get("titulo_edicao") or cip.get("titulo", "")
                       or tit_pag or doc.get("titulo", ""))
            if bnf_candidatos and not bnf:
                linha["conflitos"].append(f"BnF: {motivo_bnf}; edicao nao escolhida")

        if fontes_biblio and not (cbl or bnf):
            cache_fontes = fontes_biblio.pasta_cache_para_pdf(caminho)
            api_geral = fontes_biblio.consultar_open_library(
                linha["isbn"], cache_fontes)
            if not api_geral:
                api_geral = fontes_biblio.consultar_google_books(
                    linha["isbn"], cache_fontes)
            # Catálogos anglófonos entram depois das duas bases gerais. Eles
            # são particularmente úteis para livros antigos e editoras dos EUA.
            if not api_geral and idi == "eng":
                loc = fontes_biblio.consultar_library_of_congress(
                    linha["isbn"], cache_fontes)
                api_geral = loc
            if not api_geral and idi == "eng":
                hathitrust = fontes_biblio.consultar_hathitrust(
                    linha["isbn"], cache_fontes)
                api_geral = hathitrust
        elif not fontes_biblio:
            api_geral = open_library(linha["isbn"]) or google_books(linha["isbn"])

        # O Internet Archive ajuda a recuperar uma pista quando todas as
        # bases anteriores falham, mas nunca deixa o registro pronto sozinho.
        if (fontes_biblio and not (cbl or bnf or api_geral)
                and (leitura_local_fraca or dados_locais_incompletos)):
            cache_fontes = fontes_biblio.pasta_cache_para_pdf(caminho)
            ia_candidatos = fontes_biblio.consultar_internet_archive(
                linha["isbn"], cache_fontes)
            ia, motivo_ia = fontes_biblio.resolver_candidatos(
                ia_candidatos, ano=ano or cip.get("ano", ""),
                paginas=cip.get("paginas", "") or linha["paginas_pdf"],
                titulo=cp.get("titulo_edicao") or cip.get("titulo", "")
                       or tit_pag or doc.get("titulo", ""))
            if ia:
                linha["conflitos"].append(
                    "dados recuperados do Internet Archive exigem revisao da edicao")
            elif ia_candidatos:
                linha["conflitos"].append(
                    f"Internet Archive: {motivo_ia}; edicao nao escolhida")
        api = cbl or bnf or api_geral or ia
        time.sleep(0.4)

    # Livros antigos ou digitalizações refluídas de Word podem não ter
    # ISBN. Nesses casos, título + autor consultam o Google Books, mas só um
    # resultado forte e não ambíguo entra na ficha.
    if (usar_api and not linha["isbn"] and fontes_biblio
            and (tipo_documento in {"livro", "coletânea"} or origem_word)):
        titulo_consulta = limpar_titulo_bibliografico(
            cp.get("titulo_edicao") or cip.get("titulo", "") or tit_pag
            or doc.get("titulo", "") or tit_nome)
        autor_consulta = (cip.get("autor") or autor_rotulado or aut_nome)
        if (titulo_bibliograficamente_plausivel(titulo_consulta)
                and autor_bibliograficamente_plausivel(autor_consulta)):
            cache_fontes = fontes_biblio.pasta_cache_para_pdf(caminho)
            consulta_titulo_autor = (
                fontes_biblio.consultar_google_books_titulo_autor(
                    titulo_consulta, autor_consulta, cache_fontes))
            if not consulta_titulo_autor and idi == "eng":
                consulta_titulo_autor = (
                    fontes_biblio.consultar_library_of_congress_titulo_autor(
                        titulo_consulta, autor_consulta, cache_fontes))
            if consulta_titulo_autor:
                api_geral = consulta_titulo_autor
                api = dict(consulta_titulo_autor)
                linha["isbn_sugerido_por_titulo_autor"] = api.get("isbn", "")
                if origem_word and estrutura_de_livro(paginas):
                    tipo_documento = "livro"
                    documental = {}

    # Uma URL nas páginas iniciais pode ativar a heurística documental antes
    # que o ISBN seja lido. A ficha estruturada por ISBN, porém, prova que se
    # trata de livro e deve corrigir essa classificação preliminar.
    if deve_reclassificar_documento_como_livro(
            tipo_documento, documental,
            linha["isbn_confirmado_na_edicao"], api_geral or cbl or bnf,
            linha["paginas_pdf"]):
        tipo_documento = "livro"
        documental = {}
        academico = {}
        artigo = {}

    # Marca a resposta estruturada antes de complementar com marketplaces.
    # Assim uma coincidencia comercial apenas textual nao se apresenta como
    # se fosse uma consulta exata pelo ISBN.
    fonte_estruturada_por_isbn = bool(
        cbl or bnf or (api_geral and not consulta_titulo_autor))

    # Marketplaces nao decidem sozinhos. O navegador coleta e concilia em
    # outra etapa; aqui apenas consumimos evidencias de alta confianca ja
    # guardadas em cache. A Estante tende a representar a edicao antiga do
    # PDF; a Amazon fica como complemento para obras comerciais recentes.
    fontes_comerciais = (
        carregar_fontes_comerciais(caminho)
        if usar_api and tipo_documento in {"livro", "coletânea"}
        else {"estante": {}, "amazon": {}, "pacotes": []})
    # A Estante Virtual é uma fonte comercial brasileira. Em obras inglesas,
    # seus resultados são ruído e não participam da decisão bibliográfica.
    if idi == "eng" and fontes_comerciais.get("estante"):
        fontes_comerciais = dict(fontes_comerciais)
        fontes_comerciais["estante"] = {}
    comercial = conciliar_fontes_comerciais(
        fontes_comerciais, ano_local=ano or cip.get("ano", ""),
        paginas_pdf=cip.get("paginas", "") or linha["paginas_pdf"])
    if comercial:
        if not api:
            api = dict(comercial)
        else:
            for campo in ("titulo", "subtitulo", "autores", "editora",
                          "ano", "paginas", "assuntos"):
                if not api.get(campo) and comercial.get(campo):
                    api[campo] = comercial[campo]
            if comercial.get("fonte") and comercial["fonte"] not in api.get("fonte", ""):
                api["fonte"] = " + ".join(
                    x for x in (api.get("fonte", ""), comercial["fonte"]) if x)

    # A capa deixa de ser apenas ultimo recurso. Ela confirma desde ja o que
    # as fontes externas afirmam e vence metadados internos genericos como
    # "Miolo" ou nomes de quem produziu o arquivo.
    capa_info = {}
    if lercapa and linha.get("capa"):
        try:
            autor_pista = (cip.get("autor") or api.get("autores", "")
                           or doc.get("autor", "") or aut_nome)
            capa_info = lercapa.ler(linha["capa"], autor_conhecido=autor_pista)
            if capa_tecnica_digitalizacao(capa_info):
                capa_info = {
                    "_ignorada": "página técnica de digitalização/microfilme",
                    "_texto_ocr": capa_info.get("texto_ocr", []),
                    "_titulo_descartado": capa_info.get("titulo", ""),
                    "_autor_descartado": capa_info.get("nmAutor0", ""),
                }
        except Exception:
            capa_info = {}

    if not cip_identifica_edicao:
        cip_visual = ler_cip_ocr_visual_capa(capa_info)
        if cip_tem_identidade_bibliografica(cip_visual):
            cip.update({k: v for k, v in cip_visual.items()
                        if v not in (None, "", [])})
            cip_identifica_edicao = True
            vistos = {c["isbn"] for c in isbn_cands}
            for isbn, rotulo in cip.get("isbns", []) or []:
                if isbn not in vistos:
                    isbn_cands.append({
                        "isbn": isbn, "rotulo": rotulo or "CIP visual",
                        "ctx": "CIP lida pelo OCR visual da capa/página inicial",
                        "linha": "", "formato": "", "volume": "",
                        "pagina": cip.get("pagina_cip", 1),
                    })
                    vistos.add(isbn)
            if not linha.get("isbn") and isbn_cands:
                linha["isbn"], linha["isbn_motivo"] = escolher_isbn(
                    isbn_cands, nome, ano)

    # Um ISBN confirmado na propria edicao e a chave bibliografica primaria.
    # Quando a fonte estruturada devolve esse ISBN exato, seus dados vencem
    # OCR, capa, nome de arquivo e metadados internos do PDF.
    # O nome do arquivo NAO entra aqui. Ele e a ultima rede, la embaixo:
    # como nunca vem vazio, se entrasse agora bloquearia todas as fontes
    # melhores que vem depois - foi o que deixou "E i" e "Manual de" de pe.
    # Uma ficha CIP consistente foi preparada especificamente para identificar
    # a obra e vence leituras visuais da capa, da folha inicial e metadados do
    # arquivo. A unica autoridade superior e uma ficha externa localizada por
    # ISBN confirmado na propria edicao (inclusive codigo de barras).
    titulo = (cip.get("titulo", "") if cip_identifica_edicao else "")
    origem_tit = "cip" if titulo else ""
    if not titulo:
        titulo = cp["titulo_edicao"] or cip.get("titulo", "") or tit_pag
        origem_tit = ("copyright" if cp["titulo_edicao"] else
                      "cip" if cip.get("titulo") else
                      motivo_tit_pag if titulo else "")

    # Metadados internos bons vencem uma segmentacao evidentemente quebrada
    # da folha de rosto. Eles continuam sendo apenas evidencia auxiliar.
    titulo_repete_autor_local = bool(
        titulo and any("titulo parece conter ou repetir o nome do autor" in a
                       for a in alertas_plausibilidade_metadados(
                           titulo, cip.get("autor") or aut_nome
                           or doc.get("autor", ""), "")))
    tokens_titulo = identificar.normalizar(titulo or "").split()
    tokens_autor_pdf = identificar.normalizar(doc.get("autor", "")).split()
    autor_pdf_dentro_titulo = sum(
        1 for token_autor in tokens_autor_pdf if len(token_autor) > 2
        and any(difflib.SequenceMatcher(None, token_autor, token_titulo).ratio()
                >= 0.84 for token_titulo in tokens_titulo))
    titulo_parece_autor_do_pdf = bool(
        titulo and doc.get("autor")
        and (similaridade_titulos(titulo, doc.get("autor", "")) >= 0.72
             or autor_pdf_dentro_titulo >= min(2, len(tokens_autor_pdf))))
    titulo_fragmento_do_pdf = bool(
        titulo and doc.get("titulo")
        and titulo_local_e_fragmento_do_confirmado(titulo, doc["titulo"]))
    if (doc.get("titulo") and titulo
            and (not titulo_bibliograficamente_plausivel(titulo)
                 or titulo_parece_autor_do_pdf
                 or titulo_fragmento_do_pdf
                 or (titulo_repete_autor_local
                     and similaridade_titulos(titulo, doc["titulo"]) >= 0.55))
            and titulo_bibliograficamente_plausivel(doc["titulo"])):
        titulo, origem_tit = doc["titulo"], "metadado do PDF confirmado"

    tit_api = api.get("titulo") or ""
    sub_api = api.get("subtitulo") or ""
    tit_api_cheio = (tit_api + (f": {sub_api}" if sub_api else "")) if tit_api else ""
    # Todas as consultas estruturadas acima recebem o ISBN como chave exata.
    # O Internet Archive e a unica excecao: ele pode devolver candidatos e
    # continua exigindo conciliacao. Nao pedimos uma segunda confirmacao que
    # acabaria anulando a propria consulta por ISBN.
    api_por_isbn_exato = bool(api and linha["isbn"] and api is not ia)
    api_por_titulo_autor = bool(
        consulta_titulo_autor
        and consulta_titulo_autor.get("correspondencia") == "titulo_autor"
        and consulta_titulo_autor.get("confianca") == "alta")

    if tit_api and (titulo or api_por_isbn_exato):
        # ATENCAO a string vazia: `"" in qualquer_coisa` e sempre True, e foi
        # isso que fez "Se Lider" virar "Lead" e a Dogmatica virar "Reformed
        # dogmatics". So comparamos quando ha os DOIS lados.
        similaridade_api = similaridade_titulos(titulo, tit_api)
        mesmo = similaridade_api >= 0.68
        autor_api_titulo = sobrenome_virgula(
            (api.get("autores") or "").split(";")[0].strip())
        titulo_repete_autor = (
            "titulo parece conter ou repetir o nome do autor" in
            alertas_plausibilidade_metadados(titulo, autor_api_titulo, ""))
        titulo_local_defeituoso = (
            origem_tit == "nome do arquivo"
            or not titulo_bibliograficamente_plausivel(titulo)
            or any("titulo" in alerta for alerta in
                   alertas_plausibilidade_metadados(titulo, "", "")))
        fragmento_do_confirmado = titulo_local_e_fragmento_do_confirmado(
            titulo, tit_api)
        if (api_por_isbn_exato
                and titulo_bibliograficamente_plausivel(tit_api)):
            titulo, origem_tit = tit_api, "API por ISBN confirmado na edição"
            linha["subTitulo"] = sub_api
        elif (api_por_titulo_autor and (mesmo or titulo_local_defeituoso)
                and titulo_bibliograficamente_plausivel(tit_api)):
            titulo, origem_tit = tit_api, "Google Books por título e autor"
            linha["subTitulo"] = sub_api
        elif (cbl and not titulo_bibliograficamente_plausivel(titulo)
                and titulo_bibliograficamente_plausivel(tit_api)):
            titulo, origem_tit = tit_api, "CBL por ISBN exato"
            linha["subTitulo"] = sub_api
        elif (comercial.get("confianca") == "alta"
              and titulo_local_defeituoso
              and titulo_bibliograficamente_plausivel(tit_api)):
            titulo, origem_tit = tit_api, "fonte comercial de alta confiança"
            linha["subTitulo"] = sub_api
        elif mesmo or (comercial.get("isbn_confirmado") and titulo_repete_autor):
            titulo, origem_tit = tit_api, "api"     # mesma obra, mesma lingua
            linha["subTitulo"] = sub_api
        else:
            # O ISBN da pagina de creditos de uma traducao e o da EDICAO
            # ORIGINAL. Entao o titulo da API nao substitui o nosso - ele e
            # o titulo original, que no biblio tem campo proprio.
            linha["titulo_original"] = tit_api_cheio

    # O metadado interno costuma conservar o titulo original quando a capa
    # textual desapareceu. Usamos antes do OCR da capa, mas mantemos alerta
    # se o idioma do titulo nao combinar com o conteudo.
    titulo_visual_capa = capa_info.get("titulo_visual", "")
    titulo_atual_fraco = (
        not titulo_bibliograficamente_plausivel(titulo)
        or any("chamada editorial da capa" in alerta
               or "promocional" in alerta
               for alerta in alertas_plausibilidade_metadados(titulo, "", "")))
    if (titulo_visual_capa
            and titulo_bibliograficamente_plausivel(titulo_visual_capa)
            and (not titulo or titulo_atual_fraco)):
        titulo, origem_tit = titulo_visual_capa, "título visual da capa"
    if (capa_info.get("titulo") and titulo
            and titulo_bibliograficamente_plausivel(capa_info["titulo"])
            and not titulo_bibliograficamente_plausivel(titulo)):
        titulo, origem_tit = capa_info["titulo"], "capa substituiu OCR implausivel"
    if not titulo and doc.get("titulo"):
        titulo, origem_tit = doc["titulo"], "metadado do PDF"
    if not titulo and capa_info.get("titulo"):
        titulo, origem_tit = capa_info["titulo"], "capa"

    # --- autor, em ordem de autoridade:
    #     CIP > API > capa confirmada > metadado interno > copyright > arquivo
    #
    # O copyright cai para depois da API porque foi ele que nos deu Lubbers
    # e Bolt no lugar de Bavinck: o (c) pertence ao tradutor ou ao
    # organizador com frequencia.
    aut_cip = sobrenome_virgula(cip.get("autor", ""))
    aut_cp, _motivo_cp = autor_do_copyright(t_bibliografico)
    autores_api = separar_autores(api.get("autores", ""))
    editora_api_n = identificar.normalizar(api.get("editora", ""))
    autores_api = [a for a in autores_api
                   if identificar.normalizar(a) != editora_api_n]
    aut_api = sobrenome_virgula(autores_api[0]) if autores_api else ""
    # Uma regex de CIP pode atravessar para o prefacio e formar uma frase
    # enorme. Nesse caso, uma autoria estruturada de CBL/BNF/IA e mais segura.
    if aut_cip and not autor_bibliograficamente_plausivel(aut_cip):
        aut_cip = ""
    if aut_api and not autor_bibliograficamente_plausivel(aut_api):
        aut_api = ""
    aut_doc = sobrenome_virgula(primeiro_autor(doc.get("autor", "")))
    if aut_doc and not autor_confirmado_nas_paginas(paginas, aut_doc):
        aut_doc = ""

    autor_rotulado_plausivel = (
        autor_rotulado if autor_bibliograficamente_plausivel(autor_rotulado)
        else "")
    sobrenome_cip = identificar.normalizar(aut_cip.split(",")[0])
    sobrenome_api = identificar.normalizar(aut_api.split(",")[0])
    api_confirma_cip = bool(
        sobrenome_cip and sobrenome_api
        and difflib.SequenceMatcher(None, sobrenome_cip, sobrenome_api).ratio() >= 0.82)
    autores_capa = separar_autores(capa_info.get("nmAutor0", ""))
    aut_capa = sobrenome_virgula(autores_capa[0]) if autores_capa else ""
    sobrenome_capa = identificar.normalizar(aut_capa.split(",")[0])
    sobrenome_nome = identificar.normalizar(aut_nome.split(",")[0])
    capa_confirma_nome = bool(
        aut_capa and aut_nome and sobrenome_capa and sobrenome_nome
        and difflib.SequenceMatcher(None, sobrenome_capa, sobrenome_nome).ratio() >= 0.72)
    if api_por_isbn_exato and aut_api:
        autor, origem_aut = aut_api, "API por ISBN confirmado na edição"
    elif aut_cip:
        autor, origem_aut = aut_cip, "cip"
    elif autor_serie:
        autor, origem_aut = autor_serie, "autor confirmado pela série de obras"
    elif aut_doc:
        autor, origem_aut = aut_doc, "metadado do PDF confirmado"
    elif capa_confirma_nome:
        autor, origem_aut = aut_nome, "capa confirmou autor do nome do arquivo"
    elif api_por_titulo_autor and aut_api:
        autor, origem_aut = aut_api, "Google Books por título e autor"
    elif autor_rotulado_plausivel:
        autor, origem_aut = autor_rotulado, "rotulo documental"
    elif aut_api:
        autor, origem_aut = aut_api, "api"
    elif (capa_info.get("nmAutor0")
          and capa_info.get("confianca") == "alta"):
        autor, origem_aut = capa_info["nmAutor0"], "capa confirmada"
    elif (aut_cp and aut_doc
          and aut_cp.split(",")[0].lower() == aut_doc.split(",")[0].lower()):
        autor, origem_aut = aut_cp, "copyright confirmado pelo PDF"
    elif aut_cp:
        autor, origem_aut = aut_cp, "copyright"
    else:
        autor, origem_aut = aut_nome, ("nome do arquivo" if aut_nome else "")

    if (origem_aut == "nome do arquivo"
            and autor_confirmado_nas_paginas(paginas, autor)):
        origem_aut = "folha de rosto"

    # Folha de rosto em uma linha só: "Título Pelo/Por Dr. Autor".
    # Essa estrutura é explícita o bastante para corrigir a troca recorrente
    # entre título e autor, mas não vence ISBN/CIP/API exata.
    titulo_byline, autor_byline = titulo_autor_por_byline_folha(tit_pag)
    if (titulo_byline and autor_byline
            and not api_por_isbn_exato
            and not cip_identifica_edicao):
        titulo_atual_n = identificar.normalizar(titulo)
        titulo_byline_n = identificar.normalizar(titulo_byline)
        autor_atual_n = identificar.normalizar(autor.replace(",", " "))
        autor_byline_n = identificar.normalizar(autor_byline.replace(",", " "))
        autor_parece_titulo = bool(
            autor_atual_n and titulo_byline_n
            and (autor_atual_n in titulo_byline_n
                 or titulo_byline_n.startswith(autor_atual_n)
                 or similaridade_titulos(autor, titulo_byline) >= 0.55))
        titulo_parece_autor = bool(
            titulo_atual_n and autor_byline_n
            and (titulo_atual_n in autor_byline_n
                 or re.search(r"(?i)\b(?:pelo|pela|por)\b", titulo or "")))
        if (origem_tit in {"folha de rosto", motivo_tit_pag, "",
                           "capa", "título visual da capa"}
                and (titulo_parece_autor
                     or not titulo_bibliograficamente_plausivel(titulo)
                     or len(titulo.split()) <= 3)):
            titulo, origem_tit = titulo_byline, "folha de rosto"
        if (origem_aut in {"rotulo documental", "folha de rosto",
                           "capa confirmada", "capa", "nome do arquivo", ""}
                and (autor_parece_titulo
                     or not autor_bibliograficamente_plausivel(autor))):
            autor, origem_aut = autor_byline, "folha de rosto"

    # Proteção final contra a troca recorrente "título virou autor" em obras
    # antigas em inglês. Quando o arquivo traz uma autoria plausível e o
    # autor escolhido pelo OCR é apenas parte do título ("Twelve, Training of
    # the", "Spirit, The"), o nome do arquivo corrige a autoria. Se o título
    # local também parece subtítulo, o título do arquivo assume o campo
    # principal e o anterior fica como subtítulo.
    if (aut_nome and autor_bibliograficamente_plausivel(aut_nome)
            and not api_por_isbn_exato and not cip_identifica_edicao):
        autor_norm = identificar.normalizar(autor.replace(",", " "))
        titulo_norm = identificar.normalizar(titulo or "")
        nome_titulo_norm = identificar.normalizar(tit_nome or "")
        partes_autor = {p for p in autor_norm.split() if len(p) > 2}
        partes_titulo = {p for p in titulo_norm.split() if len(p) > 2}
        partes_nome_titulo = {
            p for p in nome_titulo_norm.split() if len(p) > 2}
        autor_e_pedaco_de_titulo = bool(
            autor and partes_autor
            and (partes_autor <= partes_titulo
                 or partes_autor <= partes_nome_titulo
                 or similaridade_titulos(autor, titulo) >= 0.55
                 or similaridade_titulos(autor, tit_nome) >= 0.55))
        if (autor_e_pedaco_de_titulo
                and origem_aut in {"rotulo documental", "folha de rosto",
                                   "capa confirmada", "capa",
                                   "nome do arquivo", ""}):
            autor, origem_aut = aut_nome, "nome do arquivo corrigiu autor-título"
            if (tit_nome and titulo_bibliograficamente_plausivel(tit_nome)
                    and origem_tit in {"folha de rosto", "metadado do PDF",
                                       "capa", "título visual da capa", ""}
                    and similaridade_titulos(titulo, tit_nome) < 0.45):
                if titulo_bibliograficamente_plausivel(titulo):
                    linha.setdefault("subTitulo", titulo)
                titulo, origem_tit = (
                    tit_nome, "nome do arquivo corrigiu autor-título")

    # Divergencia entre copyright e API so vira conflito quando ELA AINDA
    # IMPORTA - ou seja, quando o autor que escolhemos veio de um dos dois.
    # Se o CIP ja decidiu (a ficha do bibliotecario), o desacordo entre as
    # outras duas fontes e ruido: foi o caso dos tres Bavinck, marcados
    # como conflito enquanto o dado estava certo.
    if (aut_cp and aut_api
            and aut_cp.split(",")[0].lower() != aut_api.split(",")[0].lower()
            and origem_aut not in (
                "cip", "honorifico", "API por ISBN confirmado na edição")):
        linha["conflitos"].append(f"autor: copyright={aut_cp} / api={aut_api}")

    # --- ainda falta titulo? a linha de copyright costuma traze-lo inteiro
    if not titulo or len(titulo.split()) < 2:
        tc = titulo_da_linha_copyright(t_bibliografico,
                                       pistas=[tit_nome, nome])
        if tc:
            titulo, origem_tit = tc, "linha de copyright"

    # --- ainda falta algo? a folha de rosto (pagina 1)
    if not titulo or not autor:
        fr = ler_folha_rosto(caminho, autor_conhecido=autor,
                             pistas=[tit_nome, nome])
        if not titulo and fr.get("titulo"):
            titulo, origem_tit = fr["titulo"], "folha de rosto"
        if not autor and fr.get("nmAutor0"):
            autor, origem_aut = fr["nmAutor0"], "folha de rosto"

    # --- ultimo recurso: a capa (Vision + NER). So entra quando as fontes
    #     de texto nao resolveram - e o caso do livro sem ficha nenhuma.
    if not titulo and capa_info.get("titulo"):
        titulo, origem_tit = capa_info["titulo"], "capa"
    if not autor and capa_info.get("nmAutor0"):
        autor, origem_aut = capa_info["nmAutor0"], "capa"

    # --- nenhuma fonte nossa deu titulo: fica o da API, avisando que pode
    #     estar no idioma original (o ISBN e o da edicao original)
    if not titulo and tit_api_cheio:
        titulo, origem_tit = tit_api_cheio, "api (idioma original?)"
        if not api_por_isbn_exato:
            linha["conflitos"].append(
                "titulo veio da API - pode estar no idioma original")
        linha["titulo_original"] = ""

    if (titulo and tit_nome and origem_tit in {
            "capa", "folha de rosto", "metadado do PDF",
            "capa substituiu OCR implausivel", "título da apresentação",
            "cabeçalho documental explícito"}):
        titulo_nome_expandido, nome_confirmou_titulo = (
            titulo_orientado_pelo_nome_arquivo(titulo, tit_nome))
        if nome_confirmou_titulo:
            titulo = titulo_nome_expandido
            origem_tit = f"{origem_tit} confirmada pelo nome do arquivo"

    # Proteção geral: quando qualquer camada local devolve uma frase narrativa
    # ou um parágrafo inteiro como "título", o nome limpo do arquivo é uma
    # bússola mais segura para a revisão. Foi o que aconteceu com
    # "Os Moravianos e as Missões": a primeira página virou quase o artigo
    # inteiro, travando a bancada e escondendo os itens seguintes.
    if (titulo and tit_nome
            and titulo_parece_prosa_ou_artigo_inteiro(titulo)
            and titulo_bibliograficamente_plausivel(tit_nome)):
        titulo, origem_tit = tit_nome, "nome do arquivo substituiu prosa da capa"

    # --- so agora o nome do arquivo, e sempre marcado como frageil:
    #     "Herramienta para lideres de jovenes" era, na verdade,
    #     "Aprende a ser un lider como Jesus" - o Scribd rotula errado.
    if not titulo and tit_nome:
        titulo, origem_tit = tit_nome, "nome do arquivo"
    if not autor and aut_nome:
        autor, origem_aut = aut_nome, "nome do arquivo"
    # O nome do arquivo so preocupa quando NINGUEM o confirma. Nos tres
    # casos deste lote o autor vinha do arquivo e estava certo, batendo
    # com o copyright - marcar como conflito era so barulho.
    if origem_aut == "nome do arquivo" and not (aut_cp or aut_api or aut_cip):
        linha["conflitos"].append(f"autor so do nome do arquivo: {autor}")
    if origem_tit == "nome do arquivo":
        linha["conflitos"].append(f"titulo so do nome do arquivo: {titulo}")

    # Documentos não devem herdar nomes produzidos pelas heurísticas de
    # livros. Um cabeçalho explícito vence parágrafos, referências e o nome
    # do arquivo; se a autoria não estiver declarada ela permanece vazia.
    # Isso é informação bibliográfica honesta, não uma pendência técnica.
    livro_word = {}
    if tipo_documento in TIPOS_ACADEMICOS and academico:
        if academico.get("titulo"):
            titulo = academico["titulo"]
            origem_tit = ("fonte acadêmica internacional" if fonte_academica
                          else "GROBID local" if grobid.get("consultado")
                          else "folha de rosto acadêmica")
        if academico.get("autor"):
            autor = academico["autor"]
            origem_aut = ("fonte acadêmica internacional" if fonte_academica
                          else "GROBID local" if grobid.get("consultado")
                          else "autoria da folha de rosto acadêmica")
        linha["conflitos"] = [
            c for c in linha["conflitos"]
            if not any(rotulo in c for rotulo in (
                "autor so do nome do arquivo", "titulo so do nome do arquivo",
                "titulo veio da API", "autor: copyright="))
        ]
    elif tipo_documento == "artigo" and artigo:
        if artigo.get("titulo"):
            titulo = artigo["titulo"]
            origem_tit = ("fonte acadêmica internacional" if fonte_academica
                          else "GROBID local" if grobid.get("consultado")
                          else "cabeçalho de artigo")
        if artigo.get("autor"):
            autor = artigo["autor"]
            origem_aut = ("fonte acadêmica internacional" if fonte_academica
                          else "GROBID local" if grobid.get("consultado")
                          else "autoria do artigo")
        elif artigo.get("fonte_web"):
            # Se a página não declara autoria, o dado correto é vazio. OCR da
            # capa, navegação, título e frases do corpo não podem inventá-la.
            autor = ""
            origem_aut = "não declarada na página do artigo"
        linha["conflitos"] = [
            c for c in linha["conflitos"]
            if not any(rotulo in c for rotulo in (
                "autor so do nome do arquivo", "titulo so do nome do arquivo",
                "titulo veio da API", "autor: copyright="))
        ]
    elif tipo_documento == "apresentação":
        # Slides exportados para PDF costumam guardar em /Author o usuário
        # do computador e o leitor de folha de rosto pode capturar uma frase
        # do primeiro slide. Sem rótulo explícito (Autor, Apresentador,
        # Professor etc.), o dado correto é autoria não declarada. O Biblio
        # aceita documento somente com título.
        if tit_pag and titulo_bibliograficamente_plausivel(tit_pag):
            titulo = tit_pag
            origem_tit = "título da apresentação"
        autor = (autor_rotulado_plausivel
                 if autor_rotulado_plausivel else "")
        origem_aut = ("autoria explícita da apresentação"
                      if autor else "não declarada")
        linha["conflitos"] = [
            c for c in linha["conflitos"]
            if not any(rotulo in c for rotulo in (
                "autor so do nome do arquivo", "titulo so do nome do arquivo",
                "titulo veio da API", "autor: copyright="))
        ]
    elif documental and tipo_documento not in {"livro", "coletânea"}:
        if documental.get("titulo"):
            titulo = documental["titulo"]
            origem_tit = "cabeçalho documental explícito"
        autor = documental.get("autor", "")
        origem_aut = "autoria documental explícita" if autor else "não declarada"
        linha["conflitos"] = [
            c for c in linha["conflitos"]
            if not any(rotulo in c for rotulo in (
                "autor so do nome do arquivo", "titulo so do nome do arquivo",
                "titulo veio da API", "autor: copyright="))
        ]
    elif origem_word and tipo_documento in {"livro", "coletânea"}:
        livro_word = metadados_livro_word_folha_rosto(paginas, autor)
        if livro_word.get("titulo") and not cip_identifica_edicao:
            titulo = livro_word["titulo"]
            origem_tit = "folha de rosto estruturada do Word"

    if tipo_documento not in {"livro", "coletânea"}:
        titulo, nome_substituiu_ruido = titulo_documental_sem_ruido(
            titulo, tit_nome)
        if nome_substituiu_ruido:
            origem_tit = "nome do arquivo substituiu sumário ou prosa"

    # --- paginas
    #
    # Traducao ao espanhol ou portugues fica MAIS longa que o original em
    # ingles - a Dogmatica tem 826 paginas contra 688 da edicao inglesa.
    # Marcar isso como conflito enche a planilha de alarme falso.
    #
    # O que merece atencao e o contrario: PDF bem MENOR que a edicao
    # sugere arquivo incompleto, so um trecho, ou capitulo avulso.
    pg_api = api.get("paginas") or ""
    paginacao = avaliar_paginacao_edicao(
        linha["paginas_pdf"], pg_api, origem_refluida=origem_word,
        pagina_dupla=pagina_pdf_horizontal(caminho))
    if paginacao["conflito"]:
        linha["conflitos"].append(paginacao["conflito"])
    parcialidade = diagnosticar_parcialidade_pdf(paginas)
    linha["arquivo_possivelmente_parcial"] = parcialidade["parcial"]
    linha["motivo_parcialidade"] = parcialidade["motivo"]
    linha["paginas_impressas_detectadas"] = parcialidade["paginas_impressas"]
    # Para livros, uma lacuna real exige conferência. Documentos podem ser
    # preservados assim mesmo: a limitação fica registrada na ficha e na
    # descrição, sem bloquear o cadastro específico.
    if (parcialidade["parcial"]
            and tipo_documento in {"livro", "coletânea"}
            and not rev.get("aprovado")):
        linha["conflitos"].append(
            f"PDF aparentemente parcial: {parcialidade['motivo']}")

    # ALERTA QUE FALTAVA: titulo num idioma e livro em outro.
    # "Un Appel Dangereux" ficou com "CONFRONTING THE UNIQUE CHALLENGES OF"
    # - a capa do PDF frances e a do original ingles - e passou como pronto,
    # sem marca nenhuma. Erro silencioso e pior que conflito.
    if titulo and idi and idi != "eng":
        ingles = {"the", "and", "of", "for", "with", "your", "you", "how",
                  "life", "god", "church", "gospel", "christian", "calling",
                  "money", "leadership", "unique", "challenges", "confronting"}
        ingles |= {"reformed", "ethics", "volume", "created", "fallen",
                   "converted", "humanity"}
        palavras = [p for p in identificar.normalizar(titulo).split() if len(p) > 2]
        if palavras and sum(p in ingles for p in palavras) / len(palavras) >= 0.5:
            linha["conflitos"].append(
                f"titulo parece ingles mas o livro esta em '{idi}' - "
                f"pode ser o titulo do original")

    editora_capa = editora_confirmada_na_capa(
        capa_info.get("texto_ocr", []),
        [cp.get("editora", ""), cip.get("editora", ""),
         api.get("editora", ""), comercial.get("editora", "")])
    editora_institucional = editora_institucional_nas_paginas(paginas)
    editoras = {
        "copyright": limpar_editora_bibliografica(cp.get("editora", "")),
        "cip": limpar_editora_bibliografica(cip.get("editora", "")),
        "capa": limpar_editora_bibliografica(editora_capa),
        "artigo": limpar_editora_bibliografica(artigo.get("editora", "")),
        "academico": limpar_editora_bibliografica(
            academico.get("editora", "")
            or fonte_academica.get("instituicao", "")),
        "api": limpar_editora_bibliografica(api.get("editora", "")),
        "institucional": limpar_editora_bibliografica(editora_institucional),
        "folha_word": limpar_editora_bibliografica(livro_word.get("editora", "")),
        "folha_rosto": limpar_editora_bibliografica(
            folha_editorial.get("editora", "")),
    }
    if copyright_original and any(editoras.get(k) for k in (
            "cip", "capa", "artigo", "academico", "api",
            "institucional", "folha_word", "folha_rosto")):
        editoras["copyright"] = ""
    editoras = {k: v for k, v in editoras.items()
                if editora_bibliograficamente_plausivel(v)}
    # Em impressão de página web, o domínio identifica a instituição
    # responsável. Menções a editoras, autores e sites dentro do corpo do
    # artigo não podem substituir essa procedência explícita.
    editora_final = escolher_editora_final(
        tipo_documento, editoras, api_por_isbn_exato=api_por_isbn_exato)
    lugar_final = (cip.get("cidade")
                   or folha_editorial.get("cidade", "")
                   or ("" if copyright_original else cp["cidade"]))
    lugar_sugerido = {}
    if not lugar_final:
        lugar_sugerido = cidade_sugerida_por_editora(editora_final)
        lugar_final = lugar_sugerido.get("cidade", "")
    editora_final, lugar_corrigido, motivo_lugar_corrigido = (
        corrigir_editora_lugar(editora_final, lugar_final))
    if motivo_lugar_corrigido:
        lugar_final = lugar_corrigido
        lugar_sugerido = {
            "fonte": "validação automática",
            "confianca": "alta",
            "motivo": motivo_lugar_corrigido,
        }
    titulo_pre_limpeza = titulo
    titulo = limpar_titulo_bibliografico(titulo, autor)
    if (tit_nome and titulo_bibliograficamente_plausivel(tit_nome)
            and not api_por_isbn_exato and not cip_identifica_edicao):
        autor_nome_tokens = {
            p for p in identificar.normalizar(
                aut_nome.replace(",", " ")).split() if len(p) > 2}
        titulo_tokens = {
            p for p in identificar.normalizar(titulo or "").split()
            if len(p) > 2}
        titulo_nome_tokens = {
            p for p in identificar.normalizar(tit_nome or "").split()
            if len(p) > 2}
        titulo_traz_autor_nome = bool(
            autor_nome_tokens and len(autor_nome_tokens & titulo_tokens)
            >= min(2, len(autor_nome_tokens)))
        titulo_tem_hash = bool(re.search(r"\b[0-9a-f]{8}\b", titulo or "",
                                         re.I))
        titulo_fragmento_do_nome = bool(
            titulo_tokens and titulo_nome_tokens
            and titulo_tokens < titulo_nome_tokens)
        titulo_nome_corrigido, nome_orientou = (
            titulo_orientado_pelo_nome_arquivo(titulo, tit_nome))
        if (nome_orientou or titulo_traz_autor_nome or titulo_tem_hash
                or titulo_fragmento_do_nome):
            if (titulo and titulo_bibliograficamente_plausivel(titulo)
                    and similaridade_titulos(titulo, tit_nome) < 0.45
                    and not linha.get("subTitulo")):
                linha["subTitulo"] = titulo
            titulo = titulo_nome_corrigido if nome_orientou else tit_nome
            origem_tit = "nome do arquivo corrigiu leitura visual"

    if (aut_nome and autor_bibliograficamente_plausivel(aut_nome)
            and not api_por_isbn_exato and not cip_identifica_edicao):
        autor_norm = identificar.normalizar(autor.replace(",", " "))
        titulo_norm = identificar.normalizar((titulo or tit_nome).replace(",", " "))
        partes_autor = {p for p in autor_norm.split() if len(p) > 2}
        partes_titulo = {p for p in titulo_norm.split() if len(p) > 2}
        autor_parece_titulo = bool(
            partes_autor and partes_titulo
            and (partes_autor <= partes_titulo
                 or similaridade_titulos(autor, titulo or tit_nome) >= 0.55))
        autor_parece_lugar = bool(re.search(
            r"(?i)\b(?:pitts?burg|pa\.?|u\.?s\.?a\.?|usa|grand\s+rapids)\b",
            autor or ""))
        if (autor_parece_titulo or autor_parece_lugar
                or not autor_bibliograficamente_plausivel(autor)):
            autor = aut_nome
            origem_aut = "nome do arquivo corrigiu autor-título"
    _titulo_sem_edicao, edicao_embutida_titulo = (
        separar_edicao_embutida_titulo(titulo_pre_limpeza))
    titulo = limpar_titulo_com_editora_e_serie(titulo, editora_final)
    ano_sem_copyright_original = "" if copyright_original else ano
    autores_estruturados = []
    if api_por_isbn_exato or api_por_titulo_autor:
        autores_estruturados = autores_com_papeis(
            api.get("autores", ""), t_bibliografico)
        responsavel_editorial = next(
            (x for x in autores_estruturados
             if x.get("desc") in {"Editor", "Organizador", "Coordenador"}),
            None)
        if responsavel_editorial:
            autor = responsavel_editorial["nome"]
            origem_aut = "função editorial declarada no PDF"
    elif artigo.get("autores_academicos"):
        autores_estruturados = [
            {"nome": sobrenome_virgula(nome_autor), "desc": "Autor"}
            for nome_autor in artigo["autores_academicos"]
            if autor_bibliograficamente_plausivel(nome_autor)
        ]
    elif len(autores_capa) > 1:
        for nome_autor in autores_capa:
            if autor_bibliograficamente_plausivel(nome_autor):
                autores_estruturados.append({
                    "nome": sobrenome_virgula(nome_autor), "desc": "Autor"})
    elif autores_creditos:
        autores_estruturados = [
            {"nome": nome_autor, "desc": "Autor"}
            for nome_autor in autores_creditos
        ]

    documento_nao_livro = tipo_documento not in {"livro", "coletânea"}
    linha.update({
        "titulo": titulo, "origem_titulo": origem_tit,
        "subTitulo": linha.get("subTitulo", ""),
        "nmAutor0": autor, "origem_autor": origem_aut,
        "autores": autores_estruturados,
        "tipoAssunto1": ASSUNTO_PADRAO,
        # CBL por ISBN exato identifica a editora desta edição; copyright
        # pode citar a editora do original. Fragmentos de frase são filtrados.
        "editora": editora_final,
        "data": str((academico.get("ano", "")
                     if tipo_documento in TIPOS_ACADEMICOS else "")
                    or (documental.get("ano", "") if documento_nao_livro else "")
                    or (api.get("ano", "") if
                        (api_por_isbn_exato or api_por_titulo_autor) else "")
                    or (cip.get("ano") if cip_identifica_edicao else "")
                    or folha_editorial.get("ano", "")
                    or (cip.get("ano") if cip.get("formato_cip") in
                     ("brasileira", "brasileira antiga",
                      "ficha antiga sem cabeçalho") else "")
                    or artigo.get("ano", "") or ano_sem_copyright_original
                    or cip.get("ano")
                    or api.get("ano", "")
                    or ("[s.d.]" if livro_word.get("titulo")
                        and livro_word.get("editora") else "")),
        # paginas bibliograficas nao sao necessariamente paginas digitais:
        # um PDF do lote traz duas paginas impressas por folha (60 x 120).
        "nPaginas": str((pg_api if
                         (api_por_isbn_exato or api_por_titulo_autor) else "")
                        or cip.get("paginas") or pg_api or linha["paginas_pdf"]),
        "paginas_bibliograficas": str(cip.get("paginas", "")),
        "paginas_arquivo": linha["paginas_pdf"],
        "paginas_edicao": paginacao["paginas_edicao"],
        "paginacao_refluida": paginacao["paginacao_refluida"],
        "paginacao_dupla": paginacao["paginacao_dupla"],
        "nmLingua": NOME_LINGUA.get(idi, ""), "idioma": idi,
        "edicao": ("" if documento_nao_livro else
                    edicao_catalografica(
                        cip.get("edicao") or edicao_embutida_titulo,
                        cp["edicao"])),
        "tradutor": (cip.get("tradutor") or cp["tradutor"]
                     or livro_word.get("tradutor", "")),
        "lugar": lugar_final,                  # Local de publicacao
        "origem_lugar": (lugar_sugerido.get("motivo")
                         or "cidade sugerida pela editora conhecida"
                         if lugar_sugerido else ""),
        "fonte_lugar": lugar_sugerido.get("fonte", ""),
        "confianca_lugar": lugar_sugerido.get("confianca", ""),
        "local": "",                           # Estante fisica - so voce sabe
        "cdd": cip.get("cdd", ""),             # vem do DDC do bloco CIP
        "classificacao_original": cip.get("classificacao_original", ""),
        "cdd_sugerido": cip.get("cdd_sugerido", ""),
        "fonte_cdd_sugerido": cip.get("fonte_cdd_sugerido", ""),
        "CDD": cip.get("cdd", "") or cip.get("classificacao_original", ""),
        "series": "", "numSerie": "", "volume": "",
        "acervo": ACERVO_PADRAO,
        # a pagina de creditos ("Titulo del original: ...") tem prioridade;
        # se ela nao declarar, fica o titulo que a API devolveu pelo ISBN
        "titulo_original": cp["titulo_original"] or linha.get("titulo_original", ""),
        "palavrasChave": (cip.get("assuntos") or api.get("assuntos", "")
                           or fonte_academica.get("assuntos", "")
                           or artigo.get("palavras_chave", "")
                           or academico.get("palavras_chave", "")),
        "fonte_api": api.get("fonte", "") or fonte_academica.get("fonte", ""),
        "abstract": (artigo.get("abstract", "")
                     or academico.get("abstract", "")
                     or grobid.get("abstract", "")),
        "tipo_documento": tipo_documento,
        "issn": artigo.get("issn", ""),
        "doi": fonte_academica.get("doi", "") or grobid.get("doi", ""),
        "fonte_academica": fonte_academica.get("fonte", ""),
        "fonte_grobid": ("GROBID local" if grobid.get("consultado") else ""),
        "tempo_grobid": grobid.get("segundos", ""),
        "url_fonte_academica": fonte_academica.get("url", ""),
        "url_fonte_artigo": artigo.get("url", ""),
        "consulta_oatd": consulta_oatd,
        "fonte_documental": "; ".join(documental.get("fontes", [])),
        "confianca_documental": documental.get("confianca", ""),
        "motivo_descarte_documental": documental.get("motivo_descarte", ""),
    })

    if derivacao_editorial:
        isbn_fonte = linha.get("isbn", "")
        if isbn_fonte:
            linha["isbn_referencia_da_fonte"] = isbn_fonte
        linha["isbn"] = ""
        linha["isbn_confirmado_na_edicao"] = False
        linha["isbn_motivo"] = (
            f"ISBN pertence à edição-fonte; não atribuído à "
            f"{derivacao_editorial['tipo']}")
        linha["tipo_documento"] = "documento"
        linha["edicao"] = derivacao_editorial["edicao"]
        linha.setdefault("procedencia", []).append(
            derivacao_editorial["tipo"])
        if derivacao_editorial.get("limpar_edicao_fonte"):
            linha["editora_referencia_da_fonte"] = linha.get("editora", "")
            linha["data_referencia_da_fonte"] = linha.get("data", "")
            linha["editora"] = ""
            linha["data"] = ""

    alertas_finais = alertas_plausibilidade_metadados(
        linha.get("titulo", ""), linha.get("nmAutor0", ""),
        linha.get("editora", ""))
    # A ocorrência do autor pode fazer parte do título oficial
    # (``As parábolas de Jesus comentadas por John MacArthur``). Se a edição
    # foi identificada pelo ISBN e a forma veio de CIP/API estruturada, esse
    # alerta genérico não pode anular a autoridade bibliográfica superior.
    titulo_autoritativo = bool(
        linha.get("isbn_confirmado_na_edicao")
        and linha.get("origem_titulo") in {
            "cip", "API por ISBN confirmado na edição", "CBL por ISBN exato"
        })
    if titulo_autoritativo:
        alertas_finais = [
            alerta for alerta in alertas_finais
            if alerta != "titulo parece conter ou repetir o nome do autor"
        ]
    linha["conflitos"].extend(alertas_finais)

    # Antes de a decisao humana vencer, preservamos a diferenca como possivel
    # aprendizado geral. A memoria e apenas propositiva: nunca altera outra
    # ficha automaticamente.
    aprendizados_revisao = []
    if rev:
        aprendizados_revisao = registrar_aprendizados_da_revisao(
            revisao_caminho or caminho,
            {campo: linha.get(campo, "")
             for campo in CAMPOS_APRENDIZADO_REVISAO},
            rev)

    # Uma revisao humana documentada vence as heuristicas, mas so para o PDF
    # cujo hash foi conferido. Isso resolve casos sem ficha de edicao (livro
    # antigo digitalizado, traducao local) sem ensinar uma regra perigosa ao
    # restante do acervo.
    if rev:
        for campo, valor in rev.get("campos", {}).items():
            linha[campo] = valor
        linha["nmLingua"] = normalizar_nome_lingua(linha.get("nmLingua", ""))
        linha["revisao_manual"] = rev.get("justificativa", "revisado")
        linha["fontes_revisao"] = " | ".join(rev.get("fontes", []))
        if rev.get("aprovado"):
            linha["conflitos"] = []
            linha["pendencias"] = []
        else:
            if "conflitos" in rev:
                linha["conflitos"] = list(rev.get("conflitos", []))
            if "pendencias" in rev:
                linha["pendencias"] = list(rev.get("pendencias", []))
    else:
        linha["revisao_manual"] = ""
        linha["fontes_revisao"] = ""

    # ------------------------------------------------------------------
    # Ausencia precisa de CAUSA registrada.
    #
    # A ficha do "Eu, um Discipulador" dizia apenas "pendencia: editora",
    # com a editora impressa na pagina 3. Nao havia como distinguir "o
    # livro nao declara" de "ninguem conseguiu ler" - e as duas situacoes
    # pedem acoes opostas: a primeira se aceita, a segunda se conserta.
    #
    # Aqui gravamos, para cada campo vazio, QUAIS fontes foram consultadas
    # e o que cada uma devolveu.
    # ------------------------------------------------------------------
    def _diagnostico_campo(campo):
        consultadas = {
            "titulo": [("ficha catalográfica", cip.get("titulo")),
                       ("página de créditos", cp.get("titulo_edicao")),
                       ("folha de rosto", tit_pag),
                       ("base por ISBN", api.get("titulo") if api else ""),
                       ("capa", (cap or {}).get("titulo") if "cap" in dir() else "")],
            "nmAutor0": [("ficha catalográfica", cip.get("autor")),
                         ("página de créditos", autor_do_copyright(t)[0]),
                         ("base por ISBN", api.get("autores") if api else ""),
                         ("documento", doc.get("autor") if doc else "")],
            "editora": [("ficha catalográfica", cip.get("editora")),
                        ("página de créditos", cp.get("editora")),
                        ("base por ISBN", api.get("editora") if api else "")],
            "data de publicacao": [("ficha catalográfica", cip.get("ano")),
                                   ("texto do livro", ano),
                                   ("base por ISBN", api.get("ano") if api else "")],
        }.get(campo, [])
        if not consultadas:
            return campo
        partes = [f"{nome} {'sem resultado' if not valor else 'ok'}"
                  for nome, valor in consultadas]
        motivo = f"{campo}: " + ", ".join(partes)
        if campo in ("titulo", "nmAutor0", "editora") and linha.get("tem_ocr") == "NAO":
            motivo += "; o PDF nao tem camada de texto"
        elif (campo in ("titulo", "nmAutor0", "editora")
              and linha.get("qualidade_ocr", 1) < LIMIAR_OCR):
            motivo += "; a leitura de texto ficou fraca - vale reconferir na imagem"
        return motivo

    # Autor que na verdade e um pedaco do titulo. Estava passando como se
    # fosse dado bom - a pendencia acusava "editora" e ninguem olhava o
    # autor. Erro silencioso e o que mais custa neste acervo.
    # Procedencia: registra o que o arquivo E, antes de cobrar dados dele.
    #
    # E INFORMACAO, nao defeito. So vira conflito quando ninguem revisou
    # ainda: uma vez que o revisor viu e aprovou, a marca continua na
    # ficha mas para de travar o item - senao "captura de site" e
    # "traducao automatica" prenderiam o livro para sempre.
    for tipo_proc, explicacao in procedencia_do_arquivo(t):
        linha.setdefault("procedencia", [])
        if tipo_proc not in linha["procedencia"]:
            linha["procedencia"].append(tipo_proc)
        if not rev.get("aprovado"):
            linha["conflitos"].append(f"{tipo_proc}: {explicacao}")

    suspeito, motivo_suspeita = identificar.autor_e_fragmento_do_titulo(
        linha.get("nmAutor0", ""), linha.get("titulo", ""),
        linha.get("origem_autor", ""))
    if suspeito:
        linha["conflitos"].append(f"autor suspeito: {motivo_suspeita}")

    # Última camada automática: aceita ausências reais de livros antigos
    # somente quando identidade, autoria e publicação convergem. Ela não
    # apaga conflitos; apenas aplica as convenções catalográficas adequadas.
    convergencia = avaliar_convergencia_bibliografica(linha)
    linha["convergencia_bibliografica"] = convergencia["motivo"]
    linha["evidencias_convergencia"] = " | ".join(
        convergencia["evidencias"])
    linha["campos_convencionados"] = "; ".join(
        f"{campo}={valor}" for campo, valor
        in convergencia["campos_convencionados"].items())
    if convergencia["aprovada"] and not rev.get("aprovado"):
        for campo, valor in convergencia["campos_convencionados"].items():
            linha[campo] = valor

    campos_essenciais = ["titulo", "nmLingua"]
    if linha.get("tipo_documento", "livro") in ("livro", "coletânea"):
        campos_essenciais.append("nmAutor0")
    for c in campos_essenciais:
        if not linha[c]:
            linha["pendencias"].append(_diagnostico_campo(c))

    if (documento_nao_livro
            and not rev.get("aprovado")
            and documental.get("confianca") == "baixa"
            and tipo_documento != "arquivo inválido"):
        linha["pendencias"].append("confirmar procedência documental")

    # Editora e data são obrigatórias para o tombo de livro. Materiais
    # institucionais, sermões, apostilas e artigos muitas vezes não possuem
    # esses elementos; exigir campos inexistentes criava revisão artificial.
    # A revisao manual aprovada DECIDE sobre a ausencia.
    #
    # Quando o revisor conferiu o livro e registrou o campo vazio com
    # justificativa, insistir na pendencia e ignorar o trabalho ja feito.
    # "Verdadeiros Adoradores" e edicao do proprio autor: o (c) e dele e
    # nao ha editora nem ISBN. A ausencia foi verificada, nao e falha.
    #
    # So vale para revisao APROVADA e para o campo que ela declara: um
    # campo que a revisao nao menciona continua sendo cobrado.
    def _revisor_decidiu(campo):
        return (rev.get("aprovado")
                and campo in (rev.get("campos", {}) or {}))

    if linha.get("tipo_documento", "livro") in ("livro", "coletânea"):
        if not linha.get("editora") and not _revisor_decidiu("editora"):
            linha["pendencias"].append(_diagnostico_campo("editora"))
        if not linha.get("data") and not _revisor_decidiu("data"):
            linha["pendencias"].append(_diagnostico_campo("data de publicacao"))

    if linha.get("tipo_documento") == "arquivo inválido":
        linha["situacao_metadados"] = "descartado - não é livro"
    elif linha.get("excecao_tamanho"):
        linha["situacao_metadados"] = "aguardando exceção de tamanho"
    elif linha.get("tipo_documento", "livro") in TIPOS_CADASTRO_ESPECIFICO:
        linha["situacao_metadados"] = "aguardando cadastro específico"
    elif linha["conflitos"]:
        linha["situacao_metadados"] = "conflito"
    elif linha["pendencias"]:
        linha["situacao_metadados"] = "analisado"
    else:
        linha["situacao_metadados"] = "pronto para cadastro"

    linha["situacao"] = ("precisa OCR" if diagnostico["status"] != "OCR aprovado"
                         else linha["situacao_metadados"])

    linha["assinatura_programa"] = assinatura_do_programa()
    if isinstance(linha.get("procedencia"), list):
        linha["procedencia"] = "; ".join(linha["procedencia"])
    linha["conflitos"] = " | ".join(linha["conflitos"])
    linha["pendencias"] = " | ".join(linha["pendencias"])
    fontes_rejeitadas = rejeicoes_fontes_bibliograficas(
        fontes_comerciais=fontes_comerciais,
        bnf_candidatos=bnf_candidatos, bnf_escolhido=bnf,
        motivo_bnf=motivo_bnf,
        ia_candidatos=ia_candidatos, ia_escolhido=ia,
        motivo_ia=motivo_ia,
        consultas_academicas=[
            ("Crossref", consultou_crossref, crossref),
            ("OpenAlex", consultou_openalex, openalex),
            ("CORE", consultou_core, core_academico),
        ])
    linha["_diagnostico_ocr"] = diagnostico
    linha["_evidencias"] = {
        "cip": cip,
        "copyright": cp,
        "isbn_candidatos": isbn_cands,
        "codigo_barras": barras,
        "titulo_nome_arquivo": tit_nome,
        "autor_nome_arquivo": aut_nome,
        "api": api,
        "api_geral": api_geral,
        "consulta_titulo_autor": consulta_titulo_autor,
        "cbl": cbl,
        "bnf": {"escolhido": bnf, "candidatos": bnf_candidatos},
        "internet_archive": {"escolhido": ia, "candidatos": ia_candidatos},
        "library_of_congress": loc,
        "hathitrust": hathitrust,
        "crossref": crossref,
        "openalex": openalex,
        "core_academico": core_academico,
        "grobid": grobid,
        "fonte_academica": fonte_academica,
        "academico": academico,
        "consulta_oatd": consulta_oatd,
        "fontes_comerciais": {
            "estante": fontes_comerciais.get("estante", {}),
            "amazon": fontes_comerciais.get("amazon", {}),
            "conciliado": comercial,
        },
        "fontes_rejeitadas": fontes_rejeitadas,
        "capa": capa_info,
        "editora_confirmada_na_capa": editora_capa,
        "metadados_pdf": doc,
        "folha_rosto_editorial": folha_editorial,
        "titulo_paginas": {"titulo": tit_pag, "pagina": pag_tit,
                            "motivo": motivo_tit_pag},
        "revisao_manual": rev,
        "aprendizados_revisao": aprendizados_revisao,
        "artigo": artigo,
    }
    return linha


COLUNAS = ["arquivo", "situacao", "situacao_ocr", "situacao_metadados",
           "titulo", "subTitulo", "nmAutor0", "tipoAssunto1", "tipo_documento",
           "isbn", "isbn_codigo_barras", "editora", "data", "nPaginas", "nmLingua", "idioma", "edicao",
           "tradutor", "lugar", "local", "cdd", "series", "numSerie", "volume",
           "acervo", "titulo_original", "palavrasChave", "abstract",
           "origem_titulo", "origem_autor", "fonte_api", "isbn_motivo",
           "doi", "fonte_academica", "fonte_grobid", "tempo_grobid",
           "grobid_status", "url_fonte_academica",
           "url_fonte_artigo", "consulta_oatd",
           "conflitos", "pendencias", "tem_ocr", "status_ocr", "cobertura_ocr",
           "motor_texto", "qualidade_ocr", "paginas_texto_fraco",
           "paginas_sem_texto", "paginas_pdf", "paginas_arquivo",
           "paginas_edicao", "paginacao_refluida", "paginas_bibliograficas",
           "isbn_sugerido_por_titulo_autor",
           "convergencia_bibliografica", "evidencias_convergencia",
           "campos_convencionados",
           "revisao_manual", "fontes_revisao",
           "pdf_original", "pdf_preparado", "capa"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="")
    ap.add_argument("--sem-api", action="store_true")
    ap.add_argument("--sem-ocr", action="store_true",
                    help="compatibilidade: o diagnostico nunca altera o original")
    ap.add_argument("--preparar-ocr", action="store_true",
                    help="cria copia com OCR em _preparados; preserva o original")
    ap.add_argument("--refazer-ocr", action="store_true",
                    help="igual a --preparar-ocr, refazendo texto ruim na copia")
    args = ap.parse_args()

    pasta = args.dir or input("  Caminho da pasta com os livros: ").strip()
    pasta = os.path.expanduser(pasta.strip().strip("'\""))
    if not os.path.isdir(pasta):
        sys.exit(f"Pasta nao encontrada: {pasta}")

    pdfs = sorted(f for f in os.listdir(pasta) if f.lower().endswith(".pdf"))
    if not pdfs:
        sys.exit("Nenhum PDF nesta pasta.")

    print(f"\n{N}{AZ}  PREPARAR LIVROS{F}")
    print(f"{AZ}  {'-'*52}{F}")
    print(f"  Pasta: {pasta}")
    print(f"  PDFs:  {len(pdfs)}")
    if args.sem_api or not requests:
        warn("sem consulta as bases publicas")
    print()

    pasta_capas = os.path.join(pasta, "_capas")
    pasta_preparados = os.path.join(pasta, "_preparados")
    pasta_metadados = os.path.join(pasta, "_metadados")
    os.makedirs(pasta_metadados, exist_ok=True)
    linhas = []
    for i, nome in enumerate(pdfs, 1):
        caminho = os.path.join(pasta, nome)
        print(f"{N}[{i}/{len(pdfs)}]{F} {nome[:56]}")

        paginas = paginas_pdftotext(caminho)
        diag_inicial = diagnosticar_ocr(caminho, paginas)
        fonte = caminho
        preparado = ""
        quer_preparar = args.preparar_ocr or args.refazer_ocr
        if diag_inicial["status"] != "OCR aprovado":
            warn("diagnostico: " + "; ".join(diag_inicial["motivos"]))
            if quer_preparar:
                preparado = os.path.join(pasta_preparados, nome)
                idioma = idioma_do_texto("\n".join(paginas[:30]))
                refazer = args.refazer_ocr or bool(diag_inicial["paginas_pesquisaveis"])
                warn(f"criando copia com OCR ({IDIOMA_OCR.get(idi, 'por')})")
                if rodar_ocr(caminho, preparado,
                             idioma=IDIOMA_OCR.get(idi, "por"), refazer=refazer):
                    fonte = preparado
                    paginas = paginas_pdftotext(fonte)
                    diag_depois = diagnosticar_ocr(fonte, paginas)
                    if diag_depois["status"] == "OCR aprovado":
                        ok("copia preparada e OCR aprovado")
                    else:
                        err("a copia ainda nao passou no diagnostico de OCR")
                else:
                    err("OCR falhou; original preservado")
                    preparado = ""
            else:
                info("use --preparar-ocr para gerar uma copia; o original nao sera alterado")
        else:
            ok("OCR aprovado")

        # a capa vem ANTES: o processar recorre a ela quando as fontes de
        # texto nao dao titulo ou autor
        capa = gerar_capa(fonte, pasta_capas)
        linha = processar(fonte, usar_api=not args.sem_api, capa=capa,
                          paginas=paginas)
        linha["arquivo"] = nome
        linha["pdf_original"] = caminho
        linha["pdf_preparado"] = preparado
        linha["capa"] = capa

        cor = {"pronto para cadastro": V, "analisado": A,
               "conflito": A}.get(linha["situacao"], R)
        print(f"      {cor}{linha['situacao']}{F}  {linha['titulo'][:44]}"
              f"  |  {linha['nmAutor0'][:26] or '(sem autor)'}")
        if linha["conflitos"]:
            info(f"conflito: {linha['conflitos'][:90]}")
        linhas.append(linha)

        # Uma ficha por livro preserva evidencias e o diagnostico detalhado.
        # A planilha continua sendo apenas a visao consolidada.
        ficha = {k: v for k, v in linha.items() if not k.startswith("_")}
        ficha["diagnostico_ocr"] = linha["_diagnostico_ocr"]
        ficha["evidencias"] = linha["_evidencias"]
        ficha["gerado_em"] = datetime.now().isoformat(timespec="seconds")
        ficha_path = os.path.join(
            pasta_metadados, os.path.splitext(nome)[0] + ".json")
        ficha_tmp = ficha_path + ".tmp"
        with open(ficha_tmp, "w", encoding="utf-8") as fh:
            json.dump(ficha, fh, ensure_ascii=False, indent=2)
        os.replace(ficha_tmp, ficha_path)

    saida = os.path.join(pasta, "_livros-metadados.csv")
    saida_tmp = saida + ".tmp"
    with open(saida_tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUNAS, delimiter=";", extrasaction="ignore")
        w.writeheader()
        w.writerows(linhas)
    os.replace(saida_tmp, saida)

    cont = {}
    for l in linhas:
        cont[l["situacao"]] = cont.get(l["situacao"], 0) + 1

    print(f"\n{AZ}  {'-'*52}{F}")
    print(f"{N}  RESUMO{F}\n")
    for k, v in sorted(cont.items(), key=lambda x: -x[1]):
        print(f"    {k:.<28} {v}")
    print(f"\n    Planilha: {saida}")
    print(f"    Capas:    {pasta_capas}\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Interrompido.\n")
