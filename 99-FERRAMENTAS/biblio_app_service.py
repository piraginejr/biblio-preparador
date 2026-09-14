#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camada de serviço do Biblio Preparador.

Esta camada é a ponte entre a interface visual e o motor já existente.
Ela não reimplementa o preparo: apenas chama os mesmos scripts usados pelo
``LIVROS.command`` e devolve progresso legível para a interface.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional


BASE = pathlib.Path(__file__).resolve().parent
PROJETO = BASE.parent
PYTHON = sys.executable


def ambiente_app() -> Dict[str, str]:
    """Ambiente previsível para o app aberto pelo Finder/WebView.

    Aplicativos macOS não herdam o mesmo PATH do Terminal. Sem isso,
    ferramentas instaladas pelo Homebrew, como ocrmypdf, tesseract, pdftoppm,
    qpdf e ghostscript, ficam invisíveis para o preparo de OCR e capas.
    """
    env = os.environ.copy()
    caminhos = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    atual = env.get("PATH", "")
    for caminho in reversed(caminhos):
        if caminho not in atual.split(":"):
            atual = f"{caminho}:{atual}" if atual else caminho
    env["PATH"] = atual
    env["PYTHONPYCACHEPREFIX"] = "/private/tmp/biblio-pycache"
    env.setdefault("CLANG_MODULE_CACHE_PATH", "/private/tmp/biblio-clang-cache")
    env.setdefault("SWIFT_MODULE_CACHE_PATH", "/private/tmp/biblio-swift-cache")
    env.setdefault("MODULE_CACHE_DIR", "/private/tmp/biblio-swift-cache")
    return env


def biblioteca_padrao() -> pathlib.Path:
    return PROJETO / "livros"


def python_cmd(script: str, *args: str) -> List[str]:
    return [PYTHON, str(BASE / script), *map(str, args)]


