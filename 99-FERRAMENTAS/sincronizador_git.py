#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sincronizador Cooperativo e Auto-Update via Git.

Este módulo implementa:
1. Consulta rápida de fichas catalogadas por SHA-256 no repositório cooperativo.
2. Sincronização incremental de dicionários inteligentes (editoras, cidades, ruídos).
3. Verificação e aplicação segura de atualizações contínuas do motor via GitHub.
4. Resiliência a falhas de rede: se offline, o sistema opera 100% com o cache local.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("biblio.sincronizador")

VERSAO_MOTOR_LOCAL = "0.3.0"
REPO_OWNER_PADRAO = "piraginejr"
REPO_NOME_PADRAO = "biblio-preparador"
BRANCH_PADRAO = "main"

URL_RAW_PADRAO = f"https://raw.githubusercontent.com/{REPO_OWNER_PADRAO}/{REPO_NOME_PADRAO}/{BRANCH_PADRAO}"


def _fazer_requisicao_json(url: str, timeout: float = 3.5) -> Optional[Dict[str, Any]]:
    """Executa requisição GET HTTP(S) e decodifica resposta JSON.

    Retorna None em caso de 404, timeout, offline ou erro de decodificação.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"BiblioPreparador/{VERSAO_MOTOR_LOCAL} (Python-urllib)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                conteudo = resp.read().decode("utf-8")
                return json.loads(conteudo)
    except urllib.error.HTTPError as err:
        if err.code == 404:
            logger.debug("Arquivo não encontrado no Git (404): %s", url)
        else:
            logger.warning("Falha HTTP %s ao consultar %s: %s", err.code, url, err)
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        logger.debug("Rede indisponível ou timeout ao consultar %s: %s", url, err)
    except json.JSONDecodeError as err:
        logger.warning("Resposta inválida de JSON ao consultar %s: %s", url, err)
    except Exception as err:
        logger.warning("Erro inesperado ao consultar %s: %s", url, err)
    return None


# -----------------------------------------------------------------------------
# 1. Base Cooperativa: Consulta de Fichas por SHA-256
# -----------------------------------------------------------------------------

def consultar_ficha_cooperativa(
    sha256: str,
    pasta_cache: Optional[Path] = None,
    url_base_raw: str = URL_RAW_PADRAO,
    timeout: float = 3.5,
) -> Optional[Dict[str, Any]]:
    """Consulta ficha técnica pré-catalogada a partir do SHA-256 do PDF.

    Cadeia de resolução:
      1. Cache local em disco (se fornecido pasta_cache).
      2. Repositório Git via raw URL: dados/fichas/{hash[:2]}/{hash}.json.
    """
    if not sha256 or len(sha256) < 64:
        return None

    sha256 = sha256.lower().strip()
    prefixo = sha256[:2]

    # 1. Verificar cache local
    if pasta_cache:
        caminho_cache = Path(pasta_cache) / prefixo / f"{sha256}.json"
        if caminho_cache.is_file():
            try:
                with open(caminho_cache, "r", encoding="utf-8") as f:
                    dados = json.load(f)
                    if isinstance(dados, dict):
                        return dados
            except Exception as err:
                logger.warning("Falha ao ler cache local de ficha %s: %s", caminho_cache, err)

    # 2. Consultar base cooperativa remota
    url = f"{url_base_raw.rstrip('/')}/dados/fichas/{prefixo}/{sha256}.json"
    ficha_remota = _fazer_requisicao_json(url, timeout=timeout)

    # Se encontrada remotamente e houver pasta de cache, persiste localmente
    if ficha_remota and pasta_cache:
        try:
            caminho_cache = Path(pasta_cache) / prefixo / f"{sha256}.json"
            caminho_cache.parent.mkdir(parents=True, exist_ok=True)
            with open(caminho_cache, "w", encoding="utf-8") as f:
                json.dump(ficha_remota, f, ensure_ascii=False, indent=2)
        except Exception as err:
            logger.warning("Não foi possível salvar cache local de ficha: %s", err)

    return ficha_remota


# -----------------------------------------------------------------------------
# 2. Sincronização Incremental de Dicionários
# -----------------------------------------------------------------------------

def mesclar_dicionario(local: Dict[str, Any], remoto: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Mescla dicionário remoto no local de forma não-destrutiva.

    Suporta:
      - Listas (ex: termos ruído, autores ruído): adiciona novos sem duplicar.
      - Dicionários aninhados (ex: editoras -> cidades): acrescenta chaves novas.
    Retorna (dicionario_mesclado, qtd_novas_entradas).
    """
    resultado = dict(local)
    novas = 0

    for chave, valor_remoto in remoto.items():
        if chave not in resultado:
            resultado[chave] = valor_remoto
            novas += 1
        elif isinstance(resultado[chave], list) and isinstance(valor_remoto, list):
            # Identificação segura de duplicatas para tipos simples e dicionários
            vistos = set()
            for item in resultado[chave]:
                if isinstance(item, dict):
                    id_item = (item.get("nome_bibliografico") or item.get("editora")
                               or item.get("nome") or json.dumps(item, sort_keys=True))
                    vistos.add(id_item)
                else:
                    vistos.add(item)

            for item in valor_remoto:
                if isinstance(item, dict):
                    id_item = (item.get("nome_bibliografico") or item.get("editora")
                               or item.get("nome") or json.dumps(item, sort_keys=True))
                else:
                    id_item = item

                if id_item not in vistos:
                    resultado[chave].append(item)
                    vistos.add(id_item)
                    novas += 1
        elif isinstance(resultado[chave], dict) and isinstance(valor_remoto, dict):
            sub_res, sub_novas = mesclar_dicionario(resultado[chave], valor_remoto)
            resultado[chave] = sub_res
            novas += sub_novas

    return resultado, novas


