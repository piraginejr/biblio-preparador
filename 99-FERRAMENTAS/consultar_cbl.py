#!/usr/bin/env python3
"""Consulta unitaria ao catalogo publico ISBN Brasil/CBL.

O conector reproduz apenas a busca exata por ISBN oferecida pela pagina
publica da CBL. Cada resposta fica em cache local para que o mesmo livro nao
gere novas consultas em execucoes futuras. Nao ha busca em massa, login,
contorno de CAPTCHA ou tentativa de enumerar o catalogo.
"""

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:  # o programa principal sabe trabalhar sem rede
    requests = None


PAGINA_PUBLICA = "https://www.cblservicos.org.br/isbn/pesquisa/"
API_VERSION = "2020-06-30"
INTERVALO_MINIMO = 8.0
USER_AGENT = "Biblio-PIB-Curitiba/1.0 (consulta bibliografica unitaria)"
_CONFIG = None
_ULTIMA_CONSULTA = 0.0
_LOCK = threading.Lock()


def normalizar_isbn(valor):
    return re.sub(r"[^0-9Xx]", "", str(valor or "")).upper()


def isbn_valido(valor):
    numero = normalizar_isbn(valor)
    if len(numero) == 13 and numero.isdigit():
        soma = sum(int(c) * (1 if i % 2 == 0 else 3)
                   for i, c in enumerate(numero[:12]))
        return (10 - soma % 10) % 10 == int(numero[-1])
    if len(numero) == 10:
        if not numero[:9].isdigit() or not re.fullmatch(r"[0-9X]", numero[-1]):
            return False
        soma = sum((10 - i) * (10 if c == "X" else int(c))
                   for i, c in enumerate(numero))
        return soma % 11 == 0
    return False


def isbn_brasileiro(isbn):
    """Reconhece os grupos brasileiros atuais (65) e historicos (85)."""
    numero = normalizar_isbn(isbn)
    return isbn_valido(numero) and (
        numero.startswith(("97865", "97885"))
        or (len(numero) == 10 and numero.startswith("85")))


def formatar_isbn_busca(isbn):
    """Forma com hífens suficiente para melhorar a busca pública da CBL."""
    numero = normalizar_isbn(isbn)
    if len(numero) == 13 and numero.startswith("978"):
        return f"{numero[:3]}-{numero[3:5]}-{numero[5:9]}-{numero[9:12]}-{numero[-1]}"
    if len(numero) == 10:
        return f"{numero[:2]}-{numero[2:6]}-{numero[6:9]}-{numero[-1]}"
    return numero


def _extrair_configuracao(html):
    campos = {}
    for chave in ("IndexName", "QueryKey", "ServiceName"):
        m = re.search(rf'["\']{chave}["\']\s*:\s*["\']([^"\']+)', html)
        if not m:
            return {}
        campos[chave] = m.group(1)
    return campos


def _configuracao(sessao):
    global _CONFIG
    if _CONFIG:
        return _CONFIG
    resposta = sessao.get(PAGINA_PUBLICA, timeout=25)
    resposta.raise_for_status()
    config = _extrair_configuracao(resposta.text)
    if not config:
        raise RuntimeError("a pagina publica da CBL nao informou a configuracao de busca")
    _CONFIG = config
    return config


def _esperar_intervalo():
    global _ULTIMA_CONSULTA
    with _LOCK:
        espera = INTERVALO_MINIMO - (time.monotonic() - _ULTIMA_CONSULTA)
        if espera > 0:
            time.sleep(espera)
        _ULTIMA_CONSULTA = time.monotonic()


