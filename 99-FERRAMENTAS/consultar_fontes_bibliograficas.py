#!/usr/bin/env python3
"""Fontes bibliograficas complementares consultadas livro por livro.

BnF e fonte catalografica institucional. Internet Archive e usado somente
como evidencia auxiliar porque alguns registros de colecoes repetem todos os
ISBNs em cada volume. Todas as consultas sao exatas por ISBN e persistidas em
cache local.
"""

import argparse
import getpass
import html
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    requests = None

try:  # módulos POSIX; no Windows as chaves vêm das variáveis de ambiente
    import pty
    import select
except ImportError:  # pragma: no cover - exercido somente no Windows
    pty = None
    select = None


BNF_URL = "https://catalogue.bnf.fr/api/SRU"
IA_URL = "https://archive.org/advancedsearch.php"
OPEN_LIBRARY_URL = "https://openlibrary.org/api/books"
GOOGLE_BOOKS_URL = "https://www.googleapis.com/books/v1/volumes"
# O endereço HTTPS documentado pela própria LoC devolve 404 em produção;
# o gateway SRU oficial na porta 210 é o endpoint funcional.
LOC_SRU_URL = "http://lx2.loc.gov:210/lcdb"
HATHITRUST_URL = "https://catalog.hathitrust.org/api/volumes/full/isbn/{isbn}.json"
ISBNSEARCH_URL = "https://www.isbnsearch.org/isbn/{isbn}"
CROSSREF_URL = "https://api.crossref.org/works"
OPENALEX_URL = "https://api.openalex.org/works"
CORE_URL = "https://api.core.ac.uk/v3/search/works"
OATD_BUSCA_URL = "https://oatd.org/oatd/search"
CHAVES_ACADEMICAS = {
    "openalex": ("Biblioteca PIB Curitiba - OpenAlex", "consulta-academica",
                  "OPENALEX_API_KEY"),
    "core": ("Biblioteca PIB Curitiba - CORE", "consulta-academica",
              "CORE_API_KEY"),
}
INTERVALO_MINIMO = 3.0
USER_AGENT = "Biblio-PIB-Curitiba/1.0 (consulta bibliografica unitaria)"
_ULTIMA = {}
_CHAVES_INVALIDAS = set()


def ler_chave_academica(fonte):
    """Lê chave do ambiente ou do Chaves do macOS sem expô-la no código."""
    servico, conta, variavel = CHAVES_ACADEMICAS.get(fonte, ("", "", ""))
    if variavel and os.environ.get(variavel):
        return os.environ[variavel].strip()
    if not servico:
        return ""
    try:
        resposta = subprocess.run(
            ["security", "find-generic-password", "-s", servico,
             "-a", conta, "-w"], capture_output=True, text=True,
            check=False)
    except OSError:
        return ""
    return resposta.stdout.strip() if resposta.returncode == 0 else ""


def guardar_chave_academica(fonte, chave=""):
    """Guarda uma credencial no Chaves sem colocá-la nos argumentos do processo."""
    if fonte not in CHAVES_ACADEMICAS:
        raise ValueError("fonte acadêmica desconhecida")
    if sys.platform != "darwin" or pty is None or select is None:
        raise RuntimeError(
            f"neste sistema use a variável {CHAVES_ACADEMICAS[fonte][2]}")
    servico, conta, _ = CHAVES_ACADEMICAS[fonte]
    chave = chave or getpass.getpass(
        f"Chave {fonte.upper()} (ficará protegida no Chaves do macOS): ")
    if not chave:
        raise ValueError("chave ausente")
    argumentos = ["security", "add-generic-password", "-U", "-s",
                  servico, "-a", conta, "-l", servico, "-w"]
    pid, terminal = pty.fork()
    if pid == 0:  # pragma: no cover - processo substituído pelo security
        os.execvp(argumentos[0], argumentos)
    buffer = b""
    respondidos = set()
    prazo = time.monotonic() + 30
    status = None
    try:
        while time.monotonic() < prazo:
            pronto, _, _ = select.select([terminal], [], [], 0.2)
            if pronto:
                try:
                    bloco = os.read(terminal, 1024)
                except OSError:
                    bloco = b""
                buffer = (buffer + bloco)[-2048:]
                texto = buffer.lower()
                for marcador in (b"password data", b"retype password"):
                    if marcador in texto and marcador not in respondidos:
                        os.write(terminal, chave.encode("utf-8") + b"\n")
                        respondidos.add(marcador)
            concluido, codigo = os.waitpid(pid, os.WNOHANG)
            if concluido:
                status = os.waitstatus_to_exitcode(codigo)
                break
    finally:
        try:
            os.close(terminal)
        except OSError:
            pass
    if status != 0:
        raise RuntimeError("não foi possível guardar a chave no Chaves do macOS")
    return True


def normalizar_isbn(valor):
    return re.sub(r"[^0-9Xx]", "", str(valor or "")).upper()


def _lista(valor):
    if valor is None:
        return []
    return valor if isinstance(valor, list) else [valor]


