"""Separa acessórios inequívocos; conteúdo desconhecido nunca é descartado."""
import hashlib
import json
import pathlib
import shutil
from datetime import datetime

GRUPOS = {
    'atalho de endereço ou programa; não contém a obra': {'.url', '.webloc', '.lnk'},
    'fonte tipográfica avulsa': {'.ttf', '.otf', '.woff', '.woff2', '.fon'},
    'instalador ou componente de programa': {'.exe', '.dll', '.msi', '.dmg', '.pkg', '.gid'},
}
FONTES = GRUPOS['fonte tipográfica avulsa']


def digest(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def motivo(p, entrada):
    p, entrada = pathlib.Path(p), pathlib.Path(entrada)
    if p.is_symlink() or not p.is_file():
        return ''
    # Recursos de páginas salvas podem conter fontes/atalhos necessários.
    for pasta in (p.parent, *p.parents):
        if pasta == entrada.parent:
            break
        if pasta.name.lower().endswith(('_files', '_arquivos', '_ficheiros', '.files')):
            return ''
        if p.suffix.lower() in FONTES and any(
                x.is_file() and x.suffix.lower() in {'.html', '.htm', '.xhtml', '.opf', '.epub'}
                for x in pasta.iterdir()):
            return ''
        if pasta == entrada:
            break
    return next((m for m, exts in GRUPOS.items() if p.suffix.lower() in exts), '')


def ler(c):
    p = c['controle'] / 'descarte-acessorios.json'
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else {'itens': []}


def salvar(c, dados):
    p = c['controle'] / 'descarte-acessorios.json'
    tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding='utf8')
    tmp.replace(p)


def organizar(c):
    dados = ler(c)
    movidos = []
    for p in sorted(c['entrada'].rglob('*')):
        razao = motivo(p, c['entrada'])
        if not razao:
            continue
        h = digest(p)
        pasta = c['descarte'] / 'ACESSORIOS' / h[:16]
        pasta.mkdir(parents=True, exist_ok=True)
        alvo = pasta / p.name
        if alvo.exists():
            # Não apagar nem sobrescrever mesmo uma cópia idêntica.
            indice = 1
            while alvo.exists():
                alvo = pasta / (str(indice) + '-' + p.name)
                indice += 1
        item = {'origem': str(p.relative_to(c['raiz'])),
                'arquivo': str(alvo.relative_to(c['raiz'])),
                'hash': h, 'bytes': p.stat().st_size, 'motivo': razao,
                'estado': 'aguardando descarte confirmado',
                'separado_em': datetime.now().isoformat(timespec='seconds')}
        # Registrar antes da movimentação torna uma interrupção recuperável.
        dados['itens'].append(item)
        salvar(c, dados)
        shutil.move(str(p), str(alvo))
        movidos.append(item)
    if movidos:
        print('Descarte separado: {} acessório(s); originais na pasta Descarte.'.format(len(movidos)), flush=True)
    return movidos


def para_limpeza(c):
    itens = []
    permitidas = {(c['descarte'] / 'ACESSORIOS').resolve(), c['entrada'].resolve()}
    for item in ler(c)['itens']:
        if item.get('estado') != 'aguardando descarte confirmado':
            continue
        for chave in ('arquivo', 'origem'):
            p = c['raiz'] / item[chave]
            if (not p.is_symlink() and p.is_file()
                    and any(r in p.resolve().parents for r in permitidas)
                    and digest(p) == item['hash']):
                itens.append(dict(item, arquivo=str(p.relative_to(c['raiz']))))
                break
    return itens