def playwright_disponivel() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def preparar_ambiente_nativo() -> int:
    """Compila auxiliares nativos exigidos pelo preparo visual.

    O script antigo ``LIVROS.command`` fazia isso antes de abrir o menu. No
    aplicativo Mac, essa responsabilidade precisa ficar dentro do próprio app.
    """
    obrigatorios = ["ocrmypdf", "tesseract", "pdftoppm"]
    faltando = [nome for nome in obrigatorios
                if not shutil.which(nome, path=ambiente_app()["PATH"])]
    if faltando:
        print("Ferramentas essenciais ausentes para OCR/capa: "
              + ", ".join(faltando))
        print("Instale pelo Homebrew e reabra o Biblio Preparador.")
        return 1

    qpdf = shutil.which("qpdf", path=ambiente_app()["PATH"])
    gs = shutil.which("gs", path=ambiente_app()["PATH"])
    print("OCRmyPDF encontrado.")
    print("Tesseract encontrado para orientação e segunda camada.")
    print("Poppler/pdftoppm encontrado para gerar capas.")
    if qpdf:
        print("qpdf encontrado para otimização sem perdas.")
    if gs:
        print("Ghostscript encontrado para compactação quando necessária.")

    fonte = BASE / "vision-ocr.swift"
    binario = BASE / "vision-ocr"
    if not fonte.is_file():
        print("vision-ocr.swift não encontrado; OCR Apple Vision indisponível.")
        return 1
    if binario.is_file() and os.access(binario, os.X_OK):
        if binario.stat().st_mtime >= fonte.stat().st_mtime:
            print("Apple Vision OCR já preparado.")
            return 0

    compilador = shutil.which("xcrun", path=ambiente_app()["PATH"])
    if compilador:
        comando = [compilador, "swiftc", "-O", str(fonte), "-o", str(binario)]
    else:
        swiftc = shutil.which("swiftc", path=ambiente_app()["PATH"])
        if not swiftc:
            print("Compilador Swift não encontrado; instale Xcode/Command Line Tools.")
            return 1
        comando = [swiftc, "-O", str(fonte), "-o", str(binario)]

    print("Compilando auxiliar Apple Vision OCR...")
    tmp = pathlib.Path("/private/tmp") / f"biblio-vision-ocr-{os.getpid()}"
    comando[-1] = str(tmp)
    try:
        subprocess.run(
            comando, cwd=str(BASE), check=True, env=ambiente_app(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tmp.replace(binario)
        binario.chmod(0o755)
        print("Apple Vision OCR preparado.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(exc.stdout or str(exc))
        return exc.returncode or 1
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


@dataclass
class Etapa:
    titulo: str
    comando: List[str]
    obrigatoria: bool = True


@dataclass
class Job:
    id: str
    nome: str
    criado_em: float = field(default_factory=time.time)
    encerrado_em: Optional[float] = None
    estado: str = "rodando"
    etapa_atual: str = ""
    linhas: List[str] = field(default_factory=list)
    codigo_saida: Optional[int] = None

    def log(self, texto: str) -> None:
        for linha in str(texto).splitlines() or [""]:
            self.linhas.append(linha)
        if len(self.linhas) > 1200:
            self.linhas = self.linhas[-1200:]

    def como_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "nome": self.nome,
            "estado": self.estado,
            "etapa_atual": self.etapa_atual,
            "linhas": self.linhas,
            "codigo_saida": self.codigo_saida,
            "criado_em": self.criado_em,
            "encerrado_em": self.encerrado_em,
        }


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def iniciar(self, nome: str, etapas: Iterable[Etapa], cwd: pathlib.Path = BASE) -> Job:
        job = Job(id=str(uuid.uuid4()), nome=nome)
        with self._lock:
            self._jobs[job.id] = job
        thread = threading.Thread(
            target=self._executar_etapas, args=(job, list(etapas), cwd),
            daemon=True)
        thread.start()
        return job

    def obter(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def ultimo(self) -> Optional[Job]:
        with self._lock:
            if not self._jobs:
                return None
            return max(self._jobs.values(), key=lambda j: j.criado_em)

    def _executar_etapas(self, job: Job, etapas: List[Etapa], cwd: pathlib.Path) -> None:
        try:
            for indice, etapa in enumerate(etapas, start=1):
                job.etapa_atual = etapa.titulo
                job.log("")
                job.log(f"[{indice}/{len(etapas)}] {etapa.titulo}")
                job.log("$ " + " ".join(etapa.comando))
                processo = subprocess.Popen(
                    etapa.comando,
                    cwd=str(cwd),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=ambiente_app(),
                )
                assert processo.stdout is not None
                for linha in processo.stdout:
                    job.log(linha.rstrip())
                codigo = processo.wait()
                job.codigo_saida = codigo
                if codigo != 0:
                    mensagem = f"Etapa terminou com código {codigo}."
                    if etapa.obrigatoria:
                        job.log(mensagem)
                        job.estado = "erro"
                        return
                    job.log(mensagem + " Continuando porque a etapa é opcional.")
            job.estado = "concluido"
        except Exception as exc:
            job.log(f"Erro inesperado: {exc}")
            job.estado = "erro"
        finally:
            job.encerrado_em = time.time()


JOBS = JobManager()


def inicializar_biblioteca(raiz: pathlib.Path) -> None:
    raiz.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--inicializar"),
        cwd=str(BASE),
        check=True,
        env=ambiente_app(),
    )


def status_texto(raiz: pathlib.Path) -> str:
    inicializar_biblioteca(raiz)
    proc = subprocess.run(
        python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--status"),
        cwd=str(BASE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=ambiente_app(),
    )
    return proc.stdout


def contagens_basicas(raiz: pathlib.Path) -> Dict[str, int]:
    inicializar_biblioteca(raiz)
    pastas = {
        "entrada": raiz / "00-ENTRADA",
        "revisao": raiz / "10-REVISAO",
        "prontos": raiz / "20-PRONTOS",
        "documentos": raiz / "16-ARTIGOS-E-DOCUMENTOS",
        "academicos": raiz / "15-TESES-DISSERTACOES-E-TRABALHOS",
        "revistas": raiz / "17-REVISTAS-E-PERIODICOS",
        "descarte": raiz / "19-DESCARTE",
    }
    resultado = {}
    for nome, pasta in pastas.items():
        if pasta.exists():
            resultado[nome] = sum(1 for p in pasta.rglob("*") if p.is_file() and not p.name.startswith("."))
        else:
            resultado[nome] = 0
    return resultado


def etapas_preparar(raiz: pathlib.Path, com_internet: bool = True) -> List[Etapa]:
    etapas = [
        Etapa("Preparando OCR Apple Vision",
              python_cmd("biblio_app_service.py", "--preparar-ambiente")),
        Etapa("Preparando o leitor acadêmico local (GROBID)",
              python_cmd("gerenciar-grobid.py", "--raiz", str(raiz), "--garantir"),
              obrigatoria=False),
        Etapa("Corrigindo OCR e tamanho pendentes",
              python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--corrigir-ocr")),
        Etapa("Processando os materiais novos",
              python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--processar")),
        Etapa("Conciliando PDF, ISBN e bases bibliográficas/acadêmicas",
              python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--reprocessar-revisao")),
    ]
    if com_internet and playwright_disponivel():
        etapas.extend([
            Etapa("Consultando Estante Virtual para obras em português",
                  python_cmd("consultar-web-navegador.py", "--raiz", str(raiz),
                             "--motor", "estante", "--limite", "0", "--executar",
                             "--oculto"),
                  obrigatoria=False),
            Etapa("Aplicando consenso da Estante Virtual",
                  python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--reprocessar-revisao")),
            Etapa("Consultando Amazon conforme idioma da obra",
                  python_cmd("consultar-web-navegador.py", "--raiz", str(raiz),
                             "--motor", "amazon", "--limite", "0", "--executar",
                             "--oculto"),
                  obrigatoria=False),
        ])
    elif com_internet:
        etapas.append(Etapa("Navegador automatizado ausente; pulando Estante/Amazon",
                            ["/bin/echo", "Playwright não está disponível neste ambiente."],
                            obrigatoria=False))
    etapas.extend([
        Etapa("Conciliação final",
              python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--reprocessar-revisao")),
        Etapa("Atualizando fila de envio",
              python_cmd("enviar-livro-api.py", "--atualizar-fila", str(raiz))),
        Etapa("Resumo da biblioteca",
              python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--status")),
    ])
    return etapas


def etapas_enviar_tudo(raiz: pathlib.Path, enviar: bool, limite: int = 0) -> List[Etapa]:
    cmd = python_cmd("enviar-livro-api.py", "--processar-todas-filas", str(raiz),
                     "--limite", str(limite), "--intervalo", "3")
    if enviar:
        cmd.append("--enviar")
    return [
        Etapa("Atualizando fila de livros",
              python_cmd("enviar-livro-api.py", "--atualizar-fila", str(raiz))),
        Etapa("Atualizando filas específicas",
              python_cmd("biblioteca-local.py", "--raiz", str(raiz),
                         "--atualizar-filas-especificas")),
        Etapa("Enviando tudo que estiver pronto" if enviar else "Simulando envio unificado",
              cmd),
        Etapa("Resumo final",
              python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--status")),
    ]


def etapas_liberar_espaco(raiz: pathlib.Path, executar: bool) -> List[Etapa]:
    cmd = python_cmd("biblioteca-local.py", "--raiz", str(raiz), "--liberar-espaco")
    if executar:
        cmd.append("--executar")
    return [
        Etapa("Atualizando fila antes da limpeza",
              python_cmd("enviar-livro-api.py", "--atualizar-fila", str(raiz))),
        Etapa("Liberando espaço" if executar else "Simulando liberação de espaço",
              cmd),
    ]


def abrir_entrada(raiz: pathlib.Path) -> None:
    inicializar_biblioteca(raiz)
    entrada = raiz / "00-ENTRADA"
    subprocess.Popen(["open", str(entrada)])


def abrir_revisao(raiz: pathlib.Path, voltar_url: str = "") -> Job:
    cmd = python_cmd("revisao-visual.py", "--raiz", str(raiz),
                     "--limite", "0", "--abrir")
    if voltar_url:
        cmd.extend(["--voltar-url", voltar_url])
    return JOBS.iniciar(
        "Bancada de revisão visual",
        [Etapa("Abrindo bancada de revisão visual", cmd)],
    )


def importar_arquivos(raiz: pathlib.Path, arquivos: Iterable[pathlib.Path]) -> List[Dict[str, str]]:
    inicializar_biblioteca(raiz)
    entrada = raiz / "00-ENTRADA"
    resultado = []
    for arquivo in arquivos:
        destino = entrada / arquivo.name
        if destino.exists():
            base = destino.stem
            sufixo = destino.suffix
            n = 2
            while True:
                candidato = entrada / f"{base} ({n}){sufixo}"
                if not candidato.exists():
                    destino = candidato
                    break
                n += 1
        shutil.copy2(arquivo, destino)
        resultado.append({"origem": str(arquivo), "destino": str(destino)})
    return resultado


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--preparar-ambiente"]:
        return preparar_ambiente_nativo()
    print("Uso interno: biblio_app_service.py --preparar-ambiente")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