def _normalizar_texto(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", texto.lower()))


def _esperar(fonte):
    espera = INTERVALO_MINIMO - (time.monotonic() - _ULTIMA.get(fonte, 0.0))
    if espera > 0:
        time.sleep(espera)
    _ULTIMA[fonte] = time.monotonic()


def _arquivo_cache(pasta, fonte, isbn):
    return Path(pasta) / fonte / f"{normalizar_isbn(isbn)}.json"


def _arquivo_cache_texto(pasta, fonte, titulo, autor):
    chave = _normalizar_texto(titulo) + "|" + _normalizar_texto(autor)
    digest = hashlib.sha256(chave.encode("utf-8")).hexdigest()
    return Path(pasta) / fonte / f"{digest}.json"


def _ler_cache(arquivo, isbn):
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return dados.get("resultado") if dados.get("isbn") == isbn else None


def _salvar_cache(arquivo, isbn, fonte, resultado):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    pacote = {
        "isbn": isbn,
        "fonte": fonte,
        "consulta": "ISBN exato",
        "consultado_em": datetime.now().isoformat(timespec="seconds"),
        "resultado": resultado,
    }
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(json.dumps(pacote, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, arquivo)


def _ler_cache_texto(arquivo, titulo, autor):
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    consulta = dados.get("consulta_dados") or {}
    if (_normalizar_texto(consulta.get("titulo")) != _normalizar_texto(titulo)
            or _normalizar_texto(consulta.get("autor")) != _normalizar_texto(autor)):
        return None
    return dados.get("resultado")


def _salvar_cache_texto(arquivo, fonte, titulo, autor, resultado):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    pacote = {
        "fonte": fonte,
        "consulta": "título + autor",
        "consulta_dados": {"titulo": titulo, "autor": autor},
        "consultado_em": datetime.now().isoformat(timespec="seconds"),
        "resultado": resultado,
    }
    tmp = arquivo.with_name(arquivo.name + ".tmp")
    tmp.write_text(json.dumps(pacote, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    os.replace(tmp, arquivo)


def _texto_html(valor):
    texto = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", str(valor or ""))
    texto = re.sub(r"(?s)<[^>]+>", " ", texto)
    return " ".join(html.unescape(texto).split())


def _parse_isbnsearch(texto, isbn):
    """Extrai a ficha pública do ISBNsearch quando APIs catalográficas falham."""
    bloco = re.search(r'(?is)<div[^>]+class=["\']bookinfo["\'][^>]*>(.*?)</div>',
                      texto or "")
    area = bloco.group(1) if bloco else (texto or "")
    titulo = ""
    m_titulo = re.search(r"(?is)<h1[^>]*>(.*?)</h1>", area)
    if m_titulo:
        titulo = _texto_html(m_titulo.group(1))
        titulo = re.sub(r"\s*\((?:Hardcover|Paperback|Mass Market Paperback|"
                        r"eBook|Kindle Edition|Capa comum|Capa dura)\)\s*$",
                        "", titulo, flags=re.I).strip()
    campos = {}
    for m in re.finditer(
            r"(?is)<p>\s*<strong>\s*([^:<]+(?:-[0-9]+)?):\s*</strong>\s*(.*?)</p>",
            area):
        rotulo = _texto_html(m.group(1)).lower()
        valor = _texto_html(m.group(2))
        campos[rotulo] = valor
    if not titulo and not campos:
        return {}
    publicado = campos.get("published", "")
    ano = (re.search(r"\b((?:18|19|20)\d{2})\b", publicado)
           or [None, ""])[1]
    isbn_13 = normalizar_isbn(campos.get("isbn-13", ""))
    isbn_10 = normalizar_isbn(campos.get("isbn-10", ""))
    return {
        "titulo": titulo,
        "subtitulo": "",
        "autores": campos.get("author", ""),
        "editora": campos.get("publisher", ""),
        "ano": ano,
        "data": publicado,
        "paginas": "",
        "assuntos": "",
        "isbn": isbn_13 or isbn_10 or isbn,
        "isbn_10": isbn_10,
        "isbn_13": isbn_13,
        "encadernacao": campos.get("binding", ""),
        "identificador_fonte": ISBNSEARCH_URL.format(isbn=isbn),
        "fonte": "ISBNsearch",
    }


def consultar_isbnsearch(isbn, pasta_cache, sessao=None, atualizar=False):
    numero = normalizar_isbn(isbn)
    if not requests or len(numero) not in (10, 13):
        return {}
    arquivo = _arquivo_cache(pasta_cache, "isbnsearch", numero)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache(arquivo, numero)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    try:
        _esperar("isbnsearch")
        resposta = sessao.get(ISBNSEARCH_URL.format(isbn=numero), timeout=25)
        resposta.raise_for_status()
        resultado = _parse_isbnsearch(resposta.text, numero)
        _salvar_cache(arquivo, numero, "ISBNsearch", resultado)
        return resultado
    except Exception:
        return {}


def _texto(no, nome):
    achado = no.find(f"{{http://purl.org/dc/elements/1.1/}}{nome}")
    return (achado.text or "").strip() if achado is not None else ""


def _textos(no, nome):
    return [(x.text or "").strip() for x in no.findall(
        f"{{http://purl.org/dc/elements/1.1/}}{nome}") if (x.text or "").strip()]


def _limpar_autor_bnf(valor):
    valor = re.sub(r"\s*\(\d{4}(?:-\d{0,4})?\)\s*", " ", valor)
    valor = re.sub(r"(?i)\.\s*(?:auteur du texte|traducteur|editeur scientifique).*$",
                   "", valor)
    return " ".join(valor.split()).strip(" .")


def _parse_bnf(xml, isbn):
    raiz = ET.fromstring(xml)
    candidatos = []
    for no in raiz.findall(".//{http://www.openarchives.org/OAI/2.0/oai_dc/}dc"):
        identificadores = _textos(no, "identifier")
        isbns = {normalizar_isbn(x) for x in identificadores if "isbn" in x.lower()}
        if isbn not in isbns:
            continue
        formato = _texto(no, "format")
        mp = re.search(r"\b(\d{1,5})\s*p(?:\.|\b)", formato, re.I)
        titulo = _texto(no, "title")
        if " / " in titulo:
            titulo = titulo.split(" / ", 1)[0].strip()
        editora = _texto(no, "publisher")
        lugar = ""
        ml = re.search(r"\(([^()]{2,50})\)\s*$", editora)
        if ml:
            lugar = ml.group(1).strip()
            editora = editora[:ml.start()].strip()
        data = _texto(no, "date")
        candidatos.append({
            "titulo": titulo,
            "subtitulo": "",
            "autores": "; ".join(_limpar_autor_bnf(a)
                                    for a in _textos(no, "creator")),
            "editora": editora,
            "ano": (re.search(r"\b(\d{4})\b", data) or [None, ""])[1],
            "paginas": mp.group(1) if mp else "",
            "assuntos": "; ".join(_textos(no, "subject")[:5]),
            "idiomas_fonte": "; ".join(_textos(no, "language")),
            "lugar_fonte": lugar,
            "identificador_fonte": next(
                (x for x in identificadores if "ark:/" in x), ""),
            "fonte": "Bibliothèque nationale de France",
        })
    return candidatos


def consultar_bnf(isbn, pasta_cache, sessao=None, atualizar=False):
    numero = normalizar_isbn(isbn)
    if not requests or len(numero) not in (10, 13):
        return []
    arquivo = _arquivo_cache(pasta_cache, "bnf", numero)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache(arquivo, numero)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    try:
        _esperar("bnf")
        resposta = sessao.get(BNF_URL, params={
            "version": "1.2", "operation": "searchRetrieve",
            "query": f'bib.isbn all "{numero}"', "maximumRecords": 10,
            "recordSchema": "dublincore",
        }, timeout=30)
        resposta.raise_for_status()
        resultado = _parse_bnf(resposta.text, numero)
        _salvar_cache(arquivo, numero, "BnF", resultado)
        return resultado
    except Exception:
        return []


def _similaridade(a, b):
    aa, bb = set(_normalizar_texto(a).split()), set(_normalizar_texto(b).split())
    return len(aa & bb) / max(1, len(aa | bb))


def _similaridade_autor(a, b):
    """Compara nomes sem exigir a mesma ordem bibliográfica."""
    aa = {x for x in _normalizar_texto(a).split() if len(x) > 1}
    bb = {x for x in _normalizar_texto(b).split() if len(x) > 1}
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, min(len(aa), len(bb)))


def resolver_candidatos(candidatos, ano="", paginas="", titulo=""):
    """Escolhe apenas quando o contexto local separa claramente a edicao."""
    if not candidatos:
        return {}, "nao encontrado"
    if len(candidatos) == 1:
        return candidatos[0], "registro unico"
    pontuados = []
    for candidato in candidatos:
        pontos = 0
        if ano and str(candidato.get("ano")) == str(ano):
            pontos += 5
        if titulo and _similaridade(titulo, candidato.get("titulo")) >= 0.55:
            pontos += 4
        try:
            if paginas and candidato.get("paginas") and abs(
                    int(paginas) - int(candidato["paginas"])) <= 5:
                pontos += 3
        except (TypeError, ValueError):
            pass
        pontuados.append((pontos, candidato))
    pontuados.sort(key=lambda x: x[0], reverse=True)
    melhor, segundo = pontuados[0][0], pontuados[1][0]
    if melhor >= 4 and melhor >= segundo + 2:
        return pontuados[0][1], "edicao distinguida pelo PDF"
    return {}, f"{len(candidatos)} registros para o mesmo ISBN"


def _parse_ia(dados, isbn):
    docs = dados.get("response", {}).get("docs", [])
    candidatos = []
    for item in docs:
        isbns = {normalizar_isbn(x) for x in _lista(item.get("isbn"))}
        if isbn not in isbns:
            continue
        ano = str(item.get("year") or "")
        if not ano:
            ano = (re.search(r"\b(\d{4})\b", str(item.get("date") or ""))
                   or [None, ""])[1]
        candidatos.append({
            "titulo": item.get("title") or "", "subtitulo": "",
            "autores": "; ".join(str(x) for x in _lista(item.get("creator"))),
            "editora": item.get("publisher") or "", "ano": ano,
            "paginas": "",
            "assuntos": "; ".join(str(x) for x in _lista(item.get("subject"))[:5]),
            "idiomas_fonte": "; ".join(str(x) for x in _lista(item.get("language"))),
            "identificador_fonte": item.get("identifier") or "",
            "fonte": "Internet Archive (evidência)",
        })
    return candidatos


def consultar_internet_archive(isbn, pasta_cache, sessao=None, atualizar=False):
    numero = normalizar_isbn(isbn)
    if not requests or len(numero) not in (10, 13):
        return []
    arquivo = _arquivo_cache(pasta_cache, "internet-archive", numero)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache(arquivo, numero)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    try:
        _esperar("internet-archive")
        resposta = sessao.get(IA_URL, params={
            "q": f'isbn:"{numero}"',
            "fl[]": "identifier,title,creator,publisher,date,year,language,subject,isbn",
            "rows": 10, "output": "json",
        }, timeout=30)
        resposta.raise_for_status()
        resultado = _parse_ia(resposta.json(), numero)
        _salvar_cache(arquivo, numero, "Internet Archive", resultado)
        return resultado
    except Exception:
        return []


def consultar_open_library(isbn, pasta_cache, sessao=None, atualizar=False):
    numero = normalizar_isbn(isbn)
    if not requests or len(numero) not in (10, 13):
        return {}
    arquivo = _arquivo_cache(pasta_cache, "open-library", numero)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache(arquivo, numero)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    try:
        _esperar("open-library")
        resposta = sessao.get(OPEN_LIBRARY_URL, params={
            "bibkeys": f"ISBN:{numero}", "format": "json", "jscmd": "data",
        }, timeout=25)
        resposta.raise_for_status()
        dado = resposta.json().get(f"ISBN:{numero}")
        resultado = {}
        if dado:
            data = str(dado.get("publish_date") or "")
            resultado = {
                "titulo": dado.get("title") or "",
                "subtitulo": dado.get("subtitle") or "",
                "autores": "; ".join(x.get("name", "")
                                      for x in dado.get("authors", [])),
                "editora": "; ".join(x.get("name", "")
                                      for x in dado.get("publishers", [])),
                "ano": (re.search(r"\b(\d{4})\b", data) or [None, ""])[1],
                "paginas": str(dado.get("number_of_pages") or ""),
                "assuntos": "; ".join(x.get("name", "")
                                      for x in dado.get("subjects", [])[:5]),
                "fonte": "OpenLibrary",
            }
        _salvar_cache(arquivo, numero, "Open Library", resultado)
        return resultado
    except Exception:
        return {}


def consultar_google_books(isbn, pasta_cache, sessao=None, atualizar=False):
    numero = normalizar_isbn(isbn)
    if not requests or len(numero) not in (10, 13):
        return {}
    arquivo = _arquivo_cache(pasta_cache, "google-books", numero)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache(arquivo, numero)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    try:
        _esperar("google-books")
        resposta = sessao.get(GOOGLE_BOOKS_URL,
                              params={"q": f"isbn:{numero}"}, timeout=25)
        resposta.raise_for_status()
        itens = resposta.json().get("items") or []
        resultado = {}
        for item in itens:
            volume = item.get("volumeInfo", {})
            identificadores = {normalizar_isbn(x.get("identifier"))
                               for x in volume.get("industryIdentifiers", [])}
            if numero not in identificadores:
                continue
            data = str(volume.get("publishedDate") or "")
            resultado = {
                "titulo": volume.get("title") or "",
                "subtitulo": volume.get("subtitle") or "",
                "autores": "; ".join(volume.get("authors") or []),
                "editora": volume.get("publisher") or "",
                "ano": (re.search(r"\b(\d{4})\b", data) or [None, ""])[1],
                "paginas": str(volume.get("pageCount") or ""),
                "assuntos": "; ".join((volume.get("categories") or [])[:5]),
                "fonte": "GoogleBooks",
            }
            break
        _salvar_cache(arquivo, numero, "Google Books", resultado)
        return resultado
    except Exception:
        return {}


def consultar_google_books_titulo_autor(titulo, autor, pasta_cache,
                                         sessao=None, atualizar=False):
    """Recupera livro sem ISBN somente com correspondência forte e única."""
    titulo = " ".join(str(titulo or "").split()).strip()
    autor = " ".join(str(autor or "").split()).strip()
    if not requests or len(titulo) < 4 or len(autor) < 3:
        return {}
    arquivo = _arquivo_cache_texto(
        pasta_cache, "google-books-titulo-autor", titulo, autor)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache_texto(arquivo, titulo, autor)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    resultado = {}
    try:
        _esperar("google-books")
        resposta = sessao.get(
            GOOGLE_BOOKS_URL,
            params={"q": f'intitle:"{titulo}" inauthor:"{autor}"',
                    "maxResults": 10}, timeout=25)
        resposta.raise_for_status()
        candidatos = []
        for item in resposta.json().get("items") or []:
            volume = item.get("volumeInfo") or {}
            titulo_candidato = volume.get("title") or ""
            autores = volume.get("authors") or []
            autor_candidato = "; ".join(autores)
            pontos_titulo = _similaridade(titulo, titulo_candidato)
            pontos_autor = _similaridade_autor(autor, autor_candidato)
            if pontos_titulo < 0.68 or pontos_autor < 0.60:
                continue
            pontos = 0.68 * pontos_titulo + 0.32 * pontos_autor
            data = str(volume.get("publishedDate") or "")
            identificadores = {
                str(x.get("type") or ""): normalizar_isbn(x.get("identifier"))
                for x in volume.get("industryIdentifiers") or []}
            candidatos.append({
                "titulo": titulo_candidato,
                "subtitulo": volume.get("subtitle") or "",
                "autores": autor_candidato,
                "editora": volume.get("publisher") or "",
                "ano": (re.search(r"\b(\d{4})\b", data) or [None, ""])[1],
                "paginas": str(volume.get("pageCount") or ""),
                "assuntos": "; ".join((volume.get("categories") or [])[:5]),
                "isbn": (identificadores.get("ISBN_13")
                         or identificadores.get("ISBN_10") or ""),
                "fonte": "GoogleBooks (título + autor)",
                "correspondencia": "titulo_autor",
                "confianca": "alta",
                "pontuacao": round(pontos, 4),
                "pontuacao_titulo": round(pontos_titulo, 4),
                "pontuacao_autor": round(pontos_autor, 4),
            })
        candidatos.sort(key=lambda x: x["pontuacao"], reverse=True)
        if candidatos:
            melhor = candidatos[0]
            segundo = candidatos[1] if len(candidatos) > 1 else {}
            empate_ambiguo = False
            if segundo and melhor["pontuacao"] - segundo["pontuacao"] < 0.08:
                empate_ambiguo = any(
                    melhor.get(campo) and segundo.get(campo)
                    and melhor[campo] != segundo[campo]
                    for campo in ("editora", "ano", "isbn"))
            if (melhor["pontuacao"] >= 0.76
                    and melhor["pontuacao_titulo"] >= 0.72
                    and melhor["pontuacao_autor"] >= 0.66
                    and not empate_ambiguo):
                resultado = melhor
        _salvar_cache_texto(
            arquivo, "Google Books", titulo, autor, resultado)
        return resultado
    except Exception:
        return {}


def _subcampos_marc(registro, tag, codigos=None):
    """Retorna subcampos MARCXML sem depender do prefixo usado no XML."""
    valores = []
    for campo in registro.findall(
            f".//{{http://www.loc.gov/MARC21/slim}}datafield[@tag='{tag}']"):
        for subcampo in campo.findall(
                "{http://www.loc.gov/MARC21/slim}subfield"):
            codigo = subcampo.get("code", "")
            texto = " ".join((subcampo.text or "").split()).strip(" /:;,.\t")
            if texto and (not codigos or codigo in codigos):
                valores.append((codigo, texto))
    return valores


def _parse_loc_marc(xml, isbn=""):
    """Converte registros MARCXML da Library of Congress em nossa ficha."""
    raiz = ET.fromstring(xml)
    numero = normalizar_isbn(isbn)
    registros = raiz.findall(".//{http://www.loc.gov/MARC21/slim}record")
    candidatos = []
    for registro in registros:
        isbns = {
            normalizar_isbn(valor.split()[0])
            for _, valor in _subcampos_marc(registro, "020", {"a"})}
        if numero and numero not in isbns:
            continue
        titulo_partes = dict(_subcampos_marc(registro, "245", {"a", "b"}))
        titulo = titulo_partes.get("a", "")
        subtitulo = titulo_partes.get("b", "")
        autores = [valor for _, valor in _subcampos_marc(
            registro, "100", {"a"})]
        autores.extend(valor for _, valor in _subcampos_marc(
            registro, "700", {"a"}))
        publicacao = (_subcampos_marc(registro, "264", {"a", "b", "c"})
                      or _subcampos_marc(registro, "260", {"a", "b", "c"}))
        por_codigo = {}
        for codigo, valor in publicacao:
            por_codigo.setdefault(codigo, valor)
        descricao = " ".join(
            valor for _, valor in _subcampos_marc(registro, "300", {"a"}))
        mp = re.search(r"\b(\d{1,5})\s+(?:pages?|p\.?)(?:\b|\s)",
                       descricao, re.I)
        assuntos = []
        for tag in ("600", "610", "650", "651"):
            valores = [valor for _, valor in _subcampos_marc(
                registro, tag, {"a", "x", "v"})]
            if valores:
                assuntos.append(" -- ".join(valores))
        controle = registro.find(
            "{http://www.loc.gov/MARC21/slim}controlfield[@tag='001']")
        candidatos.append({
            "titulo": titulo, "subtitulo": subtitulo,
            "autores": "; ".join(dict.fromkeys(autores)),
            "editora": por_codigo.get("b", ""),
            "ano": (re.search(r"\b(?:19|20)\d{2}\b",
                               por_codigo.get("c", "")) or [""])[0],
            "paginas": mp.group(1) if mp else "",
            "assuntos": "; ".join(assuntos[:5]),
            "lugar_fonte": por_codigo.get("a", ""),
            "cdd": "; ".join(valor for _, valor in _subcampos_marc(
                registro, "082", {"a"})[:2]),
            "isbn": next(iter(isbns), ""),
            "identificador_fonte": (controle.text.strip()
                                      if controle is not None and controle.text
                                      else ""),
            "fonte": "Library of Congress",
        })
    return candidatos


def _consultar_loc(query, arquivo, cache_isbn, sessao, fonte_cache,
                   parser_isbn=""):
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    try:
        _esperar("library-of-congress")
        resposta = sessao.get(LOC_SRU_URL, params={
            "version": "1.1", "operation": "searchRetrieve",
            "query": query, "maximumRecords": 10,
            "recordSchema": "marcxml",
        }, timeout=35)
        resposta.raise_for_status()
        resultado = _parse_loc_marc(resposta.text, parser_isbn)
        _salvar_cache(arquivo, cache_isbn, fonte_cache, resultado)
        return resultado
    except Exception:
        return []


def consultar_library_of_congress(isbn, pasta_cache, sessao=None,
                                   atualizar=False):
    """Consulta a Library of Congress por ISBN e exige igualdade exata."""
    numero = normalizar_isbn(isbn)
    if not requests or len(numero) not in (10, 13):
        return {}
    arquivo = _arquivo_cache(pasta_cache, "library-of-congress", numero)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache(arquivo, numero)
        if cache is not None:
            candidatos = cache
        else:
            candidatos = []
    else:
        candidatos = _consultar_loc(
            f'bath.isbn="{numero}"', arquivo, numero,
            sessao or requests.Session(), "Library of Congress", numero)
    escolhido, _ = resolver_candidatos(candidatos)
    return escolhido


def consultar_library_of_congress_titulo_autor(
        titulo, autor, pasta_cache, sessao=None, atualizar=False):
    """Busca obra anglófona sem ISBN, aceitando só resultado forte e único."""
    titulo = " ".join(str(titulo or "").split()).strip()
    autor = " ".join(str(autor or "").split()).strip()
    if not requests or len(titulo) < 4 or len(autor) < 3:
        return {}
    arquivo = _arquivo_cache_texto(
        pasta_cache, "library-of-congress-titulo-autor", titulo, autor)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache_texto(arquivo, titulo, autor)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    resultado = {}
    try:
        _esperar("library-of-congress")
        resposta = sessao.get(LOC_SRU_URL, params={
            "version": "1.1", "operation": "searchRetrieve",
            "query": f'bath.title all "{titulo}" and bath.name all "{autor}"',
            "maximumRecords": 10, "recordSchema": "marcxml",
        }, timeout=35)
        resposta.raise_for_status()
        pontuados = []
        for candidato in _parse_loc_marc(resposta.text):
            st = _similaridade(titulo, candidato.get("titulo", ""))
            sa = _similaridade_autor(autor, candidato.get("autores", ""))
            if st >= 0.72 and sa >= 0.66:
                candidato = dict(candidato)
                candidato.update({
                    "correspondencia": "titulo_autor", "confianca": "alta",
                    "pontuacao_titulo": round(st, 4),
                    "pontuacao_autor": round(sa, 4),
                    "pontuacao": round(0.68 * st + 0.32 * sa, 4),
                })
                pontuados.append(candidato)
        pontuados.sort(key=lambda x: x["pontuacao"], reverse=True)
        if pontuados and (len(pontuados) == 1
                          or pontuados[0]["pontuacao"]
                          - pontuados[1]["pontuacao"] >= 0.08):
            resultado = pontuados[0]
        _salvar_cache_texto(
            arquivo, "Library of Congress", titulo, autor, resultado)
        return resultado
    except Exception:
        return {}


def consultar_hathitrust(isbn, pasta_cache, sessao=None, atualizar=False):
    """Usa o catálogo HathiTrust apenas quando o ISBN do registro é exato."""
    numero = normalizar_isbn(isbn)
    if not requests or len(numero) not in (10, 13):
        return {}
    arquivo = _arquivo_cache(pasta_cache, "hathitrust", numero)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache(arquivo, numero)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    resultado = {}
    try:
        _esperar("hathitrust")
        resposta = sessao.get(HATHITRUST_URL.format(isbn=numero), timeout=30)
        resposta.raise_for_status()
        registros = (resposta.json().get("records") or {}).values()
        candidatos = []
        for dado in registros:
            isbns = {normalizar_isbn(x) for x in _lista(dado.get("isbns"))}
            if numero not in isbns:
                continue
            data = " ".join(str(x) for x in _lista(dado.get("publishDates")))
            candidatos.append({
                "titulo": next(iter(_lista(dado.get("titles"))), ""),
                "subtitulo": "",
                "autores": "; ".join(str(x) for x in _lista(dado.get("authors"))),
                "editora": "; ".join(str(x) for x in _lista(dado.get("publishers"))),
                "ano": (re.search(r"\b(?:19|20)\d{2}\b", data) or [""])[0],
                "paginas": "", "assuntos": "",
                "lugar_fonte": "; ".join(
                    str(x) for x in _lista(dado.get("publishPlaces"))),
                "identificador_fonte": dado.get("recordURL") or "",
                "isbn": numero, "fonte": "HathiTrust",
            })
        escolhido, _ = resolver_candidatos(candidatos)
        resultado = escolhido
        _salvar_cache(arquivo, numero, "HathiTrust", resultado)
        return resultado
    except Exception:
        return {}


def consultar_crossref_artigo(titulo, autor, pasta_cache, doi="",
                               sessao=None, atualizar=False):
    """Confirma artigos por DOI ou por título e autor com limiar conservador."""
    titulo = " ".join(str(titulo or "").split()).strip()
    autor = " ".join(str(autor or "").split()).strip()
    doi = str(doi or "").strip().lower()
    if not requests or (not doi and len(titulo) < 8):
        return {}
    chave_titulo = f"doi:{doi}" if doi else titulo
    arquivo = _arquivo_cache_texto(
        pasta_cache, "crossref-artigo", chave_titulo, autor)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache_texto(arquivo, chave_titulo, autor)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    resultado = {}
    try:
        _esperar("crossref")
        if doi:
            resposta = sessao.get(
                CROSSREF_URL + "/" + doi, params={"mailto": "piraginejr@gmail.com"},
                timeout=30)
            resposta.raise_for_status()
            itens = [resposta.json().get("message") or {}]
        else:
            resposta = sessao.get(CROSSREF_URL, params={
                "query.title": titulo, "query.author": autor,
                "filter": "type:journal-article", "rows": 5,
                "mailto": "piraginejr@gmail.com",
            }, timeout=30)
            resposta.raise_for_status()
            itens = resposta.json().get("message", {}).get("items") or []
        candidatos = []
        for item in itens:
            titulo_item = next(iter(item.get("title") or []), "")
            autores = "; ".join(" ".join(
                x for x in (p.get("given", ""), p.get("family", "")) if x)
                for p in item.get("author") or [])
            st = 1.0 if doi else _similaridade(titulo, titulo_item)
            sa = (_similaridade_autor(autor, autores) if autor else 1.0)
            if not doi and (st < 0.80 or (autor and sa < 0.55)):
                continue
            publicado = (item.get("published-print")
                          or item.get("published-online") or item.get("issued") or {})
            partes = publicado.get("date-parts") or []
            ano = str(partes[0][0]) if partes and partes[0] else ""
            pagina = str(item.get("page") or "")
            candidatos.append({
                "titulo": titulo_item, "subtitulo": "", "autores": autores,
                "editora": (next(iter(item.get("container-title") or []), "")
                            or item.get("publisher") or ""),
                "ano": ano, "paginas": pagina,
                "assuntos": "; ".join(item.get("subject") or []),
                "issn": "; ".join(item.get("ISSN") or []),
                "doi": item.get("DOI") or doi,
                "tipo_fonte": item.get("type") or "",
                "fonte": "Crossref", "correspondencia": "doi" if doi else "titulo_autor",
                "confianca": "alta", "pontuacao_titulo": round(st, 4),
                "pontuacao_autor": round(sa, 4),
                "pontuacao": round(0.75 * st + 0.25 * sa, 4),
            })
        candidatos.sort(key=lambda x: x["pontuacao"], reverse=True)
        if candidatos and (doi or len(candidatos) == 1
                           or candidatos[0]["pontuacao"]
                           - candidatos[1]["pontuacao"] >= 0.06):
            resultado = candidatos[0]
        _salvar_cache_texto(
            arquivo, "Crossref", chave_titulo, autor, resultado)
        return resultado
    except Exception:
        return {}


def _autores_openalex(item):
    nomes = []
    for autoria in item.get("authorships") or []:
        nome = (autoria.get("author") or {}).get("display_name") or ""
        if nome and nome not in nomes:
            nomes.append(nome)
    return "; ".join(nomes)


def _instituicao_openalex(item):
    nomes = []
    for autoria in item.get("authorships") or []:
        for instituicao in autoria.get("institutions") or []:
            nome = instituicao.get("display_name") or ""
            if nome and nome not in nomes:
                nomes.append(nome)
    fonte = (((item.get("primary_location") or {}).get("source") or {})
             .get("display_name") or "")
    if fonte and fonte not in nomes:
        nomes.append(fonte)
    return "; ".join(nomes[:3])


def _resultado_openalex(item, titulo, autor):
    titulo_item = item.get("display_name") or item.get("title") or ""
    autores = _autores_openalex(item)
    st = _similaridade(titulo, titulo_item)
    sa = _similaridade_autor(autor, autores) if autor else 1.0
    biblio = item.get("biblio") or {}
    primeira, ultima = biblio.get("first_page"), biblio.get("last_page")
    paginas = (f"{primeira}-{ultima}" if primeira and ultima and primeira != ultima
               else str(primeira or ultima or ""))
    local = item.get("best_oa_location") or item.get("primary_location") or {}
    topicos = [x.get("display_name", "") for x in item.get("topics") or []]
    return {
        "titulo": titulo_item, "subtitulo": "", "autores": autores,
        "editora": _instituicao_openalex(item),
        "instituicao": _instituicao_openalex(item),
        "ano": str(item.get("publication_year") or ""),
        "paginas": paginas, "assuntos": "; ".join(x for x in topicos[:5] if x),
        "doi": str(item.get("doi") or "").replace("https://doi.org/", ""),
        "url": (local.get("landing_page_url") or local.get("pdf_url")
                or item.get("id") or ""),
        "idioma_fonte": item.get("language") or "",
        "tipo_fonte": item.get("type") or "",
        "identificador_fonte": item.get("id") or "",
        "fonte": "OpenAlex", "correspondencia": "titulo_autor",
        "confianca": "alta", "pontuacao_titulo": round(st, 4),
        "pontuacao_autor": round(sa, 4),
        "pontuacao": round(0.72 * st + 0.28 * sa, 4),
    }


def consultar_openalex_academico(titulo, autor, tipo, pasta_cache,
                                  chave="", sessao=None, atualizar=False):
    """Consulta artigos e teses, exigindo título e autoria coerentes."""
    titulo = " ".join(str(titulo or "").split()).strip()
    autor = " ".join(str(autor or "").split()).strip()
    tipo = str(tipo or "").strip().lower()
    chave = chave or ("" if "openalex" in _CHAVES_INVALIDAS
                       else ler_chave_academica("openalex"))
    # A pesquisa bibliográfica básica da OpenAlex também funciona no modo
    # público. Uma chave válida aumenta a franquia, mas nunca deve bloquear o
    # preparo: se estiver ausente ou tiver sido revogada, repetimos sem ela.
    if not requests or len(titulo) < 8:
        return {}
    titulo_cache = f"{tipo}:{titulo}"
    arquivo = _arquivo_cache_texto(
        pasta_cache, "openalex-academico", titulo_cache, autor)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache_texto(arquivo, titulo_cache, autor)
        if cache is not None:
            return cache
    filtro_tipo = ("dissertation" if tipo in {
        "tese", "dissertação", "trabalho acadêmico", "dissertation", "thesis"
    } else "article")
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    resultado = {}
    try:
        _esperar("openalex")
        parametros = {
            "search": " ".join(x for x in (titulo, autor) if x),
            "filter": f"type:{filtro_tipo}", "per-page": 10,
        }
        if chave:
            parametros["api_key"] = chave
        resposta = sessao.get(OPENALEX_URL, params=parametros, timeout=30)
        if getattr(resposta, "status_code", 200) == 401 and chave:
            _CHAVES_INVALIDAS.add("openalex")
            parametros.pop("api_key", None)
            resposta = sessao.get(
                OPENALEX_URL, params=parametros, timeout=30)
        resposta.raise_for_status()
        candidatos = []
        for item in resposta.json().get("results") or []:
            candidato = _resultado_openalex(item, titulo, autor)
            if candidato["pontuacao_titulo"] < 0.80:
                continue
            if autor and candidato["pontuacao_autor"] < 0.60:
                continue
            tipo_item = candidato.get("tipo_fonte", "")
            if filtro_tipo == "dissertation" and tipo_item not in {
                    "dissertation", "thesis"}:
                continue
            candidatos.append(candidato)
        candidatos.sort(key=lambda x: x["pontuacao"], reverse=True)
        if candidatos:
            melhor = candidatos[0]
            segundo = candidatos[1] if len(candidatos) > 1 else {}
            if (not segundo or melhor["pontuacao"] - segundo["pontuacao"] >= 0.06
                    or (melhor.get("doi") and melhor.get("doi")
                        == segundo.get("doi"))):
                resultado = melhor
        _salvar_cache_texto(
            arquivo, "OpenAlex", titulo_cache, autor, resultado)
        return resultado
    except Exception:
        return {}


def _nome_autor_core(autor):
    if isinstance(autor, dict):
        return str(autor.get("name") or autor.get("displayName") or "").strip()
    return str(autor or "").strip()


def consultar_core_academico(titulo, autor, tipo, pasta_cache,
                              chave="", sessao=None, atualizar=False):
    """Consulta o CORE público; uma chave válida apenas amplia a franquia."""
    titulo = " ".join(str(titulo or "").split()).strip()
    autor = " ".join(str(autor or "").split()).strip()
    tipo = str(tipo or "").strip().lower()
    chave = chave or ("" if "core" in _CHAVES_INVALIDAS
                       else ler_chave_academica("core"))
    # O CORE permite consultas públicas dentro de uma franquia menor. A chave
    # é opcional e nunca deve impedir o preparo: se estiver ausente, revogada
    # ou incorreta, a mesma consulta é feita sem autenticação.
    if not requests or len(titulo) < 8:
        return {}
    titulo_cache = f"{tipo}:{titulo}"
    arquivo = _arquivo_cache_texto(
        pasta_cache, "core-academico", titulo_cache, autor)
    if arquivo.exists() and not atualizar:
        cache = _ler_cache_texto(arquivo, titulo_cache, autor)
        if cache is not None:
            return cache
    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    resultado = {}
    try:
        # O endpoint v3 responde melhor à busca textual comum do que à antiga
        # sintaxe de campos title:/authors:. Primeiro usamos título e autor;
        # se o índice não localizar nada, repetimos apenas com o título. A
        # aprovação continua exigindo título e autoria coerentes, portanto a
        # consulta mais ampla não reduz a segurança bibliográfica.
        consultas = [" ".join(x for x in (titulo, autor) if x)]
        if autor:
            consultas.append(titulo)
        for consulta in consultas:
            _esperar("core")
            cabecalhos = ({"Authorization": f"Bearer {chave}"}
                          if chave else {})
            resposta = sessao.get(
                CORE_URL, params={"q": consulta, "limit": 10},
                headers=cabecalhos, timeout=35)
            if getattr(resposta, "status_code", 200) in {401, 403} and chave:
                _CHAVES_INVALIDAS.add("core")
                chave = ""
                resposta = sessao.get(
                    CORE_URL, params={"q": consulta, "limit": 10},
                    headers={}, timeout=35)
            resposta.raise_for_status()
            candidatos = []
            for item in resposta.json().get("results") or []:
                titulo_item = item.get("title") or ""
                autores = "; ".join(
                    x for x in (_nome_autor_core(a)
                                for a in item.get("authors") or []) if x)
                st = _similaridade(titulo, titulo_item)
                sa = _similaridade_autor(autor, autores) if autor else 1.0
                if st < 0.80 or (autor and sa < 0.60):
                    continue
                provedores = []
                for provedor in item.get("dataProviders") or []:
                    nome = (provedor.get("name", "")
                            if isinstance(provedor, dict) else str(provedor))
                    if nome:
                        provedores.append(nome)
                urls = item.get("sourceFulltextUrls") or []
                candidatos.append({
                    "titulo": titulo_item, "subtitulo": "", "autores": autores,
                    "editora": "; ".join(provedores[:3]),
                    "instituicao": "; ".join(provedores[:3]),
                    "ano": str(item.get("yearPublished") or ""),
                    "paginas": "", "assuntos": "",
                    "doi": item.get("doi") or "",
                    "url": item.get("downloadUrl") or next(iter(urls), ""),
                    "tipo_fonte": item.get("documentType") or "",
                    "identificador_fonte": str(item.get("id") or ""),
                    "fonte": "CORE", "correspondencia": "titulo_autor",
                    "confianca": "alta", "pontuacao_titulo": round(st, 4),
                    "pontuacao_autor": round(sa, 4),
                    "pontuacao": round(0.72 * st + 0.28 * sa, 4),
                })
            candidatos.sort(key=lambda x: x["pontuacao"], reverse=True)
            if candidatos and (len(candidatos) == 1
                               or candidatos[0]["pontuacao"]
                               - candidatos[1]["pontuacao"] >= 0.06):
                resultado = candidatos[0]
                break
        _salvar_cache_texto(arquivo, "CORE", titulo_cache, autor, resultado)
        return resultado
    except Exception:
        return {}


def link_oatd(titulo, autor=""):
    """Cria uma busca manual no OATD; o serviço não oferece API/exportação."""
    consulta = " ".join(x for x in (str(titulo or "").strip(),
                                     str(autor or "").strip()) if x)
    return OATD_BUSCA_URL + "?" + urlencode({"q": consulta}) if consulta else ""


def pasta_cache_para_pdf(caminho):
    pasta = Path(caminho).expanduser().resolve().parent
    # O PDF usado no envio pode estar em _preparados-envio, enquanto o
    # original fica em 10-REVISAO ou 20-PRONTOS. O código antigo reconhecia
    # apenas algumas pastas e, por isso, criava um segundo cache dentro de
    # _preparados-envio. A ficha correta já existia, mas desaparecia na
    # reanálise. A raiz da biblioteca é definida pela presença de _controle,
    # independentemente do nome futuro da subpasta.
    for candidata in (pasta, *pasta.parents):
        if (candidata / "_controle").is_dir():
            pasta = candidata
            break
    else:
        if (pasta.name in {"00-ENTRADA", "10-REVISAO", "20-PRONTOS",
                           "30-ARQUIVADOS", "_preparados-envio"}
                or re.match(r"^(?:15|16|17|18|19)-", pasta.name)):
            pasta = pasta.parent
    return pasta / "_controle" / "cache-fontes"


def main():
    ap = argparse.ArgumentParser(
        description="Configura e verifica fontes bibliográficas acadêmicas")
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--configurar-openalex", action="store_true")
    grupo.add_argument("--configurar-core", action="store_true")
    grupo.add_argument("--status-chaves", action="store_true")
    args = ap.parse_args()
    if args.configurar_openalex:
        guardar_chave_academica("openalex")
        print("Chave OpenAlex protegida no Chaves do macOS.")
    elif args.configurar_core:
        guardar_chave_academica("core")
        print("Chave CORE protegida no Chaves do macOS.")
    else:
        print(json.dumps({
            "openalex": ("configurada; modo público é fallback"
                           if ler_chave_academica("openalex")
                           else "modo público; chave opcional para maior franquia"),
            "core": ("configurada; modo público é fallback"
                     if ler_chave_academica("core")
                     else "modo público; chave opcional para maior franquia"),
            "oatd": "consulta manual disponível; não exige chave",
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
