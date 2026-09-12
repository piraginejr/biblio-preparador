#!/usr/bin/env python3
"""Baixa, com cautela, o acervo Full Gospel Business Men's Voice da ORU.

O programa funciona em modo de simulação por padrão. Para efetuar downloads,
é necessário informar explicitamente ``--baixar``.

Exemplos:

    python3 99-FERRAMENTAS/baixar_acervo.py
    python3 99-FERRAMENTAS/baixar_acervo.py --simular --limite 5
    python3 99-FERRAMENTAS/baixar_acervo.py --baixar --intervalo 5
    python3 99-FERRAMENTAS/baixar_acervo.py --baixar-via-chrome --limite 1

Os PDFs são materiais protegidos por direitos autorais. Este programa os
mantém apenas no acervo local e não os publica nem os envia ao GitHub.
"""

from __future__ import annotations

import argparse
import atexit
import csv
import hashlib
import http.cookiejar
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO, Iterable


COLECAO_PADRAO = "https://digitalshowcase.oru.edu/voice/"
USER_AGENT = (
    "FGMBV-Acervo/1.0 "
    "(pesquisa privada; contato via pagina institucional da ORU)"
)
MANIFEST_FIELDS = [
    "record_url",
    "pdf_url",
    "titulo",
    "ano",
    "arquivo",
    "caminho_local",
    "status",
    "http_status",
    "tamanho_bytes",
    "sha256",
    "erro",
    "verificado_em_utc",
]


@dataclass
class Edicao:
    record_url: str
    pdf_url: str
    titulo: str
    ano: str
    arquivo: str


@dataclass
class ManifestRow:
    record_url: str
    pdf_url: str
    titulo: str
    ano: str
    arquivo: str
    caminho_local: str
    status: str
    http_status: str = ""
    tamanho_bytes: str = ""
    sha256: str = ""
    erro: str = ""
    verificado_em_utc: str = ""


class RecordLinkParser(HTMLParser):
    """Extrai links de registros /voice/<n> da página da coleção."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        absolute = urllib.parse.urljoin(self.base_url, href)
        parsed = urllib.parse.urlparse(absolute)
        if re.fullmatch(r"/voice/\d+/?", parsed.path):
            canonical = urllib.parse.urlunparse(
                (parsed.scheme, parsed.netloc, parsed.path.rstrip("/") + "/", "", "", "")
            )
            self.links.append(canonical)


class RecordParser(HTMLParser):
    """Extrai metadados e o link PDF da página de uma edição."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.meta: dict[str, str] = {}
        self.pdf_links: list[str] = []
        self.page_title_parts: list[str] = []
        self._inside_title = False

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attrs_dict = {key.lower(): value for key, value in attrs}
        lower_tag = tag.lower()
        if lower_tag == "meta":
            name = (attrs_dict.get("name") or attrs_dict.get("property") or "").lower()
            content = attrs_dict.get("content")
            if name and content:
                self.meta[name] = content.strip()
        elif lower_tag == "a":
            href = attrs_dict.get("href")
            if href:
                absolute = urllib.parse.urljoin(self.base_url, href)
                if "cgi/viewcontent.cgi" in absolute and "context=voice" in absolute:
                    self.pdf_links.append(absolute.replace("&amp;", "&"))
        elif lower_tag == "title":
            self._inside_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._inside_title = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.page_title_parts.append(data)


