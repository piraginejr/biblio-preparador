#!/usr/bin/env python3
"""Consulta leve e independente: sem OCR, preparo, upload ou alteração do catálogo."""
import argparse
import csv
import datetime
import importlib.util
import json
import pathlib
import re
import subprocess
import xml.etree.ElementTree as ET

BASE = pathlib.Path(__file__).resolve().parent


def carregar(nome, arquivo):
    spec = importlib.util.spec_from_file_location(nome, BASE / arquivo)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


api = carregar('consulta_api', 'enviar-livro-api.py')
prep = carregar('consulta_prep', 'preparar-livros.py')


def identificar(arquivo):
    """Lê OPF ou texto das primeiras 12 páginas; jamais renderiza/OCR."""
    titulo, autores, texto = '', [], ''
    fonte = 'nome do arquivo (não confirmado)'
    if arquivo.suffix.lower() == '.opf':
        root = ET.parse(arquivo).getroot()
        valores = lambda tag: [' '.join(x.itertext()).strip() for x in root.iter()
                               if x.tag.split('}')[-1] == tag]
        titulo = next(iter(valores('title')), '')
        autores = valores('creator')
        texto = '\n'.join(valores('identifier'))
        fonte = 'OPF'
    elif arquivo.suffix.lower() == '.pdf':
        r = subprocess.run(['pdftotext', '-f', '1', '-l', '12', str(arquivo), '-'],
                           capture_output=True, text=True, timeout=30)
        if r.returncode:
            raise RuntimeError('não foi possível ler o texto do PDF sem OCR')
        texto = r.stdout
        pista, autor_nome = prep.do_nome(arquivo.name)
        titulo_lido, pagina, origem = prep.titulo_nas_paginas_iniciais(
            texto.split('\f'), pistas=[pista], autor=autor_nome)
        if titulo_lido:
            titulo = titulo_lido
            fonte = f'texto do PDF, página {pagina}: {origem}'
        else:
            titulo = pista
        if autor_nome:
            autores = [autor_nome]
        # PDF Info Title não é prova de título bibliográfico; o nome é só pista.
        autor = re.search(r'(?im)^\s*(?:autor(?:a)?|by)\s*:?\s+([^\n]{4,100})$', texto)
        if autor:
            autores = [autor.group(1).strip()]
    titulo = titulo or re.sub(r'[_]+', ' ', arquivo.stem).strip()
    isbns = list(dict.fromkeys(x['isbn'] for x in prep.candidatos_isbn(texto)))
    return {'titulo': titulo, 'autores': autores, 'isbns': isbns, 'fonte': fonte}


def consultar(arquivo, sessao, chave):
    dados = identificar(arquivo)
    respostas = []
    for isbn in dados['isbns']:
        resposta = api.consultar_livro(sessao, chave, isbn=isbn, exato=True)
        respostas.append(resposta)
    exatas = [r for r in respostas if api.consulta_confirmada_por_isbn(r)]
    if len(dados['isbns']) == 1 and exatas and int(exatas[0].get('total_matches', 1)) == 1:
        estado = 'já existente por ISBN'
    else:
        if not any(r.get('encontrado') for r in respostas) and dados['titulo']:
            respostas.append(api.consultar_livro(sessao, chave, titulo=dados['titulo'],
                                                autores=dados['autores'], exato=True))
        encontrado = any(r.get('encontrado') for r in respostas)
        estado = ('precisa conferir' if encontrado or not dados['isbns'] else
                  'não localizado')
    return {**dados, 'resultado': estado, 'respostas': respostas,
            'observacao': ('Título/autor e edição exigem conferência; ausência de resultado não prova ausência no acervo.'
                           if estado != 'já existente por ISBN' else
                           'ISBN encontrado; nenhum arquivo foi alterado ou enviado.')}


def executar(entrada, saida, sessao=None, chave=None):
    chave = chave or api.ler_chave_chaves()
    if not chave:
        raise RuntimeError('Configure a chave do Biblio antes de consultar.')
    arquivos = sorted(p for p in entrada.rglob('*') if p.is_file() and p.suffix.lower() in {'.pdf', '.opf'})
    # Não presumir que OPF e todos os PDFs de uma pasta sejam o mesmo livro.
    itens = []
    with (sessao or api.criar_sessao_api()) as s:
        for n, arquivo in enumerate(arquivos, 1):
            print(f'[{n}/{len(arquivos)}] Consultando {arquivo.name} — sem preparo', flush=True)
            try:
                item = consultar(arquivo, s, chave)
            except Exception as exc:
                item = {'resultado': 'precisa conferir', 'observacao': str(exc)}
            item['arquivo'] = str(arquivo.relative_to(entrada))
            itens.append(item)
            print('  ' + item['resultado'], flush=True)
    saida.mkdir(parents=True, exist_ok=True)
    destino = saida / ('consulta-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    destino.with_suffix('.json').write_text(json.dumps(itens, ensure_ascii=False, indent=2), encoding='utf-8')
    with destino.with_suffix('.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['arquivo', 'titulo', 'resultado', 'observacao'], extrasaction='ignore')
        w.writeheader(); w.writerows(itens)
    print(f'Consulta concluída: {len(itens)} material(is). Relatório: {destino.with_suffix(".csv")}', flush=True)
    print('Nenhum OCR, cadastro, descarte ou alteração dos arquivos de origem foi realizado.', flush=True)
    return itens


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--entrada', type=pathlib.Path, required=True)
    ap.add_argument('--saida', type=pathlib.Path, required=True)
    args = ap.parse_args()
    executar(args.entrada, args.saida)
