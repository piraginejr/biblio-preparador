#!/usr/bin/env python3
"""Relatórios locais de substituições confirmadas e do piloto cego Apple."""
import argparse
import difflib
import html
import json
import pathlib
import re
import unicodedata


def normalizar(valor, campo):
    if isinstance(valor,list):
        valor = '; '.join(str(x) for x in valor)
    valor = str(valor or '').strip()
    if valor in ('[s.n.]','[s.d.]'):
        return ''
    if campo == 'data':
        anos = set(re.findall(r'\b(?:18|19|20)\d{2}\b',valor))
        return next(iter(anos)) if len(anos)==1 else valor
    s = unicodedata.normalize('NFKD',valor.lower())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    palavras=re.findall(r'[a-z0-9]+',s)
    if campo=='nmAutor0':
        palavras=[p for p in palavras if p not in ('prof','dr','dra','professor')]
        return ' '.join(sorted(palavras))
    return ' '.join(palavras)


def igual(a,b,campo):
    a,b=normalizar(a,campo),normalizar(b,campo)
    return a==b


def documento(titulo,corpo):
    return '<!doctype html><meta charset="utf-8"><title>'+titulo+'</title>'+'''
    <style>body{font:16px system-ui;max-width:1300px;margin:35px auto;padding:20px;color:#243b30;background:#fffaf1}
    table{border-collapse:collapse;width:100%}th,td{border:1px solid #d9cbb8;padding:10px;text-align:left;vertical-align:top}
    th{background:#e5efe7}small{color:#666}.ok{color:#166534}.erro{color:#9f1239}h1{color:#1f4d3a}</style>'''+corpo


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raiz',type=pathlib.Path,required=True)
    args=ap.parse_args();pasta=args.raiz/'_controle'
    diario=json.loads((pasta/'correcoes-lote-20261025.json').read_text())
    linhas=[];novos=[];bloqueados=[];existentes=[]
    for x in diario['itens']:
        e=x.get('envio',{});antigo=x.get('id_antigo');novo=e.get('id_remoto')
        if e.get('estado')=='cadastrado' and novo:
            if antigo:
                linhas.append(f'<tr><td>{antigo}</td><td>{html.escape(str(x["antes"].get("titulo",x["arquivo"])))}</td>'
                    f'<td>{novo}</td><td>{html.escape(x["depois"].get("titulo",x["arquivo"]))}</td>'
                    f'<td>{html.escape(x["fonte"])}</td></tr>')
            else:
                novos.append({'id':novo,'arquivo':x['arquivo']})
        elif e.get('upload_evitado') and novo:
            existentes.append({'id':novo,'arquivo':x['arquivo'],'criterio':e['estado']})
        elif antigo or e:
            bloqueados.append({'id_antigo':antigo,'arquivo':x['arquivo'],
                               'motivo':x.get('motivo') or e})
    corpo='<h1>Cadastros corrigidos — 25/10/2026</h1><p>Somente os IDs antigos abaixo têm substituição confirmada por HTTP 201. Nenhum cadastro foi excluído por esta rotina. O gestor deve conferir os novos antes de excluir os antigos.</p>'
    corpo+='<table><tr><th>ID antigo: excluir após conferência</th><th>Ficha antiga</th><th>ID novo: manter</th><th>Título corrigido</th><th>Evidência da revisão</th></tr>'+''.join(linhas)+'</table>'
    corpo+='<h2>Cadastros recuperados sem substituição</h2><pre>'+html.escape(json.dumps(novos,ensure_ascii=False,indent=2))+'</pre>'
    corpo+='<h2>Pendências: não excluir automaticamente</h2><pre>'+html.escape(json.dumps(bloqueados,ensure_ascii=False,indent=2))+'</pre>'
    corpo+='<h2>Já existentes confirmados — upload evitado</h2><pre>'+html.escape(json.dumps(existentes,ensure_ascii=False,indent=2))+'</pre>'
    (pasta/'correcoes-para-gestor-20261025.html').write_text(documento('Correções Biblio',corpo),encoding='utf-8')
    resultados=[];soma_antes=soma_apple=0;falhas=0;segundos=0
    for path in sorted((pasta/'piloto-apple-20261025').glob('*.json')):
        d=json.loads(path.read_text())
        if 'ficha_original' not in d:
            continue
        ref=d['referencia_independente'];apple=d.get('apple',{})
        original=d['ficha_original'];valido=bool(apple and not apple.get('erro') and not d.get('erro'))
        autores=apple.get('autores') or []
        candidato={**apple,'nmAutor0':autores[0] if autores else ''}
        notas_antes=[];notas_apple=[]
        for campo in ('titulo','nmAutor0','editora','data'):
            notas_antes.append(igual(original.get(campo),ref.get(campo),campo))
            notas_apple.append(valido and igual(candidato.get(campo),ref.get(campo),campo))
        a,b=sum(notas_antes),sum(notas_apple);soma_antes+=a;soma_apple+=b
        falhas+=not valido;segundos+=d.get('tempo_total',0)
        resultados.append({'arquivo':d['arquivo'],'antes':a,'apple':b,'valido':valido,
                           'campos_antes':notas_antes,'campos_apple':notas_apple,
                           'referencia':ref,'resposta_apple':apple,'tempo':d.get('tempo_total')})
    total=len(resultados)*4
    resumo={'materiais':len(resultados),'campos_avaliados':total,
            'concordancia_motor_original':soma_antes,'concordancia_apple':soma_apple,
            'taxa_motor_original':round(soma_antes/max(1,total)*100,1),
            'taxa_apple':round(soma_apple/max(1,total)*100,1),
            'respostas_invalidas':falhas,'segundos':round(segundos,1),
            'criterio':'Concordância estrita com revisão independente em título, autor principal, editora e ano. Ausência correta também conta; acentos, caixa, ordem bibliográfica e precisão do ano são normalizados. Não é taxa de aprovação do aplicativo.'}
    (pasta/'piloto-apple-20261025/avaliacao.json').write_text(json.dumps({'resumo':resumo,'itens':resultados},ensure_ascii=False,indent=2),encoding='utf-8')
    corpo='<h1>Piloto cego — Apple Intelligence local</h1><pre>'+html.escape(json.dumps(resumo,ensure_ascii=False,indent=2))+'</pre>'
    corpo+='<p>O modelo recebeu texto das primeiras páginas, CIP e créditos finais, sem nomes de arquivo e sem as correções. Erros de contexto da primeira passagem foram preservados nos arquivos individuais. As respostas da IA não foram aplicadas ao catálogo.</p>'
    for r in resultados:
        corpo+='<h2>'+html.escape(r['arquivo'])+'</h2><p>Motor anterior: '+str(r['antes'])+'/4; Apple: '+str(r['apple'])+'/4; '+str(r['tempo'])+' s.</p><details><summary>Referência e resposta integral</summary><pre>'+html.escape(json.dumps({'referencia':r['referencia'],'apple':r['resposta_apple']},ensure_ascii=False,indent=2))+'</pre></details>'
    (pasta/'piloto-apple-20261025.html').write_text(documento('Piloto Apple',corpo),encoding='utf-8')
    print(json.dumps({'substituicoes':len(linhas),'recuperados':len(novos),'existentes':existentes,
                      'pendencias':bloqueados,'piloto':resumo},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
