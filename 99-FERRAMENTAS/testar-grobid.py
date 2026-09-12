#!/usr/bin/env python3
"""Avalia o GROBID numa amostra isolada; nao altera nem cadastra o acervo."""

import argparse
import csv
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import time
import unicodedata
import xml.etree.ElementTree as ET

import requests


NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def normalizar(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", texto.lower()))


def texto_no(elemento):
    if elemento is None:
        return ""
    return " ".join(
        parte.strip() for parte in elemento.itertext() if parte.strip())


def extrair_tei(conteudo):
    raiz = ET.fromstring(conteudo)
    titulo = raiz.find(".//tei:sourceDesc//tei:analytic/tei:title[@level='a']", NS)
    if titulo is None:
        titulo = raiz.find(".//tei:titleStmt/tei:title", NS)
    autores = []
    for autor in raiz.findall(".//tei:sourceDesc//tei:analytic/tei:author", NS):
        nome = autor.find(".//tei:persName", NS)
        valor = texto_no(nome if nome is not None else autor)
        if valor and valor not in autores:
            autores.append(valor)
    doi = ""
    for identificador in raiz.findall(".//tei:idno", NS):
        if str(identificador.get("type", "")).lower() == "doi":
            doi = texto_no(identificador)
            break
    data = raiz.find(".//tei:sourceDesc//tei:monogr//tei:imprint/tei:date", NS)
    ano = ""
    if data is not None:
        ano = re.search(r"(?:19|20)\d{2}", data.get("when", "") or texto_no(data))
        ano = ano.group(0) if ano else ""
    periodico = raiz.find(".//tei:sourceDesc//tei:monogr/tei:title[@level='j']", NS)
    resumo = raiz.find(".//tei:profileDesc/tei:abstract", NS)
    palavras = [texto_no(termo) for termo in
                raiz.findall(".//tei:profileDesc//tei:keywords//tei:term", NS)]
    return {
        "titulo": texto_no(titulo),
        "autores": autores,
        "doi": doi,
        "ano": ano,
        "periodico": texto_no(periodico),
        "abstract": texto_no(resumo),
        "palavras_chave": [p for p in palavras if p],
    }


def comparar(extraido, esperado):
    titulo = SequenceMatcher(
        None, normalizar(extraido.get("titulo")),
        normalizar(esperado.get("titulo"))).ratio()
    nomes_extraidos = normalizar(" ".join(extraido.get("autores", [])))
    sobrenomes = []
    for autor in esperado.get("autores", []):
        partes = normalizar(autor).split()
        if partes:
            sobrenomes.append(partes[-1])
    autores_ok = sum(1 for nome in sobrenomes if nome in nomes_extraidos)
    recall_autores = autores_ok / len(sobrenomes) if sobrenomes else 1.0
    doi_ok = normalizar(extraido.get("doi")) == normalizar(esperado.get("doi"))
    ano_ok = str(extraido.get("ano", "")) == str(esperado.get("ano", ""))
    return {
        "similaridade_titulo": round(titulo, 3),
        "recall_autores": round(recall_autores, 3),
        "doi_correto": doi_ok,
        "ano_correto": ano_ok,
        "titulo_aprovado": titulo >= 0.90,
        "autores_aprovados": recall_autores >= 0.80,
        "essencial_aprovado": titulo >= 0.90 and recall_autores >= 0.80,
    }


def avaliar(manifesto, pasta_pdfs, endpoint, timeout=180):
    itens = json.loads(Path(manifesto).read_text(encoding="utf-8"))["itens"]
    resultados = []
    for posicao, esperado in enumerate(itens, 1):
        pdf = Path(pasta_pdfs) / esperado["arquivo"]
        inicio = time.monotonic()
        print(f"[{posicao}/{len(itens)}] {pdf.name}", flush=True)
        try:
            with pdf.open("rb") as arquivo:
                resposta = requests.post(
                    endpoint.rstrip("/") + "/api/processHeaderDocument",
                    files={"input": (pdf.name, arquivo, "application/pdf")},
                    data={"consolidateHeader": "0", "includeRawAffiliations": "1"},
                    timeout=timeout)
            resposta.raise_for_status()
            extraido = extrair_tei(resposta.text)
            comparacao = comparar(extraido, esperado)
            erro = ""
        except Exception as exc:
            extraido = {}
            comparacao = {"similaridade_titulo": 0.0, "recall_autores": 0.0,
                          "doi_correto": False, "ano_correto": False,
                          "titulo_aprovado": False, "autores_aprovados": False,
                          "essencial_aprovado": False}
            erro = f"{type(exc).__name__}: {exc}"
        segundos = round(time.monotonic() - inicio, 3)
        resultados.append({"arquivo": pdf.name, "esperado": esperado,
                           "extraido": extraido, "comparacao": comparacao,
                           "segundos": segundos, "erro": erro})
        estado = "ok" if comparacao["essencial_aprovado"] else "revisar"
        print(f"    {estado}; {segundos:.2f}s; titulo="
              f"{comparacao['similaridade_titulo']:.1%}; autores="
              f"{comparacao['recall_autores']:.1%}", flush=True)
    return resultados


def salvar(resultados, destino):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    pacote = {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total": len(resultados),
        "essencial_aprovado": sum(
            r["comparacao"]["essencial_aprovado"] for r in resultados),
        "titulo_aprovado": sum(
            r["comparacao"]["titulo_aprovado"] for r in resultados),
        "autores_aprovados": sum(
            r["comparacao"]["autores_aprovados"] for r in resultados),
        "doi_correto": sum(r["comparacao"]["doi_correto"] for r in resultados),
        "ano_correto": sum(r["comparacao"]["ano_correto"] for r in resultados),
        "segundos_total": round(sum(r["segundos"] for r in resultados), 3),
        "resultados": resultados,
    }
    (destino / "resultado-grobid.json").write_text(
        json.dumps(pacote, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    with (destino / "resultado-grobid.csv").open(
            "w", newline="", encoding="utf-8-sig") as arquivo:
        campos = ["arquivo", "segundos", "titulo", "autores", "doi", "ano",
                  "similaridade_titulo", "recall_autores", "doi_correto",
                  "ano_correto", "titulo_aprovado", "autores_aprovados",
                  "essencial_aprovado", "erro"]
        escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        for item in resultados:
            ex, cp = item["extraido"], item["comparacao"]
            escritor.writerow({
                "arquivo": item["arquivo"], "segundos": item["segundos"],
                "titulo": ex.get("titulo", ""),
                "autores": " | ".join(ex.get("autores", [])),
                "doi": ex.get("doi", ""), "ano": ex.get("ano", ""),
                **cp, "erro": item["erro"],
            })
    return pacote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifesto", required=True)
    parser.add_argument("--pdfs", required=True)
    parser.add_argument("--saida", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8070")
    args = parser.parse_args()
    pacote = salvar(
        avaliar(args.manifesto, args.pdfs, args.endpoint), args.saida)
    print(json.dumps({k: v for k, v in pacote.items() if k != "resultados"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
