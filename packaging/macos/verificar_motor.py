#!/usr/bin/env python3
"""Gera/compara a versão dos fontes, do pacote e da instalação ativa."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

MEMORIAS = {'titulos-ruidosos-conhecidos.json', 'autores-ruidosos-conhecidos.json',
            'editoras-cidades.json', 'periodicos-conhecidos.json', 'autores-conhecidos.json'}


def inventario(pasta):
    return {str(p.relative_to(pasta)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(pasta.rglob('*')) if p.is_file()
            and p.suffix in {'.py', '.json', '.swift', '.sh', '.command'}
            and '__pycache__' not in p.parts
            and p.name != 'versao-motor.json' and p.name not in MEMORIAS}


def instalar(origem, destino):
    """Atualização pontual: não remove caches/binários nem acervo."""
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = set(inventario(origem)) | {'versao-motor.json'} | MEMORIAS
    for rel in sorted(arquivos):
        src, dst = origem / rel, destino / rel
        if not src.is_file():
            continue
        dados = src.read_bytes()
        if rel in MEMORIAS and dst.is_file():
            novo, anterior = json.loads(dados), json.loads(dst.read_text(encoding='utf-8'))
            for chave in ('itens', 'autores', 'editoras', 'periodicos'):
                if not isinstance(anterior.get(chave), list):
                    continue
                lista = novo.setdefault(chave, [])
                vistos = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in lista}
                for x in anterior[chave]:
                    valor = json.dumps(x, sort_keys=True, ensure_ascii=False)
                    if valor not in vistos:
                        lista.append(x)
                        vistos.add(valor)
            dados = (json.dumps(novo, ensure_ascii=False, indent=2) + '\n').encode()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and dst.read_bytes() == dados:
            continue
        fd, temporario = tempfile.mkstemp(dir=dst.parent, prefix='.atualizando-')
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(dados)
            shutil.copymode(src, temporario)
            os.replace(temporario, dst)
        finally:
            if os.path.exists(temporario):
                os.unlink(temporario)


def versao(arquivos):
    return hashlib.sha256(json.dumps(arquivos, sort_keys=True).encode()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('ferramentas', type=Path)
    ap.add_argument('--gerar', action='store_true')
    ap.add_argument('--comparar', type=Path)
    ap.add_argument('--instalar', type=Path,
                    help='instala arquivos pontualmente, preservando memórias e binários locais')
    args = ap.parse_args()
    arquivos = inventario(args.ferramentas)
    dados = {'versao': versao(arquivos), 'arquivos': arquivos}
    if args.instalar:
        instalar(args.ferramentas, args.instalar)
        if inventario(args.instalar) != arquivos:
            raise SystemExit('A instalação ainda possui fontes divergentes; confira antes de abrir.')
    if args.gerar:
        (args.ferramentas/'versao-motor.json').write_text(
            json.dumps(dados, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if args.comparar:
        outro = inventario(args.comparar)
        divergentes = [k for k in sorted(set(arquivos)|set(outro))
                       if arquivos.get(k) != outro.get(k)]
        print(json.dumps({'iguais': not divergentes, 'divergentes': divergentes}, ensure_ascii=False))
        raise SystemExit(bool(divergentes))
    print(dados['versao'])


if __name__ == '__main__':
    main()