class HttpClient:
    def __init__(self, timeout: float, tentativas: int) -> None:
        self.timeout = timeout
        self.tentativas = max(1, tentativas)
        cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar)
        )

    def _request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/pdf,"
                    "application/octet-stream;q=0.9,*/*;q=0.8"
                ),
            },
        )

    def read(self, url: str) -> tuple[bytes, int, str]:
        ultimo_erro: Exception | None = None
        for tentativa in range(1, self.tentativas + 1):
            try:
                with self.opener.open(
                    self._request(url), timeout=self.timeout
                ) as response:
                    body = response.read()
                    status = getattr(response, "status", 200)
                    content_type = response.headers.get_content_type()
                    return body, status, content_type
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                ultimo_erro = exc
                if tentativa < self.tentativas:
                    time.sleep(min(2**tentativa, 10))
        raise RuntimeError(f"Falha ao acessar {url}: {ultimo_erro}")

    def download_pdf(
        self,
        *,
        record_url: str,
        pdf_url: str,
        temporary_path: Path,
    ) -> tuple[int, int, str]:
        """Aquece a página do registro e baixa o PDF para um arquivo temporário."""

        ultimo_erro: Exception | None = None
        ultimo_status = 0
        for tentativa in range(1, self.tentativas + 1):
            try:
                # O Digital Commons pode devolver 403/504 quando o CGI é
                # acessado sem que a página da edição tenha sido carregada.
                self.read(record_url)
                request = self._request(pdf_url)
                request.add_header("Referer", record_url)
                with self.opener.open(request, timeout=self.timeout) as response:
                    ultimo_status = getattr(response, "status", 200)
                    content_type = response.headers.get_content_type()
                    tamanho, digest = _stream_to_file(response, temporary_path)
                if not _is_pdf(temporary_path, content_type):
                    temporary_path.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Resposta não é PDF (HTTP {ultimo_status}, {content_type})"
                    )
                return ultimo_status, tamanho, digest
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                RuntimeError,
            ) as exc:
                ultimo_erro = exc
                temporary_path.unlink(missing_ok=True)
                if isinstance(exc, urllib.error.HTTPError):
                    ultimo_status = exc.code
                if tentativa < self.tentativas:
                    time.sleep(min(2**tentativa, 15))
        raise RuntimeError(
            f"Download falhou após {self.tentativas} tentativa(s): {ultimo_erro}"
        )