def sincronizar_dicionarios(
    pasta_local_ferramentas: Path,
    url_base_raw: str = URL_RAW_PADRAO,
    timeout: float = 4.0,
) -> Dict[str, int]:
    """Sincroniza dicionários inteligentes conhecidos com a base comunitária.

    Retorna relatório {nome_arquivo: qtd_novos_registros}.
    """
    arquivos = [
        "editoras-cidades.json",
        "autores-conhecidos.json",
        "autores-ruidosos-conhecidos.json",
        "titulos-ruidosos-conhecidos.json",
        "periodicos-conhecidos.json",
    ]
    relatorio: Dict[str, int] = {}
    pasta_local = Path(pasta_local_ferramentas)

    for nome in arquivos:
        url = f"{url_base_raw.rstrip('/')}/dados/{nome}"
        remoto = _fazer_requisicao_json(url, timeout=timeout)
        if not remoto or not isinstance(remoto, dict):
            relatorio[nome] = 0
            continue

        caminho_local = pasta_local / nome
        local: Dict[str, Any] = {}
        if caminho_local.is_file():
            try:
                with open(caminho_local, "r", encoding="utf-8") as f:
                    local = json.load(f)
            except Exception:
                local = {}

        mesclado, qtd_novas = mesclar_dicionario(local, remoto)
        if qtd_novas > 0:
            try:
                caminho_tmp = caminho_local.with_suffix(".tmp")
                with open(caminho_tmp, "w", encoding="utf-8") as f:
                    json.dump(mesclado, f, ensure_ascii=False, indent=2)
                caminho_tmp.replace(caminho_local)
                logger.info("Dicionário %s enriquecido com %d novos registros.", nome, qtd_novas)
            except Exception as err:
                logger.warning("Falha ao salvar dicionário mesclado %s: %s", nome, err)

        relatorio[nome] = qtd_novas

    return relatorio


# -----------------------------------------------------------------------------
# 3. Auto-Update Contínuo do Motor via Git
# -----------------------------------------------------------------------------

def _parse_versao(v_str: str) -> Tuple[int, ...]:
    """Converte '1.2.3' em (1, 2, 3) para comparação semântica."""
    partes = []
    for pedaco in str(v_str).strip().lstrip("v").split("."):
        try:
            partes.append(int(pedaco))
        except ValueError:
            partes.append(0)
    return tuple(partes)


def verificar_atualizacao_motor(
    versao_local: str = VERSAO_MOTOR_LOCAL,
    url_base_raw: str = URL_RAW_PADRAO,
    timeout: float = 3.5,
) -> Dict[str, Any]:
    """Consulta version.json no repositório para verificar disponibilidade de update.

    Retorna dicionário com:
      - disponivel (bool)
      - versao_remota (str)
      - changelog (str)
      - arquivos_modificados (list[str])
    """
    url = f"{url_base_raw.rstrip('/')}/versao-motor.json"
    manifesto = _fazer_requisicao_json(url, timeout=timeout)

    if not manifesto or not isinstance(manifesto, dict):
        return {"disponivel": False, "motivo": "sem_resposta"}

    versao_remota = str(manifesto.get("versao", "0.0.0"))
    tem_update = _parse_versao(versao_remota) > _parse_versao(versao_local)

    return {
        "disponivel": tem_update,
        "versao_local": versao_local,
        "versao_remota": versao_remota,
        "data": manifesto.get("data"),
        "changelog": manifesto.get("changelog", ""),
        "arquivos_modificados": manifesto.get("arquivos_modificados", []),
        "manifesto": manifesto,
    }