def _converter(item):
    autores = item.get("Authors") or []
    idiomas = item.get("IdiomasObra") or []
    paises = item.get("Countries") or []
    ano = item.get("Ano")
    # Date e a data de atribuicao do ISBN, nao necessariamente a data de
    # publicacao. Ela fica na evidencia e nunca preenche o ano do tombo.
    return {
        "titulo": item.get("Title") or "",
        "subtitulo": item.get("Subtitle") or "",
        "autores": "; ".join(autores),
        "editora": item.get("Imprint") or "",
        "ano": str(ano or ""),
        "paginas": str(item.get("Paginas") or ""),
        "edicao": str(item.get("Edicao") or ""),
        "assuntos": item.get("Subject") or "",
        "idiomas_cbl": "; ".join(idiomas),
        "paises_cbl": "; ".join(paises),
        "data_atribuicao_isbn": item.get("Date") or "",
        "origem_registro_cbl": item.get("PartitionKey") or "",
        "fonte": "CBL/ISBN Brasil",
    }


def _ler_cache(arquivo, isbn):
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if dados.get("isbn") != isbn:
        return None
    resultado = dados.get("resultado")
    return resultado if isinstance(resultado, dict) else {}


def _salvar_cache(arquivo, isbn, resultado, status):
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    dados = {
        "isbn": isbn,
        "consultado_em": datetime.now().isoformat(timespec="seconds"),
        "fonte": PAGINA_PUBLICA,
        "tipo_consulta": "ISBN exato",
        "status": status,
        "resultado": resultado,
    }
    temporario = arquivo.with_name(arquivo.name + ".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    os.replace(temporario, arquivo)


def consultar(isbn, pasta_cache, sessao=None, atualizar=False):
    """Retorna metadados CBL para um ISBN brasileiro exato.

    Resposta vazia significa ISBN nao brasileiro, nao encontrado ou falha de
    rede. Falhas nao sao gravadas como resultado definitivo; uma execucao
    futura pode tentar novamente.
    """
    numero = normalizar_isbn(isbn)
    if not requests or not isbn_brasileiro(numero):
        return {}
    arquivo = Path(pasta_cache) / f"{numero}.json"
    if not atualizar and arquivo.exists():
        cached = _ler_cache(arquivo, numero)
        if cached is not None:
            return cached

    sessao = sessao or requests.Session()
    sessao.headers.setdefault("User-Agent", USER_AGENT)
    try:
        config = _configuracao(sessao)
        _esperar_intervalo()
        url = (f"https://{config['ServiceName']}.search.windows.net/"
               f"indexes/{config['IndexName']}/docs")
        def buscar(termo):
            resposta = sessao.get(
                url,
                params={
                    "api-version": API_VERSION,
                    "search": termo,
                    "searchFields": "FormattedKey,RowKey",
                    "$top": 5,
                    "$select": ("Authors,Profissoes,Colection,Countries,Date,Imprint,"
                                "Title,Subtitle,RowKey,PartitionKey,RecordId,FormattedKey,"
                                "Subject,Veiculacao,Ano,IdiomasObra,Paginas,Edicao"),
                },
                headers={"api-key": config["QueryKey"]},
                timeout=25,
            )
            resposta.raise_for_status()
            return resposta.json().get("value", [])

        itens = buscar(numero)
        exatos = [item for item in itens if numero in {
            normalizar_isbn(item.get("FormattedKey")),
            normalizar_isbn(item.get("RowKey")),
        }]
        if not exatos:
            termo_formatado = formatar_isbn_busca(numero)
            if termo_formatado and termo_formatado != numero:
                itens = buscar(termo_formatado)
                exatos = [item for item in itens if numero in {
                    normalizar_isbn(item.get("FormattedKey")),
                    normalizar_isbn(item.get("RowKey")),
                }]
        resultado = _converter(exatos[0]) if len(exatos) == 1 else {}
        status = "encontrado" if resultado else (
            "conflito" if len(exatos) > 1 else "nao_encontrado")
        _salvar_cache(arquivo, numero, resultado, status)
        return resultado
    except Exception:
        return {}


def pasta_cache_para_pdf(caminho):
    """Mantem o cache no controle da biblioteca, nunca junto dos PDFs."""
    pasta = Path(caminho).expanduser().resolve().parent
    if pasta.name in {"00-ENTRADA", "10-REVISAO", "20-PRONTOS",
                      "30-ARQUIVADOS"}:
        pasta = pasta.parent
    return pasta / "_controle" / "cache-cbl"
