"""Snapshot privado e verificável. Não acessa API, Chaves nem altera originais."""
import argparse
import hashlib
import io
import json
import os
import pathlib
import platform
import stat
import subprocess
import tarfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP = {'.git', '__pycache__', '.pytest_cache', '.venv', 'migracao-privada'}


def digest(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(block)
    return h.hexdigest()


def sha(path):
    with path.open('rb') as stream:
        return digest(stream)


def criar_tar(destino, fontes):
    """Inclui todos os arquivos de dados; não segue links para fora das fontes."""
    registros = []
    with tarfile.open(destino, 'w:gz', compresslevel=3, dereference=True) as tar:
        for label, source in fontes.items():
            for folder, dirs, files in os.walk(source, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in SKIP)
                for name in list(dirs):
                    path = pathlib.Path(folder) / name
                    if path.is_symlink():
                        rel = pathlib.PurePosixPath(label) / path.relative_to(source).as_posix()
                        registros.append({'arquivo': str(rel), 'link_na_origem': os.readlink(path), 'incluido': False})
                        dirs.remove(name)
                for name in sorted(files):
                    path = pathlib.Path(folder) / name
                    rel = pathlib.PurePosixPath(label) / path.relative_to(source).as_posix()
                    if path.is_symlink():
                        registros.append({'arquivo': str(rel), 'link_na_origem': os.readlink(path),
                                          'incluido': False})
                        continue
                    before = path.stat()
                    if not stat.S_ISREG(before.st_mode):
                        continue
                    h = sha(path)
                    tar.add(path, arcname=str(rel), recursive=False)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise RuntimeError('Arquivo mudou durante o backup: ' + str(path))
                    registros.append({'arquivo': str(rel), 'bytes': before.st_size,
                                      'sha256': h, 'incluido': True})
                    if len(registros) % 250 == 0:
                        print(f'Preservados {len(registros)} arquivos...', flush=True)
                if not dirs and not files:
                    rel = pathlib.PurePosixPath(label) / pathlib.Path(folder).relative_to(source).as_posix()
                    tar.add(folder, arcname=str(rel), recursive=False)
                    registros.append({'arquivo': str(rel), 'tipo': 'pasta', 'incluido': True})
    os.chmod(destino, 0o600)
    return registros


def verificar_tar(path, registros):
    esperados = {r['arquivo']: r for r in registros if r.get('incluido')}
    vistos = set()
    with tarfile.open(path, 'r:gz') as tar:
        for member in tar:
            parts = pathlib.PurePosixPath(member.name)
            if parts.is_absolute() or '..' in parts.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Membro inseguro ou inesperado: ' + member.name)
            if member.name not in esperados or member.name in vistos:
                raise ValueError('Membro ausente do manifesto ou repetido: ' + member.name)
            if esperados[member.name].get('tipo') == 'pasta':
                if not member.isdir():
                    raise ValueError('Pasta divergente: ' + member.name)
                vistos.add(member.name)
                continue
            with tar.extractfile(member) as stream:
                h = digest(stream)
            record = esperados[member.name]
            if h != record['sha256'] or member.size != record['bytes']:
                raise ValueError('Conteúdo divergente: ' + member.name)
            vistos.add(member.name)
    if vistos != set(esperados):
        raise ValueError('Arquivos faltando no pacote')
    return len(vistos)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def exportar(destino, historico=None):
    destino = destino.expanduser().resolve()
    if destino.exists():
        raise ValueError('Escolha uma pasta nova; nenhum backup existente será sobrescrito')
    # Não incluir o pacote dentro da árvore que está sendo arquivada.
    if destino == ROOT or ROOT in destino.parents:
        raise ValueError('O destino privado precisa ficar fora do projeto')
    destino.mkdir(parents=True, mode=0o700)
    support = pathlib.Path.home() / 'Library/Application Support/Biblio Preparador/revista'
    fontes = {'projeto': ROOT}
    if support.is_dir():
        fontes['instalacao-ativa'] = support
    manifest = {'formato': 1, 'concluido': False, 'criado_em': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'sistema': platform.platform(), 'arquitetura': platform.machine(),
                'fontes': {k: str(v) for k, v in fontes.items()},
                'observacoes': ['Pacote privado: não publicar no GitHub.',
                                'Não inclui senhas do Chaves, contas de IA, ambientes virtuais ou originais externos referenciados por links.',
                                'Links externos são registrados, mas não seguidos. Não apagar a máquina antiga antes de conferir a restauração.',
                                'Encerrar app/OCR antes do snapshot; não processar enquanto ele estiver sendo criado.']}
    (destino / 'MANIFESTO.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    (destino / 'staging-anterior.patch').write_bytes(git('diff', '--cached', '--binary'))
    (destino / 'NOTA-SNAPSHOT.txt').write_text('O arquivo compactado preserva literalmente os arquivos de trabalho. O patch é somente o staging anterior; não aplicar automaticamente.\n')
    manifest['git_status_anterior'] = git('status', '--short').decode()
    manifest['branches'] = git('for-each-ref', '--format=%(refname:short) %(objectname)', 'refs/heads').decode()
    bundle = destino / 'historico-git.bundle'
    repo = pathlib.Path(historico).resolve() if historico else ROOT
    if repo != ROOT:
        for branch in ['codex/app-mac-biblio', 'desenvolvimento-biblio']:
            original = git('rev-parse', 'refs/heads/' + branch).strip()
            copia = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'refs/heads/' + branch]).strip()
            if original != copia:
                raise ValueError('Clone histórico divergente: ' + branch)
    subprocess.run(['git', '-C', str(repo), 'bundle', 'create', str(bundle), '--all'], check=True)
    subprocess.run(['git', '-C', str(repo), 'bundle', 'verify', str(bundle)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Preservando projeto, dados e instalação ativa...', flush=True)
    archive = destino / 'dados-privados.tar.gz'
    manifest['arquivos'] = criar_tar(archive, fontes)
    print('Conferindo conteúdo integral do pacote...', flush=True)
    manifest['arquivos_verificados'] = verificar_tar(archive, manifest['arquivos'])
    manifest['sha256_pacote'] = sha(archive)
    manifest['sha256_bundle'] = sha(bundle)
    manifest['concluido'] = True
    path = destino / 'MANIFESTO.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    for file in destino.iterdir():
        os.chmod(file, 0o600)
    print(json.dumps({'destino': str(destino), 'arquivos_conferidos': manifest['arquivos_verificados'],
                      'bytes_pacote': archive.stat().st_size, 'sha256': manifest['sha256_pacote']}, ensure_ascii=False), flush=True)


def verificar(destino):
    manifest = json.loads((destino / 'MANIFESTO.json').read_text())
    if not manifest.get('concluido'):
        raise ValueError('Snapshot incompleto')
    if sha(destino / 'dados-privados.tar.gz') != manifest['sha256_pacote']:
        raise ValueError('Pacote alterado ou incompleto')
    if sha(destino / 'historico-git.bundle') != manifest['sha256_bundle']:
        raise ValueError('Bundle alterado ou incompleto')
    n = verificar_tar(destino / 'dados-privados.tar.gz', manifest['arquivos'])
    print(f'Pacote íntegro: {n} arquivos conferidos.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('acao', choices=['criar', 'verificar'])
    p.add_argument('destino', type=pathlib.Path)
    p.add_argument('--historico', type=pathlib.Path, help='clone independente com as mesmas branches; opcional')
    args = p.parse_args()
    if args.acao == 'criar':
        exportar(args.destino, args.historico)
    else:
        verificar(args.destino.expanduser().resolve())