def aplicar_atualizacao_motor(
    info_update: Dict[str, Any],
    pasta_raiz_projeto: Path,
    url_base_raw: str = URL_RAW_PADRAO,
    timeout: float = 10.0,
) -> Tuple[bool, List[str]]:
    """Baixa e aplica de forma atômica os arquivos atualizados do motor.

    Cria backup com extensão .bak antes de sobrescrever.
    Retorna (sucesso_geral, lista_de_arquivos_atualizados).
    """
    arquivos = info_update.get("arquivos_modificados", [])
    if not arquivos:
        return False, []

    raiz = Path(pasta_raiz_projeto)
    aplicados = []

    for rel_path in arquivos:
        url = f"{url_base_raw.rstrip('/')}/{rel_path.lstrip('/')}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": f"BiblioPreparador/{VERSAO_MOTOR_LOCAL}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    conteudo = resp.read()
                else:
                    logger.warning("Falha ao baixar %s (status %s)", url, resp.status)
                    continue
        except Exception as err:
            logger.warning("Erro ao baixar atualização de %s: %s", rel_path, err)
            continue

        destino = raiz / rel_path
        destino.parent.mkdir(parents=True, exist_ok=True)

        # Fazer backup do arquivo existente
        if destino.is_file():
            shutil.copy2(destino, destino.with_suffix(destino.suffix + ".bak"))

        # Gravar novo arquivo de forma atômica
        destino_tmp = destino.with_suffix(destino.suffix + ".novo")
        with open(destino_tmp, "wb") as f:
            f.write(conteudo)
        destino_tmp.replace(destino)
        aplicados.append(rel_path)

    sucesso = len(aplicados) == len(arquivos)
    return sucesso, aplicados


# -----------------------------------------------------------------------------
# 4. Utilitário: Exportação de Revisões Aprovadas para a Base Git
# -----------------------------------------------------------------------------

def exportar_revisoes_para_fichas(
    caminho_revisoes_json: Path,
    pasta_dados_fichas: Path,
) -> int:
    """Lê revisões manuais locais aprovadas e exporta para dados/fichas/{hash[:2]}/{hash}.json."""
    caminho = Path(caminho_revisoes_json)
    if not caminho.is_file():
        return 0

    with open(caminho, "r", encoding="utf-8") as f:
        dados = json.load(f)

    livros = dados.get("livros", {})
    exportados = 0
    saida = Path(pasta_dados_fichas)

    for nome_pdf, ficha in livros.items():
        if not isinstance(ficha, dict):
            continue
        # Exporta apenas fichas explicitamente aprovadas
        if not ficha.get("aprovado", False):
            continue

        sha256 = ficha.get("hash_sha256", "").strip().lower()
        if not sha256 or len(sha256) < 64:
            continue

        prefixo = sha256[:2]
        pasta_prefixo = saida / prefixo
        pasta_prefixo.mkdir(parents=True, exist_ok=True)

        registro_exportado = {
            "hash_sha256": sha256,
            "arquivo_origem": nome_pdf,
            "campos": ficha.get("campos", {}),
            "justificativa": ficha.get("justificativa", ""),
            "fontes": ficha.get("fontes", []),
        }

        arquivo_ficha = pasta_prefixo / f"{sha256}.json"
        with open(arquivo_ficha, "w", encoding="utf-8") as f:
            json.dump(registro_exportado, f, ensure_ascii=False, indent=2)
        exportados += 1

    return exportados


