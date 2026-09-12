#!/usr/bin/env python3
"""Extracao local e conservadora de cabecalhos academicos com GROBID.

O modulo nao inicia Docker, nao altera PDFs e nao consulta a internet. Ele
somente usa um servico GROBID ja disponivel em 127.0.0.1. Quando o servico
nao esta acessivel, devolve um diagnostico e a esteira continua normalmente.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
import xml.etree.ElementTree as ET

try:
    import requests
except ImportError:  # pragma: no cover - instalacao incompleta
    requests = None


NS = {"tei": "http://www.tei-c.org/ns/1.0"}
ENDPOINT_PADRAO = "http://127.0.0.1:8070"
VERSAO_CACHE = 2
_ESTADO_SERVICO = {"endpoint": "", "instante": 0.0, "disponivel": False}


def normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", texto.lower()))


def texto_no(elemento):
    if elemento is None:
        return ""
    return " ".join(parte.strip() for parte in elemento.itertext()
                    if parte.strip())


def normalizar_doi(valor):
    encontrados = dois_no_texto(valor)
    return encontrados[0] if encontrados else ""


def dois_no_texto(valor):
    """Extrai todos os DOI, normalizando travessoes usados em intervalos."""
    texto = str(valor or "").replace("–", "-").replace("—", "-")
    return list(dict.fromkeys(
        achado.rstrip(".,;)").lower()
        for achado in re.findall(
            r"(?i)(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", texto)
        if achado.rstrip(".,;)")))


def _autor_ruidoso(valor):
    n = normalizar(valor)
    return (not n or len(n) < 3 or len(n) > 100
            or bool(re.search(
                r"\b(?:abstract|resumo|keywords?|palavras chave|correspondence|"
                r"affiliation|department|university|universidade|faculty|"
                r"faculdade|institute|instituto|orcid|received|accepted|"
                r"editor(?:ial)?|volume|issue|doi|ph d|psichology|psychology)\b",
                n)))


def limpar_autores(autores):
    """Remove falsos autores evidentes sem tentar adivinhar nomes partidos."""
    limpos = []
    vistos = set()
    for autor in autores or []:
        valor = "".join(c for c in str(autor or "")
                        if unicodedata.category(c) != "Co")
        valor = " ".join(valor.split()).strip(" ,;:-")
        chave = normalizar(valor)
        if _autor_ruidoso(valor) or chave in vistos:
            continue
        vistos.add(chave)
        limpos.append(valor)
    return limpos


def reparar_autor_truncado(autor, texto):
    """Repara sobrenome de ate 2 letras somente quando o PDF o repete inteiro."""
    valor = " ".join(str(autor or "").split()).strip(" ,;:-")
    if not valor:
        return valor, ""
    if "," in valor:
        sobrenome, restante = [x.strip() for x in valor.split(",", 1)]
        ordem_invertida = True
    else:
        partes = valor.split()
        sobrenome, restante = partes[-1], " ".join(partes[:-1])
        ordem_invertida = False
    if not sobrenome.isalpha() or len(sobrenome) > 2:
        return valor, ""
    candidatos = re.findall(
        r"(?<![A-Za-zÀ-ÿ])" + re.escape(sobrenome)
        + r"[A-Za-zÀ-ÿ]{2,}(?![A-Za-zÀ-ÿ])", str(texto or ""), re.I)
    contagens = {}
    formas = {}
    for candidato in candidatos:
        chave = normalizar(candidato)
        contagens[chave] = contagens.get(chave, 0) + 1
        formas.setdefault(chave, candidato)
    fortes = sorted(
        ((qtd, formas[chave]) for chave, qtd in contagens.items() if qtd >= 2),
        reverse=True)
    if not fortes or (len(fortes) > 1 and fortes[0][0] == fortes[1][0]):
        return valor, ""
    completo = fortes[0][1]
    corrigido = (f"{completo}, {restante}" if ordem_invertida else
                 " ".join(x for x in (restante, completo) if x))
    return corrigido, (
        f"sobrenome '{sobrenome}' truncado pelo texto do PDF; "
        f"'{completo}' aparece {fortes[0][0]} vezes")


def extrair_tei(conteudo):
    raiz = ET.fromstring(conteudo)
    titulo = raiz.find(
        ".//tei:sourceDesc//tei:analytic/tei:title[@level='a']", NS)
    if titulo is None:
        titulo = raiz.find(".//tei:titleStmt/tei:title", NS)
    autores = []
    for autor in raiz.findall(
            ".//tei:sourceDesc//tei:analytic/tei:author", NS):
        nome = autor.find(".//tei:persName", NS)
        autores.append(texto_no(nome if nome is not None else autor))
    doi = ""
    for identificador in raiz.findall(".//tei:idno", NS):
        if str(identificador.get("type", "")).lower() == "doi":
            doi = normalizar_doi(texto_no(identificador))
            break
    data = raiz.find(
        ".//tei:sourceDesc//tei:monogr//tei:imprint/tei:date", NS)
    ano = ""
    if data is not None:
        achado = re.search(r"(?:19|20)\d{2}",
                           data.get("when", "") or texto_no(data))
        ano = achado.group(0) if achado else ""
    periodico = raiz.find(
        ".//tei:sourceDesc//tei:monogr/tei:title[@level='j']", NS)
    resumo = raiz.find(".//tei:profileDesc/tei:abstract", NS)
    palavras = [texto_no(termo) for termo in raiz.findall(
        ".//tei:profileDesc//tei:keywords//tei:term", NS)]
    return {
        "titulo": texto_no(titulo),
        "autores": limpar_autores(autores),
        "doi": doi,
        "ano": ano,
        "periodico": texto_no(periodico),
        "abstract": texto_no(resumo),
        "palavras_chave": [p for p in palavras if p],
    }


def sinais_academicos(tipo_documento, texto, paginas_pdf=0):
    """Decide quando vale pagar a extracao, sem chamar todo PDF de artigo."""
    n = normalizar(texto)
    sinais = []
    tipo_n = normalizar(tipo_documento)
    if tipo_n in {"artigo", "tese", "dissertacao", "trabalho academico"}:
        sinais.append("tipo acadêmico já reconhecido")
    if normalizar_doi(texto):
        sinais.append("DOI no PDF")
    if re.search(r"\b(?:abstract|resumo)\b", n):
        sinais.append("resumo estruturado")
    if re.search(r"\b(?:keywords?|palavras chave)\b", n):
        sinais.append("palavras-chave")
    if re.search(r"\b(?:references|referencias bibliograficas|bibliografia)\b", n):
        sinais.append("referências")
    if re.search(r"\bissn\s*\d{4}\s*[- ]?\s*\d{3}[\dx]\b", n):
        sinais.append("ISSN")

    reconhecido = tipo_n in {
        "artigo", "tese", "dissertacao", "trabalho academico"}
    estrutura_academica = set(sinais) & {
        "resumo estruturado", "palavras-chave", "referências", "ISSN"}
    pacote_artigo = ("DOI no PDF" in sinais
                     and bool(estrutura_academica)
                     and (not paginas_pdf or paginas_pdf <= 100))
    documento_academico = (tipo_n in {"documento", "apostila"}
                           and len(set(sinais) & {
                               "DOI no PDF", "resumo estruturado",
                               "palavras-chave", "referências", "ISSN"}) >= 3)
    return {
        "consultar": bool(reconhecido or pacote_artigo or documento_academico),
        "reclassificar_artigo": bool(pacote_artigo),
        "sinais": sinais,
    }


def titulo_aceitavel(titulo, periodico=""):
    n = normalizar(titulo)
    if len(n) < 5 or len(n) > 350:
        return False
    if periodico and n == normalizar(periodico):
        return False
    if re.match(r"^(?:dossier|dossie|original article|research article|"
                r"artigo original|editorial)(?:\b|\s*[:\-])", n):
        return False
    if re.search(r"\b(?:all rights reserved|todos os direitos reservados|"
                 r"copyright|received|accepted)\b", n):
        return False
    if (len(n.split()) <= 7
            and re.search(r"\b(?:journal|revista|studies|review|quarterly)\b", n)
            and ":" not in str(titulo or "")):
        return False
    return len(n.split()) >= 2


def esta_disponivel(endpoint=None, atualizar=False):
    endpoint = (endpoint or os.environ.get("BIBLIO_GROBID_URL")
                or ENDPOINT_PADRAO).rstrip("/")
    agora = time.monotonic()
    if (not atualizar and _ESTADO_SERVICO["endpoint"] == endpoint
            and agora - _ESTADO_SERVICO["instante"] < 30):
        return _ESTADO_SERVICO["disponivel"]
    disponivel = False
    if requests:
        try:
            resposta = requests.get(endpoint + "/api/isalive", timeout=(0.4, 1.5))
            disponivel = resposta.ok and "true" in resposta.text.lower()
        except Exception:
            disponivel = False
    _ESTADO_SERVICO.update(
        endpoint=endpoint, instante=agora, disponivel=disponivel)
    return disponivel


def _arquivo_cache(pasta_cache, caminho):
    digest = hashlib.sha256(Path(caminho).read_bytes()).hexdigest()[:24]
    pasta = Path(pasta_cache)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta / f"grobid-{digest}.json"


def consultar(caminho, tipo_documento, texto, paginas_pdf, pasta_cache,
              endpoint=None, atualizar=False):
    """Extrai o cabecalho e devolve tambem a causa de uso ou de ausencia."""
    decisao = sinais_academicos(tipo_documento, texto, paginas_pdf)
    resultado = {"consultado": False, "disponivel": False,
                 "motivo": "sem sinais acadêmicos suficientes", **decisao}
    if not decisao["consultar"]:
        return resultado
    arquivo = _arquivo_cache(pasta_cache, caminho)
    if arquivo.exists() and not atualizar:
        try:
            cache = json.loads(arquivo.read_text(encoding="utf-8"))
            if cache.get("versao_cache") == VERSAO_CACHE:
                cache["cache"] = True
                return cache
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    endpoint = (endpoint or os.environ.get("BIBLIO_GROBID_URL")
                or ENDPOINT_PADRAO).rstrip("/")
    if not esta_disponivel(endpoint):
        resultado["motivo"] = "serviço GROBID local indisponível"
        return resultado
    inicio = time.monotonic()
    try:
        with open(caminho, "rb") as pdf:
            resposta = requests.post(
                endpoint + "/api/processHeaderDocument",
                files={"input": (Path(caminho).name, pdf, "application/pdf")},
                data={"consolidateHeader": "0", "includeRawAffiliations": "1"},
                timeout=(3, 180))
        resposta.raise_for_status()
        extraido = extrair_tei(resposta.text)
        resultado.update(extraido)
        resultado.update({
            "versao_cache": VERSAO_CACHE,
            "consultado": True,
            "disponivel": True,
            "motivo": "cabeçalho acadêmico extraído localmente",
            "titulo_aceitavel": titulo_aceitavel(
                extraido.get("titulo", ""), extraido.get("periodico", "")),
            "segundos": round(time.monotonic() - inicio, 3),
            "cache": False,
        })
        temporario = arquivo.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        temporario.replace(arquivo)
        return resultado
    except Exception as exc:
        resultado.update({
            "disponivel": True,
            "motivo": f"falha no GROBID: {type(exc).__name__}",
            "segundos": round(time.monotonic() - inicio, 3),
        })
        return resultado
