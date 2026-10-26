"""Importação limitada de documentos ZIP/RAR, sem executar seu conteúdo."""
import ctypes
import ctypes.util
import hashlib
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import time

PERMITIDOS = {'.pdf', '.doc', '.docx', '.rtf', '.txt', '.odt', '.fodt',
              '.epub', '.mobi', '.azw3', '.fb2', '.html', '.htm',
              '.ppt', '.pptx', '.odp', '.opf', '.jpg', '.jpeg', '.png'}


def caminho_seguro(nome):
    nome = nome.replace('\\', '/')
    partes = pathlib.PurePosixPath(nome).parts
    if (not partes or nome.startswith('/') or ':' in nome
            or '..' in partes or any(ord(c) < 32 for c in nome)):
        raise ValueError('caminho inseguro no compactado')
    return pathlib.Path(*partes)


def extrair(origem, destino, max_arquivos=5000,
            max_total=2 * 1024**3, max_item=250 * 1024**2, segundos=100):
    """Libarchive lê RAR/ZIP em blocos; nunca usamos extractall/shell."""
    lib = ctypes.CDLL(ctypes.util.find_library('archive') or 'libarchive.dylib')
    ptr = ctypes.c_void_p
    for nome, args, retorno in [
        ('archive_read_new', [], ptr),
        ('archive_read_support_filter_all', [ptr], ctypes.c_int),
        ('archive_read_support_format_all', [ptr], ctypes.c_int),
        ('archive_read_open_filename', [ptr, ctypes.c_char_p, ctypes.c_size_t], ctypes.c_int),
        ('archive_read_next_header', [ptr, ctypes.POINTER(ptr)], ctypes.c_int),
        ('archive_entry_pathname', [ptr], ctypes.c_char_p),
        ('archive_entry_filetype', [ptr], ctypes.c_uint),
        ('archive_entry_size', [ptr], ctypes.c_longlong),
        ('archive_entry_symlink', [ptr], ctypes.c_char_p),
        ('archive_entry_hardlink', [ptr], ctypes.c_char_p),
        ('archive_read_data', [ptr, ptr, ctypes.c_size_t], ctypes.c_ssize_t),
        ('archive_read_free', [ptr], ctypes.c_int),
        ('archive_error_string', [ptr], ctypes.c_char_p),
    ]:
        func = getattr(lib, nome)
        func.argtypes, func.restype = args, retorno
    destino = pathlib.Path(destino)
    destino.mkdir(parents=True, exist_ok=False)
    arquivo = lib.archive_read_new()
    inicio, total = time.monotonic(), 0
    resultado = {'extraidos': [], 'ignorados': [], 'ok': False}
    def erro():
        return (lib.archive_error_string(arquivo) or b'compactado ilegivel').decode('utf8', 'replace')
    try:
        lib.archive_read_support_filter_all(arquivo)
        lib.archive_read_support_format_all(arquivo)
        if lib.archive_read_open_filename(arquivo, os.fsencode(origem), 65536) != 0:
            raise ValueError(erro())
        entrada, buffer = ptr(), ctypes.create_string_buffer(65536)
        for indice in range(max_arquivos + 1):
            codigo = lib.archive_read_next_header(arquivo, ctypes.byref(entrada))
            if codigo == 1:  # ARCHIVE_EOF
                resultado['ok'] = True
                break
            if codigo != 0:
                raise ValueError(erro())
            if indice == max_arquivos or time.monotonic() - inicio > segundos:
                raise ValueError('limite de quantidade/tempo excedido')
            nome = (lib.archive_entry_pathname(entrada) or b'').decode('utf8', 'replace')
            relativo = caminho_seguro(nome)
            tipo = lib.archive_entry_filetype(entrada)
            if tipo == stat.S_IFDIR:
                continue
            if (tipo != stat.S_IFREG or lib.archive_entry_symlink(entrada)
                    or lib.archive_entry_hardlink(entrada)):
                raise ValueError('link ou arquivo especial bloqueado: ' + nome)
            if relativo.suffix.lower() not in PERMITIDOS:
                resultado['ignorados'].append(nome)
                continue
            tamanho = lib.archive_entry_size(entrada)
            if tamanho < 0 or tamanho > max_item or total + tamanho > max_total:
                raise ValueError('limite de tamanho excedido: ' + nome)
            alvo = destino / relativo
            alvo.parent.mkdir(parents=True, exist_ok=True)
            # Destino novo, sem links, e criação exclusiva: nada é sobrescrito.
            with alvo.open('xb') as saida:
                escritos = 0
                while True:
                    n = lib.archive_read_data(arquivo, buffer, len(buffer))
                    if n < 0:
                        raise ValueError(erro())
                    if n == 0:
                        break
                    escritos += n
                    total += n
                    if (escritos > max_item or total > max_total
                            or time.monotonic() - inicio > segundos):
                        raise ValueError('limite de extração excedido')
                    saida.write(buffer.raw[:n])
            resultado['extraidos'].append(str(relativo))
        resultado['bytes'] = total
        return resultado
    finally:
        lib.archive_read_free(arquivo)


def preparar(entrada, controle):
    """Cada hash é importado uma vez; falhas ficam isoladas fora da entrada."""
    entrada, controle = pathlib.Path(entrada), pathlib.Path(controle)
    manifesto = controle / 'importacoes-compactados.json'
    dados = json.loads(manifesto.read_text()) if manifesto.exists() else {'itens': {}}
    arquivos = sorted(p for p in entrada.rglob('*')
                      if p.suffix.lower() in {'.zip', '.rar'}
                      and p.is_file() and not p.is_symlink()
                      and '_descompactados' not in p.relative_to(entrada).parts)
    for origem in arquivos:
        h = hashlib.sha256()
        with origem.open('rb') as f:
            for bloco in iter(lambda: f.read(1024 * 1024), b''):
                h.update(bloco)
        digest = h.hexdigest()
        if digest in dados['itens']:
            continue
        nome = re.sub(r'[^\w.-]', '_', origem.stem)[:90] + '-' + digest[:12]
        temporario = controle / 'compactados-isolados' / nome
        temporario.parent.mkdir(parents=True, exist_ok=True)
        print('  Lendo compactado: ' + origem.name, flush=True)
        try:
            proc = subprocess.run(
                [sys.executable, str(pathlib.Path(__file__).resolve()),
                 str(origem), str(temporario)], capture_output=True,
                text=True, timeout=120, check=True)
            resultado = json.loads(proc.stdout)
            destino = entrada / '_descompactados' / nome
            destino.parent.mkdir(exist_ok=True)
            temporario.rename(destino)
            resultado['destino'] = str(destino)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            detalhe = str(exc)
            if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                detalhe = exc.stderr.strip().splitlines()[-1][:1000]
            resultado = {'ok': False, 'erro': detalhe,
                         'nota': 'original preservado; conteúdo isolado, não processado'}
        resultado['origem'] = str(origem)
        dados['itens'][digest] = resultado
        temp = manifesto.with_suffix('.tmp')
        temp.write_text(json.dumps(dados, ensure_ascii=False, indent=2))
        temp.replace(manifesto)
        print('    ' + (str(len(resultado.get('extraidos', []))) + ' arquivo(s) recuperado(s)'
                        if resultado.get('ok') else 'aguardando revisão do compactado'), flush=True)
    return dados


if __name__ == '__main__':
    print(json.dumps(extrair(sys.argv[1], sys.argv[2]), ensure_ascii=False))