def _stream_to_file(source: BinaryIO, destination: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    tamanho = 0
    with destination.open("xb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
            tamanho += len(chunk)
    return tamanho, digest.hexdigest()


def _is_pdf(path: Path, content_type: str) -> bool:
    try:
        with path.open("rb") as stream:
            magic = stream.read(5)
    except OSError:
        return False
    # A assinatura do arquivo é mais confiável que o Content-Type de
    # repositórios antigos, que pode variar entre application/pdf,
    # application/octet-stream e outros valores genéricos.
    return magic == b"%PDF-"


def _publish_no_clobber(temporary_path: Path, final_path: Path) -> bool:
    """Publica atomicamente sem substituir um arquivo já existente."""

    try:
        os.link(temporary_path, final_path)
        temporary_path.unlink()
        return True
    except FileExistsError:
        temporary_path.unlink(missing_ok=True)
        return False
    except OSError:
        # Fallback para sistemas de arquivos sem hard links. O modo "xb"
        # mantém a garantia de não substituir o destino.
        try:
            with temporary_path.open("rb") as source, final_path.open("xb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            temporary_path.unlink()
            return True
        except FileExistsError:
            temporary_path.unlink(missing_ok=True)
            return False


def _import_download_no_clobber(
    downloaded_path: Path,
    final_path: Path,
) -> tuple[bool, bool]:
    """Copia com segurança e remove o download somente quando permitido."""

    temporary = final_path.parent / f".{final_path.name}.browser.part"
    temporary.unlink(missing_ok=True)
    try:
        with downloaded_path.open("rb") as source, temporary.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        published = _publish_no_clobber(temporary, final_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    if not published:
        return False, False

    source_removed = False
    try:
        downloaded_path.unlink()
        source_removed = True
    except OSError:
        # Pastas geridas pelo iCloud podem permitir leitura sem remoção.
        # A cópia validada no acervo continua sendo o resultado principal.
        pass
    return True, source_removed


def _clean_title(raw: str) -> str:
    title = re.sub(r"\s+", " ", raw).strip()
    title = re.sub(r'^["\s]+|["\s]+$', "", title)
    title = re.sub(r"\s+by\s+Thomas\s+R\.\s+Nick(?:el|le)\s*$", "", title, flags=re.I)
    return title or "FGMBV-edicao-sem-titulo"


def _safe_filename(title: str) -> str:
    normalized = unicodedata.normalize("NFC", title)
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return f"{normalized[:180]}.pdf"


def _extract_year(title: str, meta: dict[str, str]) -> str:
    for key in ("bepress_citation_date", "citation_date", "dc.date"):
        value = meta.get(key, "")
        match = re.search(r"\b(19|20)\d{2}\b", value)
        if match:
            return match.group(0)
    match = re.search(r"\b(19|20)\d{2}\b", title)
    return match.group(0) if match else "SEM-ANO"


def parse_record(record_url: str, html: bytes) -> Edicao:
    text = html.decode("utf-8", errors="replace")
    parser = RecordParser(record_url)
    parser.feed(text)
    raw_title = (
        parser.meta.get("bepress_citation_title")
        or parser.meta.get("citation_title")
        or "".join(parser.page_title_parts)
    )
    titulo = _clean_title(raw_title)
    pdf_url = (
        parser.meta.get("bepress_citation_pdf_url")
        or parser.meta.get("citation_pdf_url")
        or (parser.pdf_links[0] if parser.pdf_links else "")
    )
    pdf_url = urllib.parse.urljoin(record_url, pdf_url).replace("&amp;", "&")
    if not pdf_url:
        raise ValueError("Link PDF não localizado")
    ano = _extract_year(titulo, parser.meta)
    return Edicao(
        record_url=record_url,
        pdf_url=pdf_url,
        titulo=titulo,
        ano=ano,
        arquivo=_safe_filename(titulo),
    )


def discover_record_urls(client: HttpClient, collection_url: str) -> list[str]:
    html, _, _ = client.read(collection_url)
    parser = RecordLinkParser(collection_url)
    parser.feed(html.decode("utf-8", errors="replace"))
    unique = list(dict.fromkeys(parser.links))
    return sorted(unique, key=_record_number)


def _record_number(url: str) -> int:
    match = re.search(r"/(\d+)/?$", urllib.parse.urlparse(url).path)
    return int(match.group(1)) if match else 0


def _volume_issue_key(filename: str) -> str:
    match = re.search(r"\b(\d+)\.(\d+)\b", filename)
    if match:
        return f"v{int(match.group(1))}-n{int(match.group(2))}"
    match = re.search(r"\bv(\d+)-n(\d+)\b", filename, flags=re.I)
    if match:
        return f"v{int(match.group(1))}-n{int(match.group(2))}"
    return ""


def find_existing(
    edicao: Edicao, target_path: Path, legacy_root: Path
) -> Path | None:
    if target_path.exists():
        return target_path

    legacy_year = legacy_root / edicao.ano
    exact_legacy = legacy_year / edicao.arquivo
    if exact_legacy.exists():
        return exact_legacy

    issue_key = _volume_issue_key(edicao.arquivo)
    if issue_key and legacy_year.exists():
        for candidate in legacy_year.glob("*.pdf"):
            candidate_key = _volume_issue_key(candidate.name)
            if candidate_key == issue_key:
                return candidate
    return None


def load_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as stream:
        return {
            row["record_url"]: row
            for row in csv.DictReader(stream)
            if row.get("record_url")
        }


def write_manifest(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in MANIFEST_FIELDS})
    os.replace(temporary, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download_snapshot(downloads_dir: Path) -> set[Path]:
    if not downloads_dir.is_dir():
        raise RuntimeError(f"Pasta de downloads não localizada: {downloads_dir}")
    return {
        path.resolve()
        for path in downloads_dir.iterdir()
        if path.is_file()
    }


def _default_downloads_dir() -> Path:
    icloud_downloads = (
        Path.home()
        / "Library"
        / "Mobile Documents"
        / "com~apple~CloudDocs"
        / "Downloads"
        / "Downloads"
    )
    if icloud_downloads.is_dir():
        return icloud_downloads
    return Path.home() / "Downloads"


def _wait_for_new_pdf(
    downloads_dir: Path,
    before: set[Path],
    *,
    timeout: float,
    poll_interval: float = 0.5,
) -> Path:
    deadline = time.monotonic() + max(1.0, timeout)
    stable_size: int | None = None
    stable_count = 0

    while time.monotonic() < deadline:
        current = _download_snapshot(downloads_dir)
        new_pdfs = sorted(
            path
            for path in current - before
            if path.suffix.lower() == ".pdf"
        )
        partials = [
            path
            for path in current - before
            if path.name.lower().endswith(".crdownload")
        ]
        if len(new_pdfs) > 1:
            raise RuntimeError(
                "Mais de um PDF novo apareceu em Downloads; "
                "nenhum arquivo foi movido"
            )
        if len(new_pdfs) == 1 and not partials:
            candidate = new_pdfs[0]
            size = candidate.stat().st_size
            if size > 0 and size == stable_size:
                stable_count += 1
            else:
                stable_size = size
                stable_count = 0
            if stable_count >= 2:
                if not _is_pdf(candidate, "application/pdf"):
                    raise RuntimeError(
                        f"Arquivo recebido não é um PDF válido: {candidate}"
                    )
                return candidate
        time.sleep(max(0.1, poll_interval))

    raise RuntimeError(
        f"Nenhum PDF novo foi concluído em {downloads_dir} "
        f"dentro de {timeout:g} segundos"
    )


def _osascript(lines: list[str], *arguments: str) -> str:
    command = ["osascript"]
    for line in lines:
        command.extend(["-e", line])
    if arguments:
        command.extend(["--", *arguments])
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"Falha ao controlar o Chrome: {detail}") from exc
    return completed.stdout.strip()


class ChromeDownloader:
    """Usa uma janela dedicada do Chrome e recebe o PDF em Downloads."""

    def __init__(
        self,
        downloads_dir: Path,
        *,
        page_wait: float,
        download_timeout: float,
    ) -> None:
        self.downloads_dir = downloads_dir.expanduser().resolve()
        self.page_wait = max(1.0, page_wait)
        self.download_timeout = max(5.0, download_timeout)
        self.window_id: str | None = None

    def start(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError(
                "O modo --baixar-via-chrome está disponível somente no macOS"
            )
        _download_snapshot(self.downloads_dir)
        self.window_id = _osascript(
            [
                'tell application "Google Chrome"',
                "activate",
                "set fgmbvWindow to make new window",
                "return id of fgmbvWindow",
                "end tell",
            ]
        )
        if not self.window_id:
            raise RuntimeError("Não foi possível criar a janela dedicada do Chrome")

    def close(self) -> None:
        if not self.window_id:
            return
        try:
            _osascript(
                [
                    "on run argv",
                    'tell application "Google Chrome"',
                    "set wantedId to item 1 of argv as integer",
                    "if exists (window id wantedId) then close window id wantedId",
                    "end tell",
                    "end run",
                ],
                self.window_id,
            )
        except (subprocess.CalledProcessError, OSError):
            pass
        self.window_id = None

    def _navigate(self, url: str) -> None:
        assert self.window_id is not None
        _osascript(
            [
                "on run argv",
                'tell application "Google Chrome"',
                "set wantedId to item 1 of argv as integer",
                "set targetUrl to item 2 of argv",
                "activate",
                "set index of window id wantedId to 1",
                "set URL of active tab of window id wantedId to targetUrl",
                "end tell",
                "end run",
            ],
            self.window_id,
            url,
        )

    def _reload(self) -> None:
        assert self.window_id is not None
        _osascript(
            [
                "on run argv",
                'tell application "Google Chrome"',
                "set wantedId to item 1 of argv as integer",
                "activate",
                "set index of window id wantedId to 1",
                "reload active tab of window id wantedId",
                "end tell",
                "end run",
            ],
            self.window_id,
        )

    def _title(self) -> str:
        assert self.window_id is not None
        return _osascript(
            [
                "on run argv",
                'tell application "Google Chrome"',
                "set wantedId to item 1 of argv as integer",
                "return title of active tab of window id wantedId",
                "end tell",
                "end run",
            ],
            self.window_id,
        )

    @staticmethod
    def _is_pdf_title(title: str) -> bool:
        normalized = title.strip().lower()
        if not normalized:
            return False
        blocked_titles = (
            "human verification",
            "viewcontent.cgi",
            "digitalshowcase.oru.edu",
        )
        return not any(marker in normalized for marker in blocked_titles)

    def _wait_for_pdf(self) -> str:
        deadline = time.monotonic() + self.page_wait
        last_title = ""
        while time.monotonic() < deadline:
            time.sleep(min(8.0, max(1.0, deadline - time.monotonic())))
            last_title = self._title()
            if self._is_pdf_title(last_title):
                return last_title
            self._reload()
        last_title = self._title()
        if self._is_pdf_title(last_title):
            return last_title
        raise RuntimeError(
            "O PDF não abriu no Chrome após a validação da ORU "
            f"(último título: {last_title or 'sem título'})"
        )

    def _save(self, expected_filename: str) -> None:
        assert self.window_id is not None
        _osascript(
            [
                "on run argv",
                'tell application "Google Chrome"',
                "set wantedId to item 1 of argv as integer",
                "activate",
                "set index of window id wantedId to 1",
                "end tell",
                'tell application "System Events"',
                'tell application process "Google Chrome"',
                'keystroke "s" using command down',
                "end tell",
                "end tell",
                "end run",
            ],
            self.window_id,
        )
        time.sleep(1.0)
        save_result = _osascript(
            [
                "on run argv",
                "set expectedName to item 1 of argv",
                'tell application "System Events"',
                'tell application process "Google Chrome"',
                "if (count of sheets of window 1) is 0 then return \"NO_SHEET\"",
                "if (count of sheets of window 1) is not 1 then return \"MULTIPLE_SHEETS\"",
                "tell splitter group 1 of sheet 1 of window 1",
                'set actualName to value of text field "Salvar Como:"',
                'set actualWhere to value of pop up button "Onde:"',
                "if actualName is not expectedName then "
                "return \"WRONG_NAME|\" & actualName",
                'if actualWhere does not contain "Downloads" then '
                'return "WRONG_FOLDER|" & actualWhere',
                'if enabled of button "Salvar" is false then return "SAVE_DISABLED"',
                'click button "Salvar"',
                "return \"SAVED\"",
                "end tell",
                "end tell",
                "end tell",
                "end run",
            ],
            expected_filename,
        )
        if save_result not in ("NO_SHEET", "SAVED"):
            raise RuntimeError(
                f'Não foi seguro confirmar "Salvar como": {save_result}'
            )

    def download(self, edicao: Edicao) -> Path:
        if self.window_id is None:
            self.start()
        before = _download_snapshot(self.downloads_dir)

        self._navigate(edicao.record_url)
        time.sleep(min(self.page_wait, 3.0))
        self._navigate(edicao.pdf_url)
        self._wait_for_pdf()

        self._save(edicao.arquivo)
        return _wait_for_new_pdf(
            self.downloads_dir,
            before,
            timeout=self.download_timeout,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Localiza e baixa as edições digitalizadas da Full Gospel "
            "Business Men's Voice na Oral Roberts University."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--simular",
        action="store_true",
        help="apenas descobre e registra o que seria baixado (padrão)",
    )
    mode.add_argument(
        "--baixar",
        action="store_true",
        help="autoriza efetivamente o download dos PDFs",
    )
    mode.add_argument(
        "--baixar-via-chrome",
        action="store_true",
        help=(
            "abre cada PDF em uma janela dedicada do Chrome, recebe em "
            "Downloads e move para o acervo"
        ),
    )
    parser.add_argument(
        "--colecao",
        default=COLECAO_PADRAO,
        help=f"URL da coleção (padrão: {COLECAO_PADRAO})",
    )
    parser.add_argument(
        "--raiz",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="raiz do projeto FGMBV",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=5.0,
        help="segundos de espera entre downloads (padrão: 5)",
    )
    parser.add_argument(
        "--intervalo-consulta",
        type=float,
        default=0.25,
        help="segundos entre consultas às páginas das edições (padrão: 0,25)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="limite de espera de cada requisição, em segundos",
    )
    parser.add_argument(
        "--tentativas",
        type=int,
        default=4,
        help="número de tentativas em caso de erro temporário",
    )
    parser.add_argument(
        "--limite",
        type=int,
        default=0,
        help="processa somente as primeiras N edições; 0 significa todas",
    )
    parser.add_argument(
        "--downloads",
        type=Path,
        default=_default_downloads_dir(),
        help="pasta padrão de downloads do Chrome",
    )
    parser.add_argument(
        "--espera-chrome",
        type=float,
        default=5.0,
        help="segundos de espera para a validação e abertura do PDF no Chrome",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    chrome_enabled = bool(args.baixar_via_chrome)
    download_enabled = bool(args.baixar or chrome_enabled)
    root = args.raiz.expanduser().resolve()
    # Mantém um único acervo: edições existentes e novos downloads ficam
    # organizados por ano sob 01-EDICOES-PDF.
    pdf_root = root / "01-EDICOES-PDF"
    legacy_root = pdf_root
    manifest_path = root / "download-manifest.csv"
    pdf_root.mkdir(parents=True, exist_ok=True)

    client = HttpClient(timeout=args.timeout, tentativas=args.tentativas)
    print(f"Coleção: {args.colecao}")
    print(f"Raiz: {root}")
    if chrome_enabled:
        print("Modo: DOWNLOAD VIA CHROME")
        print(f"Downloads do Chrome: {args.downloads.expanduser().resolve()}")
    else:
        print(f"Modo: {'DOWNLOAD' if download_enabled else 'SIMULAÇÃO'}")

    try:
        record_urls = discover_record_urls(client, args.colecao)
    except Exception as exc:
        print(f"ERRO: não foi possível listar a coleção: {exc}", file=sys.stderr)
        return 2

    if args.limite > 0:
        record_urls = record_urls[: args.limite]
    print(f"Registros localizados: {len(record_urls)}")

    previous = load_manifest(manifest_path)
    rows: dict[str, dict[str, str]] = dict(previous)
    download_attempts = 0
    chrome_downloader = (
        ChromeDownloader(
            args.downloads,
            page_wait=args.espera_chrome,
            download_timeout=args.timeout,
        )
        if chrome_enabled
        else None
    )
    if chrome_downloader:
        atexit.register(chrome_downloader.close)
    abort_after_row = False

    for index, record_url in enumerate(record_urls, start=1):
        now = utc_now()
        try:
            html, status, _ = client.read(record_url)
            edicao = parse_record(record_url, html)
            year_dir = pdf_root / edicao.ano
            final_path = year_dir / edicao.arquivo
            existing = find_existing(edicao, final_path, legacy_root)

            if existing:
                result = ManifestRow(
                    **asdict(edicao),
                    caminho_local=str(existing.relative_to(root)),
                    status="EXISTENTE",
                    http_status=str(status),
                    tamanho_bytes=str(existing.stat().st_size),
                    verificado_em_utc=now,
                )
                print(f"[{index}/{len(record_urls)}] EXISTE: {existing}")
            elif not download_enabled:
                result = ManifestRow(
                    **asdict(edicao),
                    caminho_local=str(final_path.relative_to(root)),
                    status="SIMULADO",
                    http_status=str(status),
                    verificado_em_utc=now,
                )
                print(
                    f"[{index}/{len(record_urls)}] SIMULAR: "
                    f"{edicao.ano}/{edicao.arquivo}"
                )
            else:
                year_dir.mkdir(parents=True, exist_ok=True)
                download_attempts += 1
                if chrome_downloader:
                    received_path = chrome_downloader.download(edicao)
                    tamanho = received_path.stat().st_size
                    digest = _sha256_file(received_path)
                    pdf_status = status
                    published, source_removed = _import_download_no_clobber(
                        received_path,
                        final_path,
                    )
                    downloaded_status = (
                        "BAIXADO_CHROME"
                        if source_removed
                        else "COPIADO_CHROME"
                    )
                else:
                    temporary = year_dir / f".{edicao.arquivo}.part"
                    temporary.unlink(missing_ok=True)
                    pdf_status, tamanho, digest = client.download_pdf(
                        record_url=record_url,
                        pdf_url=edicao.pdf_url,
                        temporary_path=temporary,
                    )
                    published = _publish_no_clobber(temporary, final_path)
                    downloaded_status = "BAIXADO"
                if published:
                    status_text = downloaded_status
                    print(
                        f"[{index}/{len(record_urls)}] {status_text}: "
                        f"{final_path} ({tamanho} bytes)"
                    )
                else:
                    status_text = "EXISTENTE"
                    tamanho = final_path.stat().st_size
                    digest = ""
                    print(f"[{index}/{len(record_urls)}] EXISTE: {final_path}")
                result = ManifestRow(
                    **asdict(edicao),
                    caminho_local=str(final_path.relative_to(root)),
                    status=status_text,
                    http_status=str(pdf_status),
                    tamanho_bytes=str(tamanho),
                    sha256=digest,
                    verificado_em_utc=now,
                )
        except Exception as exc:
            print(f"[{index}/{len(record_urls)}] ERRO: {record_url}: {exc}")
            if chrome_enabled:
                abort_after_row = True
            result = ManifestRow(
                record_url=record_url,
                pdf_url="",
                titulo="",
                ano="",
                arquivo="",
                caminho_local="",
                status="ERRO",
                erro=str(exc),
                verificado_em_utc=now,
            )

        rows[record_url] = {key: str(value) for key, value in asdict(result).items()}
        ordered_rows = sorted(
            rows.values(),
            key=lambda row: (
                row.get("ano", ""),
                row.get("titulo", ""),
                row.get("record_url", ""),
            ),
        )
        write_manifest(manifest_path, ordered_rows)

        if abort_after_row:
            print(
                "Execução via Chrome interrompida após o primeiro erro; "
                "nenhuma outra edição será aberta."
            )
            break

        if index < len(record_urls):
            if download_enabled and result.status in (
                "BAIXADO",
                "BAIXADO_CHROME",
                "COPIADO_CHROME",
            ):
                time.sleep(max(0.0, args.intervalo))
            else:
                time.sleep(max(0.0, args.intervalo_consulta))

    if chrome_downloader:
        chrome_downloader.close()
        atexit.unregister(chrome_downloader.close)

    print(f"Manifesto: {manifest_path}")
    if download_enabled:
        print(f"Downloads tentados nesta execução: {download_attempts}")
    else:
        print("Nenhum PDF foi baixado. Use --baixar para autorizar downloads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
