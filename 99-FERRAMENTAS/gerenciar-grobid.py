#!/usr/bin/env python3
"""Prepara o GROBID local sem interferir em outros conteineres Docker."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen


IMAGEM = "grobid/grobid:0.9.1-crf"
CONTAINER = "biblio-grobid"
ENDPOINT = "http://127.0.0.1:8070"


def executar(*args, capturar=True):
    try:
        return subprocess.run(
            list(args), capture_output=capturar, text=True, check=False)
    except OSError:
        return None


def vivo(endpoint):
    try:
        with urlopen(endpoint.rstrip("/") + "/api/isalive", timeout=2) as r:
            return r.status == 200 and "true" in r.read().decode().lower()
    except Exception:
        return False


def marcador(raiz):
    caminho = Path(raiz).expanduser().resolve() / "_controle"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho / "grobid-iniciado-pelo-aplicativo"


def status(endpoint):
    if vivo(endpoint):
        print(f"GROBID disponível em {endpoint}")
        return 0
    docker = executar("docker", "info")
    if docker is None:
        print("GROBID desligado; Docker não foi encontrado.")
        return 1
    if docker.returncode:
        print("GROBID desligado; o mecanismo Docker/OrbStack não está ativo.")
        return 1
    imagem = executar("docker", "image", "inspect", IMAGEM)
    if not imagem or imagem.returncode:
        print(f"GROBID desligado; falta instalar a imagem {IMAGEM}.")
        return 1
    print("GROBID desligado; imagem local pronta para iniciar.")
    return 1


def garantir(raiz, endpoint):
    if vivo(endpoint):
        print(f"   GROBID local já está disponível em {endpoint}.")
        return 0
    # Um endereço institucional configurado nunca autoriza iniciar um
    # contêiner local como substituto silencioso.
    if endpoint.rstrip("/") != ENDPOINT:
        print(f"   GROBID configurado em {endpoint}, mas está indisponível.")
        return 1
    docker = executar("docker", "info")
    if docker is None or docker.returncode:
        print("   GROBID não iniciado: abra o Docker/OrbStack.")
        return 1
    imagem = executar("docker", "image", "inspect", IMAGEM)
    if not imagem or imagem.returncode:
        print("   GROBID não instalado. Use a opção 15 uma vez para instalar.")
        return 1

    existente = executar("docker", "container", "inspect", CONTAINER)
    if existente and existente.returncode == 0:
        iniciado = executar("docker", "start", CONTAINER)
    else:
        iniciado = executar(
            "docker", "run", "-d", "--name", CONTAINER,
            "-p", "127.0.0.1:8070:8070", IMAGEM)
    if not iniciado or iniciado.returncode:
        detalhe = ((iniciado.stderr or iniciado.stdout).strip()
                   if iniciado else "Docker indisponível")
        print(f"   GROBID não pôde ser iniciado: {detalhe}")
        return 1
    marcador(raiz).write_text(
        f"container={CONTAINER}\niniciado_em={time.strftime('%Y-%m-%dT%H:%M:%S')}\n",
        encoding="utf-8")
    print("   Iniciando o leitor acadêmico local", end="", flush=True)
    for _ in range(90):
        if vivo(endpoint):
            print(" pronto.")
            return 0
        print(".", end="", flush=True)
        time.sleep(1)
    print(" tempo esgotado; o ciclo continuará sem GROBID.")
    return 1


def parar(raiz):
    arquivo = marcador(raiz)
    if not arquivo.exists():
        return 0
    executar("docker", "stop", CONTAINER)
    executar("docker", "rm", CONTAINER)
    try:
        arquivo.unlink()
    except OSError:
        pass
    print("   Leitor acadêmico local encerrado.")
    return 0


def instalar():
    docker = executar("docker", "info")
    if docker is None or docker.returncode:
        print("Abra o Docker/OrbStack antes de instalar o GROBID.")
        return 1
    print(f"Baixando {IMAGEM}; são aproximadamente 1,7 GB...")
    resultado = executar("docker", "pull", IMAGEM, capturar=False)
    return resultado.returncode if resultado else 1


def main():
    ap = argparse.ArgumentParser()
    grupo = ap.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--status", action="store_true")
    grupo.add_argument("--garantir", action="store_true")
    grupo.add_argument("--parar", action="store_true")
    grupo.add_argument("--instalar", action="store_true")
    ap.add_argument("--raiz", default=".")
    ap.add_argument("--endpoint", default=(
        os.environ.get("BIBLIO_GROBID_URL") or ENDPOINT))
    args = ap.parse_args()
    if args.status:
        return status(args.endpoint)
    if args.garantir:
        return garantir(args.raiz, args.endpoint)
    if args.parar:
        return parar(args.raiz)
    return instalar()


if __name__ == "__main__":
    sys.exit(main())
