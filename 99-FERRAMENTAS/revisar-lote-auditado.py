#!/usr/bin/env python3
"""Aplica revisão documentada, mede piloto independente e envia substituições.

As decisões desta execução ficam em arquivo separado das regras gerais.
Padrão: plano somente. --aplicar corrige localmente; --enviar faz uploads.
"""
import argparse
import importlib.util
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time


def carregar(nome):
    p = pathlib.Path(__file__).with_name(nome)
    s = importlib.util.spec_from_file_location(nome.replace('-', '_'), p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def salvar(p, d):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    tmp.replace(p)


def piloto(raiz, itens, binario):
    catalogo = json.loads((raiz/'_controle/catalogo-local.json').read_text())
    pasta = raiz/'_controle/piloto-apple-20261025'
    for item in itens:
        if not item.get('arquivo') or item.get('desfazer_duplicidade'):
            continue
        reg = next((r for r in catalogo['livros'].values()
                    if r['arquivo'] == item['arquivo']), None)
        if not reg:
            continue
        saida = pasta/(pathlib.Path(reg['metadados']).stem+'.json')
        anterior = json.loads(saida.read_text()) if saida.exists() else {}
        if anterior.get('entrada_versao') == 2 and not anterior.get('erro') and not anterior.get('apple', {}).get('erro'):
            continue
        ficha = json.loads((raiz/reg['metadados']).read_text())
        pdf = raiz/reg['caminho']
        txt = subprocess.run(['/opt/homebrew/bin/pdftotext', '-layout', str(pdf), '-'],
                             capture_output=True, text=True, timeout=60).stdout
        paginas = txt.split('\f')
        # Entrada cega: só texto das páginas, sem nome do arquivo nem correções.
        trechos=[]
        for i,t in enumerate(paginas[:10]):
            cip=re.search(r'(?i)\bCIP\b|ficha\s+catalog|dados\s+internacionais\s+de\s+catalog',t)
            if cip:
                inicio=max(0,cip.start()-100)
                trecho=t[inicio:inicio+1700]
            elif i<2:
                trecho=t[:1200]
            elif i<4:
                trecho=t[:300]
            else:
                continue
            trechos.append(f'PÁGINA {i+1}\n{trecho}')
        amostra='\n'.join(trechos)[:5000]
        if len(paginas)>7:
            amostra += '\nÚLTIMAS PÁGINAS\n'+'\n'.join(paginas[-3:])[-900:]
        entrada = {'paginas':amostra}
        pacote = {'arquivo':reg['arquivo'], 'entrada_versao':2, 'ficha_original':anterior.get('ficha_original',ficha),
                  'referencia_independente':item['campos'], 'entrada':entrada}
        if anterior:
            pacote['tentativa_anterior'] = {k:anterior.get(k) for k in ('apple','erro','tempo_total')}
        inicio = time.monotonic()
        print('PILOTO', reg['arquivo'], flush=True)
        try:
            res = subprocess.run([str(binario)], input=json.dumps(entrada),
                                 capture_output=True, text=True, timeout=100)
            pacote['apple'] = json.loads(res.stdout)
            if res.returncode:
                pacote['erro'] = res.stderr[-1500:]
        except Exception as exc:
            pacote['erro'] = str(exc)
        pacote['tempo_total'] = round(time.monotonic()-inicio,2)
        salvar(saida,pacote)
        print('  ',str(pacote.get('apple',pacote.get('erro')))[:400],flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raiz', type=pathlib.Path, required=True)
    ap.add_argument('--plano',type=pathlib.Path,required=True)
    ap.add_argument('--aplicar',action='store_true')
    ap.add_argument('--enviar',action='store_true')
    ap.add_argument('--piloto',type=pathlib.Path)
    ap.add_argument('--somente-cadastrados',action='store_true')
    ap.add_argument('--limite-envio',type=int,default=0)
    ap.add_argument('--reabrir-duplicado',default='')
    args=ap.parse_args()
    raiz=args.raiz.resolve()
    itens=json.loads(args.plano.read_text())['itens']
    if args.somente_cadastrados:
        itens=[item for item in itens if item.get('id')]
    if args.piloto:
        piloto(raiz,itens,args.piloto)
        return
    local=carregar('biblioteca-local.py')
    api=local.api_envio
    registro_path=raiz/'_controle/correcoes-lote-20261025.json'
    diario=json.loads(registro_path.read_text()) if registro_path.exists() else {'itens':[]}
    if not args.aplicar and not args.enviar and not args.reabrir_duplicado:
        print(json.dumps(itens,ensure_ascii=False,indent=2));return
    with local.trava_execucao(raiz,'revisão auditada e envio corrigido'):
        if args.reabrir_duplicado:
            item=next(x for x in diario['itens'] if x['arquivo']==args.reabrir_duplicado)
            if not item.get('envio',{}).get('upload_evitado'):
                raise RuntimeError('a decisão não é uma duplicidade prévia sem upload')
            c=local.inicializar(raiz);cat=local.carregar_catalogo(c)
            reg=next(x for x in cat['livros'].values() if x.get('metadados')==item['ficha'])
            reg['estado']='analisado'
            reg['duplicidade_invalidada']=item['envio']
            reg.pop('id_remoto',None)
            local.salvar_catalogo(c,cat)
            local.gravar_decisao_revisao(raiz,item['arquivo'],item['depois'],
                aprovado=True,fontes=[item['fonte']],
                justificativa='Parte distinta; consulta anterior comparou apenas o título principal',imprimir=False)
            item.setdefault('decisoes_anteriores',[]).append(item.pop('envio'))
            salvar(registro_path,diario)
            local.atualizar_filas_especificas(raiz)
        if args.aplicar:
            backup=raiz/'_controle/auditoria-20261025-original'
            if not backup.exists():
                shutil.copytree(raiz/'_metadados',backup/'metadados')
                for p in (raiz/'_controle').glob('*.json'):
                    shutil.copy2(p,backup/p.name)
            for item in itens:
                if any(x.get('chave')==(item.get('arquivo') or str(item.get('id')))
                       for x in diario['itens']):
                    continue
                c=local.inicializar(raiz);cat=local.carregar_catalogo(c)
                regs=[(h,r) for h,r in cat['livros'].items()
                      if (r['arquivo']==item.get('arquivo') if item.get('arquivo') else
                          r.get('id_remoto')==item.get('id') and r['estado']=='cadastrado')]
                if len(regs)!=1:
                    raise RuntimeError(f'Identificação não única: {item}')
                digest,reg=regs[0]; arquivo=reg['arquivo']
                original=json.loads((raiz/reg['metadados']).read_text())
                if not local._arquivo_do_registro(c,reg):
                    corrigida={**original,**item['campos'],
                               'correcao_remota_pendente':True,
                               'situacao':'cadastrado'}
                    salvar(raiz/reg['metadados'],corrigida)
                    diario['itens'].append({'chave':item.get('arquivo') or str(item.get('id')),
                        'arquivo':arquivo,'ficha':reg['metadados'],'id_antigo':item.get('id'),
                        'fonte':item['fonte'],'antes':{k:original.get(k) for k in item['campos']},
                        'depois':item['campos'],'aprovado':False,
                        'motivo':'PDF local já liberado; correção no servidor depende do gestor'})
                    salvar(registro_path,diario)
                    print('SEM PDF LOCAL; FICHA CORRIGIDA',arquivo,flush=True)
                    continue
                if item.get('desfazer_duplicidade'):
                    reg['duplicidade_invalidada']={k:reg.get(k) for k in
                        ('estado','id_remoto','confirmado_por_api','correspondencia_api')}
                    reg['estado']='conflito'
                    for k in ('id_remoto','confirmado_por_api','correspondencia_api'):
                        reg.pop(k,None)
                    local.salvar_catalogo(c,cat)
                campos=dict(item['campos'])
                if 'nmAutor0' in campos and 'autores' not in campos:
                    campos['autores']=([{'nome':campos['nmAutor0'],'desc':'Autor'}]
                                       if campos['nmAutor0'] else [])
                for k in ('abstract','pchave','palavrasChave'):
                    campos.setdefault(k,'')
                campos['isbn_confirmado_na_edicao']=bool(campos.get('isbn') or original.get('isbn'))
                local.gravar_decisao_revisao(raiz,arquivo,campos,
                    aprovado=item.get('aprovar',True),fontes=[item['fonte']],
                    justificativa='Auditoria do lote 25/10/2026: '+item['fonte'],imprimir=False)
                diario['itens'].append({'chave':item.get('arquivo') or str(item.get('id')),
                    'arquivo':arquivo,'ficha':reg['metadados'],'id_antigo':item.get('id'),
                    'fonte':item['fonte'],'antes':{k:original.get(k) for k in campos},
                    'depois':campos,'aprovado':item.get('aprovar',True)})
                salvar(registro_path,diario)
                print('CORRIGIDO',arquivo,flush=True)
            api.atualizar_fila(raiz)
            local.atualizar_filas_especificas(raiz)
        if args.enviar:
            chave=api.ler_chave_chaves()
            if not chave:raise RuntimeError('chave ausente no Chaves')
            sessao=api.criar_sessao_api()
            tentados=0
            for item in diario['itens']:
                if not item.get('aprovado') or item.get('envio'):
                    continue
                if args.limite_envio and tentados>=args.limite_envio:
                    break
                tentados+=1
                ficha_path=raiz/item['ficha']
                ficha=json.loads(ficha_path.read_text())
                tipo=local.tipo_api_para_documento(ficha) if hasattr(local,'tipo_api_para_documento') else None
                if not tipo:
                    t=ficha.get('tipo_documento','livro')
                    tipo='livro' if t=='livro' else 'artigo de revista' if t=='artigo' else 'documento'
                # Validação da substituição usa a ficha pronta, mas mantém o
                # catálogo marcado como cadastrado até a confirmação do novo ID.
                if item.get('id_antigo'):
                    ficha['situacao']='pronto para cadastro' if tipo=='livro' else 'pronto para cadastro específico'
                    salvar(ficha_path,ficha)
                print('ENVIANDO',item['arquivo'], 'substitui',item.get('id_antigo'),flush=True)
                try:
                    if not item.get('id_antigo'):
                        consulta=api.consultar_livro(sessao,chave,
                            isbn=ficha.get('isbn',''),titulo=api.titulo_para_consulta(ficha),
                            autores=api.autores_para_consulta(ficha),exato=True)
                        item['consulta_previa']=consulta
                        mesmo=(api.consulta_confirmada_por_isbn(consulta) or
                               api.consulta_confirmada_por_titulo_autor(consulta) or
                               (not api.autores_para_consulta(ficha) and
                                api.consulta_corresponde_ao_titulo_exato(consulta)))
                        if mesmo and consulta.get('id') and not api.consulta_com_isbn_divergente(consulta):
                            c=local.inicializar(raiz);cat=local.carregar_catalogo(c)
                            estado=('duplicado confirmado por ISBN' if
                                    api.consulta_confirmada_por_isbn(consulta) else
                                    api.ESTADO_DUPLICADO_TITULO_AUTOR if api.autores_para_consulta(ficha) else
                                    api.ESTADO_DUPLICADO_TITULO)
                            ficha.update(situacao=estado,situacao_metadados=estado,
                                         id_remoto=consulta['id'],consulta_previa_api=consulta)
                            salvar(ficha_path,ficha)
                            for reg in cat['livros'].values():
                                if reg.get('metadados')==item['ficha']:
                                    reg.update(estado=estado,id_remoto=consulta['id'])
                            local.salvar_catalogo(c,cat)
                            item['envio']={'estado':estado,'id_remoto':consulta['id'],
                                           'upload_evitado':True}
                            salvar(registro_path,diario)
                            print('  JÁ EXISTENTE',consulta['id'],flush=True)
                            continue
                    resultado=api.enviar(ficha_path,realmente=True,chave=chave,
                        sessao=sessao,tipo_api=tipo,substituir_id=item.get('id_antigo'))
                    item['envio']={k:resultado.get(k) for k in
                        ('estado','id_remoto','http_status','resposta','substitui_id')}
                    if resultado.get('estado')=='cadastrado':
                        ficha['id_remoto']=resultado['id_remoto']
                        ficha['correcao_remota_pendente']=False
                        salvar(ficha_path,ficha)
                        c=local.inicializar(raiz);cat=local.carregar_catalogo(c)
                        for reg in cat['livros'].values():
                            if reg.get('metadados')==item['ficha']:
                                reg.update(estado='cadastrado',id_remoto=resultado['id_remoto'],
                                           cadastrado_em=resultado.get('concluido_em',local.agora()))
                        local.salvar_catalogo(c,cat)
                    print('  ',item['envio'],flush=True)
                except Exception as exc:
                    item['envio']={'estado':'verificar antes de repetir','erro':str(exc)}
                    print('  FALHA',str(exc),flush=True)
                salvar(registro_path,diario)
                time.sleep(3)
            api.atualizar_fila(raiz)
            local.atualizar_filas_especificas(raiz)


if __name__=='__main__':
    main()