def exportar_acervo_completo(
    pasta_livros: Path,
    pasta_saida_fichas: Path,
) -> int:
    """Consolida todas as fontes de acervo local e exporta para dados/fichas/{prefixo}/{sha256}.json.

    Fontes integradas com precedência:
      1. livros/_metadados/*.json (fichas completas de livros, revistas e artigos preparados)
      2. livros/_controle/envios-api.json (registros com confirmação de sucesso na API)
      3. livros/_controle/revisoes-manuais.json (decisões humanas validadas têm precedência)
    """
    saida = Path(pasta_saida_fichas)
    fichas_consolidadas: Dict[str, Dict[str, Any]] = {}

    # 1. Carregar _metadados/*.json
    pasta_meta = Path(pasta_livros) / "_metadados"
    if pasta_meta.is_dir():
        for arq_meta in pasta_meta.glob("*.json"):
            try:
                with open(arq_meta, "r", encoding="utf-8") as f:
                    d = json.load(f)
                h = str(d.get("hash_sha256", "")).lower().strip()
                if len(h) == 64:
                    campos = {
                        "titulo": d.get("titulo", ""),
                        "subTitulo": d.get("subTitulo", ""),
                        "nmAutor0": d.get("nmAutor0", ""),
                        "autores": d.get("autores", []),
                        "editora": d.get("editora", ""),
                        "data": str(d.get("data", "")),
                        "edicao": d.get("edicao", ""),
                        "lugar": d.get("lugar") or d.get("local", ""),
                        "nPaginas": str(d.get("nPaginas", "")),
                        "isbn": d.get("isbn", ""),
                        "isbn_codigo_barras": d.get("isbn_codigo_barras", ""),
                        "cdd": d.get("cdd", ""),
                        "nmLingua": d.get("nmLingua", ""),
                        "tipo_documento": d.get("tipo_documento", "livro"),
                        "abstract": d.get("abstract", ""),
                        "palavrasChave": d.get("palavrasChave", ""),
                    }
                    fichas_consolidadas[h] = {
                        "hash_sha256": h,
                        "arquivo_origem": d.get("arquivo", arq_meta.name),
                        "campos": campos,
                        "justificativa": "Preparado e validado pelo motor Biblio",
                        "fontes": ["Metadados locais do acervo"],
                    }
            except Exception as err:
                logger.debug("Erro ao ler %s: %s", arq_meta, err)

    # 2. Carregar envios-api.json (enriquecer com confirmações da API)
    caminho_envios = Path(pasta_livros) / "_controle" / "envios-api.json"
    if caminho_envios.is_file():
        try:
            with open(caminho_envios, "r", encoding="utf-8") as f:
                d_env = json.load(f)
            for h, envio in d_env.get("envios", {}).items():
                h = str(h).lower().strip()
                if len(h) == 64:
                    if h in fichas_consolidadas:
                        if envio.get("id_remoto"):
                            fichas_consolidadas[h]["id_remoto"] = envio["id_remoto"]
                        fichas_consolidadas[h]["fontes"].append("API Biblio PIB Curitiba")
                    else:
                        fichas_consolidadas[h] = {
                            "hash_sha256": h,
                            "arquivo_origem": envio.get("arquivo", ""),
                            "campos": {
                                "titulo": envio.get("titulo", ""),
                                "isbn": envio.get("isbn", ""),
                            },
                            "justificativa": "Cadastrado na API Biblio",
                            "fontes": ["API Biblio PIB Curitiba"],
                        }
        except Exception as err:
            logger.debug("Erro ao ler envios-api.json: %s", err)

    # 3. Sobrepor revisoes-manuais.json (decisão humana sobrepõe qualquer heurística)
    caminho_revisoes = Path(pasta_livros) / "_controle" / "revisoes-manuais.json"
    if caminho_revisoes.is_file():
        try:
            with open(caminho_revisoes, "r", encoding="utf-8") as f:
                d_rev = json.load(f)
            for arq, rev in d_rev.get("livros", {}).items():
                if not rev.get("aprovado", False):
                    continue
                h = str(rev.get("hash_sha256", "")).lower().strip()
                if len(h) == 64:
                    if h not in fichas_consolidadas:
                        fichas_consolidadas[h] = {
                            "hash_sha256": h,
                            "arquivo_origem": arq,
                            "campos": rev.get("campos", {}),
                            "justificativa": rev.get("justificativa", "Revisão humana aprovada"),
                            "fontes": rev.get("fontes", ["Revisão humana"]),
                        }
                    else:
                        # Sobrescreve com os campos revisados por humano
                        for campo, val in rev.get("campos", {}).items():
                            if val:
                                fichas_consolidadas[h]["campos"][campo] = val
                        fichas_consolidadas[h]["justificativa"] = rev.get("justificativa", "Revisão humana aprovada")
                        fichas_consolidadas[h]["fontes"].extend(rev.get("fontes", []))
        except Exception as err:
            logger.debug("Erro ao ler revisoes-manuais.json: %s", err)

    # Gravar todas as fichas no formato particionado dados/fichas/{prefixo}/{sha256}.json
    total_gravadas = 0
    for h, ficha in fichas_consolidadas.items():
        prefixo = h[:2]
        pasta_prefixo = saida / prefixo
        pasta_prefixo.mkdir(parents=True, exist_ok=True)
        caminho_arq = pasta_prefixo / f"{h}.json"
        try:
            with open(caminho_arq, "w", encoding="utf-8") as f:
                json.dump(ficha, f, ensure_ascii=False, indent=2)
            total_gravadas += 1
        except Exception as err:
            logger.warning("Falha ao gravar ficha %s: %s", caminho_arq, err)

    return total_gravadas

