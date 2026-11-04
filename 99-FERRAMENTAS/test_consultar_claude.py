import ast
import copy
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import consultar_claude as ia


def resposta():
    r = {c: None for c in ia.provas.CAMPOS}
    r.update(titulo='O Caminho da Fé', nmAutor0='Maria Silva', editora='Vida', data='2002',
             autores=[{'nome': 'Maria Silva', 'papel': 'Autor'}], tipo_documento='livro',
             observacoes=[], evidencias=[
                 {'campo': 'titulo', 'pagina': 1, 'trecho': 'O Caminho da Fé'},
                 {'campo': 'nmAutor0', 'pagina': 1, 'trecho': 'Autor: Maria Silva'},
                 {'campo': 'editora', 'pagina': 1, 'trecho': 'Editora Vida, 2002'},
                 {'campo': 'data', 'pagina': 1, 'trecho': 'Editora Vida, 2002'}])
    return r


class ClaudeTest(unittest.TestCase):
    def setUp(self):
        self.paginas = ['O Caminho da Fé\nAutor: Maria Silva\nEditora Vida, 2002']
        self.fontes = {'catálogo': {'titulo': 'O Caminho da Fé', 'autores': ['Silva, Maria'],
                                    'editora': 'Vida', 'ano': '2002'}}
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = pathlib.Path(self.tmp.name)
        self.pdf = self.p / 'livro.pdf'
        self.pdf.write_bytes(b'pdf simulado para hash')
        self.patch = mock.patch.object(ia, 'pasta_config', return_value=self.p / 'config')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        ia._suspenso_ate = 0

    def envelope(self, r=None, **outros):
        return json.dumps(dict(status='SUCCESS', structured_output=r or resposta(), **outros))

    def analisar(self, r=None):
        with mock.patch.object(ia, 'status', return_value={'ativo': True}), \
             mock.patch.object(ia, 'binario', return_value='/bin/agy'), \
             mock.patch.object(ia, 'executar', return_value=r or resposta()) as rodar, \
             mock.patch.object(ia.shutil, 'which', return_value=None):
            dados = ia.analisar(self.pdf, self.paginas, self.fontes)
        return dados, rodar

    def test_opt_in_desligado_sem_enviar(self):
        with mock.patch.object(ia, 'executar') as run:
            self.assertEqual('desativado', ia.analisar(self.pdf, self.paginas)['estado'])
        run.assert_not_called()

    def test_configuracao_nao_grava_chaves_ou_cache_no_projeto(self):
        with mock.patch.object(ia, 'binario', return_value='/bin/agy'):
            ia.configurar(True)
        cfg = self.p / 'config/config.json'
        self.assertEqual(0o600, cfg.stat().st_mode & 0o777)
        self.assertTrue(json.loads(cfg.read_text())['ativo'])
        self.assertNotIn('token', cfg.read_text())

    def test_nao_executa_app_grafico_como_cli(self):
        with mock.patch.dict(ia.os.environ, {'BIBLIO_ANTIGRAVITY_CLI': '/Applications/Antigravity.app/Contents/MacOS/Antigravity'}), \
             mock.patch.object(ia.pathlib.Path, 'is_file', return_value=True), \
             mock.patch.object(ia.os, 'access', return_value=True), \
             mock.patch.object(ia.shutil, 'which', return_value=None):
            self.assertNotIn('.app/', ia.binario())

    def test_timeout_com_success_nao_e_aceito(self):
        with self.assertRaises(ValueError):
            ia.validar_envelope(self.envelope(finished_reason='print_timeout'))
        with self.assertRaises(ValueError):
            ia.validar_envelope('{"status":"SUCCESS","response":""}')
        with self.assertRaises(ValueError):
            ia.validar_envelope(self.envelope(denied_actions=[{'action': 'read_file'}]))

    def test_campos_contrato_e_tipos_obrigatorios(self):
        for campo, valor in [('data', 2002), ('tipo_documento', 'qualquer coisa'),
                             ('autores', 'Maria'), ('observacoes', [{}])]:
            r = resposta(); r[campo] = valor
            with self.assertRaises(ValueError):
                ia.validar_envelope(self.envelope(r))
        self.assertEqual(resposta(), ia.validar_envelope(self.envelope()))

    def test_citacao_e_fonte_independente_aplicam(self):
        a, _ = self.analisar()
        self.assertEqual('revisão assistida', a['estado'])
        linha = {'conflitos': ['titulo so do nome do arquivo: arquivo', 'ISBN: divergente']}
        ia.aplicar_confirmadas(linha, a)
        self.assertEqual('O Caminho da Fé', linha['titulo'])
        self.assertTrue(linha['origem_titulo'].startswith('Claude +'))
        self.assertEqual(['ISBN: divergente'], linha['conflitos'])

    def test_fonte_primaria_explicita_aplica_sem_catalogo_externo(self):
        a, _ = self.analisar()
        for s in a['sugestoes']:
            s['fontes_confirmadoras'] = []
        linha = {'titulo': 'anterior'}
        self.assertTrue(ia.aplicar_confirmadas(linha, a))
        self.assertEqual('O Caminho da Fé', linha['titulo'])
        self.assertEqual('Maria Silva', linha['nmAutor0'])
        self.assertFalse(linha.get('revisao_manual_aprovada'))

    def test_sem_evidencia_primaria_nem_catalogo_nao_aplica(self):
        linha = {'titulo': 'anterior'}
        self.assertEqual([], ia.aplicar_confirmadas(linha, {'sugestoes': []}))
        self.assertEqual('anterior', linha['titulo'])

    def test_titulo_com_prova_nao_depende_de_tipo_resolvido(self):
        r=resposta();r.update(tipo_documento='trabalho acadêmico',nmAutor0=None,editora=None,data=None)
        a=ia.conferir_fonte_primaria(r,self.paginas)
        self.assertFalse(a['identidade_verificada'])
        linha={'titulo':'Nome errado','tipo_documento':'trabalho acadêmico','conflitos':[]}
        ia.aplicar_confirmadas(linha,{'fonte_primaria':a},['tipo_documento'])
        self.assertEqual('O Caminho da Fé',linha['titulo'])
        self.assertEqual('trabalho acadêmico',linha['tipo_documento'])

    def test_assinatura_propria_junto_ao_titulo_nao_exige_rotulo_autor(self):
        r=resposta();r.update(tipo_documento='artigo',nmAutor0='C. René Padilla',editora=None,data=None)
        r['evidencias']=[{'campo':'titulo','pagina':1,'trecho':'O Caminho da Fé'},
                        {'campo':'nmAutor0','pagina':1,'trecho':'C. René Padilla'}]
        a=ia.conferir_fonte_primaria(r,['O Caminho da Fé\nC. René Padilla\nTexto do artigo e suas reflexões.'])
        self.assertEqual('C. René Padilla',a['campos']['nmAutor0']['valor'])
        self.assertEqual('documento',a['tipo'])

    def test_slogan_em_maiusculas_nao_e_assinatura(self):
        r=resposta();r.update(tipo_documento='artigo',nmAutor0='RELACIONAMENTO AMOROSO',editora=None)
        r['evidencias']=[{'campo':'titulo','pagina':1,'trecho':'O Caminho da Fé'},
                        {'campo':'nmAutor0','pagina':1,'trecho':'RELACIONAMENTO AMOROSO'}]
        a=ia.conferir_fonte_primaria(r,['O Caminho da Fé\nRELACIONAMENTO AMOROSO\ntexto'])
        self.assertNotIn('nmAutor0',a['campos'])

    def test_fonte_primaria_preserva_integridade_e_edicao(self):
        a, _ = self.analisar()
        for s in a['sugestoes']:
            s['fontes_confirmadoras'] = []
        linha = {'conflitos': ['PDF pode estar incompleto: 20 paginas, a edicao tem 200',
                              'ISBN: divergente', 'edição divergente']}
        ia.aplicar_confirmadas(linha, a)
        self.assertEqual(3, len(linha['conflitos']))
        r = resposta()
        primaria = ia.conferir_fonte_primaria(r, self.paginas,
                       {'isbn_confirmado_na_edicao': True, 'data': '2001', 'titulo': 'Outro título'})
        self.assertNotIn('data', primaria['campos'])
        self.assertNotIn('titulo', primaria['campos'])

    def test_copyright_nao_e_byline_e_endereco_nao_e_cidade_publicacao(self):
        r = resposta()
        r.update(tipo_documento='artigo', lugar='São Paulo', nmAutor0='Maria Silva')
        r['evidencias'] += [{'campo': 'nmAutor0', 'pagina': 1, 'trecho': '© Maria Silva'},
                            {'campo': 'lugar', 'pagina': 1, 'trecho': 'Rua Dois, São Paulo'}]
        r['evidencias'] = [e for e in r['evidencias'] if not e['trecho'].startswith('Autor:')]
        p = self.paginas[0] + '\n© Maria Silva\nRua Dois, São Paulo'
        a = ia.conferir_fonte_primaria(r, [p])
        self.assertNotIn('nmAutor0', a['campos'])
        self.assertNotIn('lugar', a['campos'])

    def test_titulo_curto_so_como_linha_autonoma(self):
        r = resposta(); r['titulo'] = 'Paul'
        r['evidencias'][0]['trecho'] = 'Paul'
        a = ia.conferir_fonte_primaria(r, ['A letter from Paul to others'])
        self.assertNotIn('titulo', a['campos'])
        a = ia.conferir_fonte_primaria(r, ['Paul\nJewish Law and Early Christianity'])
        self.assertIn('titulo', a['campos'])

    def test_capitulo_avulso_nao_herda_titulo_do_cabecalho_do_livro(self):
        r=resposta();r.update(tipo_documento='trecho',titulo='Manual de Crescimento da Igreja',
                            nmAutor0=None,editora=None,data=None)
        r['evidencias']=[{'campo':'titulo','pagina':2,'trecho':'156 - Manual de Crescimento da Igreja'},
                        {'campo':'tipo_documento','pagina':1,'trecho':'CAPÍTULO VII'}]
        paginas=['CAPÍTULO VII\n\nO MINISTÉRIO SOCIAL E\nO CRESCIMENTO DA\nIGREJA\n\nNo segundo capítulo, falamos...',
                 '156 - Manual de Crescimento da Igreja\nTexto']
        a=ia.conferir_fonte_primaria(r,paginas)
        self.assertEqual('O MINISTÉRIO SOCIAL E O CRESCIMENTO DA IGREJA',a['campos']['titulo']['valor'])
        self.assertEqual('trecho',a['tipo'])
        self.assertIn('titulo_da_obra_origem',a['rejeitados'])

    def test_tipo_manual_nao_e_trocado_por_classificacao_da_ia(self):
        a, _ = self.analisar()
        linha = {'tipo_documento': 'documento', 'titulo': 'Manual'}
        ia.aplicar_confirmadas(linha, a, ['tipo_documento'])
        self.assertEqual('documento', linha['tipo_documento'])

    def test_citacao_inventada_ou_em_referencias_nao_e_primaria(self):
        r = resposta()
        for e in r['evidencias']:
            e['pagina'] = 15
        self.assertFalse(ia.conferir_fonte_primaria(r, self.paginas * 20)['campos'])

    def test_cronologia_contraditoria_nao_passa_como_data_confirmada(self):
        r = resposta(); r['observacoes'] = ['Sumário tem artigos posteriores a 2002: divergência não explicada.']
        a = ia.conferir_fonte_primaria(r, self.paginas)
        self.assertTrue(a['alerta_data'])
        self.assertNotIn('data', a['campos'])

    def test_divergencia_amostral_nao_e_contradicao_de_publicacao(self):
        r = resposta(); r['observacoes'] = ['Divergência nos dados: 585 entrevistas em 2022 e gráfico com 584.']
        self.assertFalse(ia.conferir_fonte_primaria(r, self.paginas)['alerta_data'])

    def test_editor_da_coletanea_conserva_papel_na_api(self):
        r = resposta(); r.update(tipo_documento='coletânea', nmAutor0=None)
        p = self.paginas[0] + '\nStaff for this book:\nMaria Silva – Editor\nJoão Souza – Designer'
        a = ia.conferir_fonte_primaria(r, [p])
        self.assertEqual('Editor', a['campos']['nmAutor0']['papel'])
        linha = {'conflitos': []}
        ia.aplicar_confirmadas(linha, {'fonte_primaria': a})
        self.assertEqual([{'nome': 'Maria Silva', 'desc': 'Editor'}], linha['autores'])
        self.assertEqual('livro', linha['tipo_documento'])

    def test_editor_do_periodico_citado_nao_vira_editor_da_coletanea(self):
        r = resposta();r.update(tipo_documento='coletânea', nmAutor0=None)
        p = self.paginas[0] + '\nwith Maria Silva, editor, Religious Review'
        a = ia.conferir_fonte_primaria(r, [p])
        self.assertNotIn('nmAutor0', a['campos'])

    def test_autores_anteriores_nao_sobrevivem_ao_anonimato_documental(self):
        r = resposta(); r.update(tipo_documento='artigo',nmAutor0=None)
        p = self.paginas[0]+'\nhttps://exemplo.org/article/teste\nAug 20, 2002'
        r['evidencias'] += [{'campo':'data','pagina':1,'trecho':'Aug 20, 2002'}]
        a=ia.conferir_fonte_primaria(r,[p])
        linha={'autores':[{'nome':'Menu incorreto'}], 'conflitos':[]}
        ia.aplicar_confirmadas(linha,{'fonte_primaria':a})
        self.assertEqual([],linha['autores'])

    def test_decisao_humana_e_id_remoto_nao_reabrem(self):
        for chave in ('revisao_manual_aprovada', 'id_remoto'):
            with mock.patch.object(ia, 'executar') as run:
                self.assertEqual('preservado', ia.analisar(self.pdf, self.paginas, contexto={chave: True})['estado'])
                run.assert_not_called()
            linha = {'titulo': 'manual', chave: True}
            self.assertEqual([], ia.aplicar_confirmadas(linha, {'sugestoes': []}))

    def test_salvo_sem_aprovar_tambem_preserva_campos_editados(self):
        a, _ = self.analisar()
        linha = {'titulo': 'Título manual', 'conflitos': []}
        ia.aplicar_confirmadas(linha, a, campos_manuais=['titulo'])
        self.assertEqual('Título manual', linha['titulo'])
        self.assertEqual('Vida', linha['editora'])

    def test_cache_evitar_nova_chamada_e_reavaliar_confirmacao(self):
        a, _ = self.analisar()
        with mock.patch.object(ia, 'status', return_value={'ativo': True}), \
             mock.patch.object(ia, 'binario', return_value='/bin/agy'), \
             mock.patch.object(ia, 'executar') as run:
            b = ia.analisar(self.pdf, self.paginas, {})
        run.assert_not_called()
        self.assertEqual(a['cache'], b['cache'])
        self.assertFalse(a['cache_reutilizado'])
        self.assertTrue(a['nova_consulta'])
        self.assertTrue(b['cache_reutilizado'])
        self.assertFalse(b['nova_consulta'])
        self.assertFalse(any(s['fontes_confirmadoras'] for s in b['sugestoes']))

    def test_citacao_fora_da_pagina_enviada_nao_confirma(self):
        r = resposta()
        r['evidencias'][0]['pagina'] = 8
        a, _ = self.analisar(r)
        self.assertFalse(a['sugestoes'][0]['evidencias'])
        r['evidencias'][0] = {'campo': 'titulo', 'pagina': 1, 'trecho': 'Inventado no PDF'}
        a, _ = self.analisar(r)
        # A resposta anterior em cache deve continuar válida; novo teste sem cache.
        pathlib.Path(a['cache']).unlink()
        a, _ = self.analisar(r)
        self.assertFalse(a['sugestoes'][0]['evidencias'])

    def test_falha_pausa_nuvem_mas_nao_aborta_lote(self):
        with mock.patch.object(ia, 'status', return_value={'ativo': True}), \
             mock.patch.object(ia, 'binario', return_value='/bin/agy'), \
             mock.patch.object(ia, 'executar', side_effect=TimeoutError()) as run, \
             mock.patch.object(ia.shutil, 'which', return_value=None):
            a = ia.analisar(self.pdf, self.paginas)
            b = ia.analisar(self.pdf, self.paginas)
        self.assertEqual(1, run.call_count)
        self.assertEqual('falha', a['estado'])
        self.assertEqual('indisponível', b['estado'])

    def test_selecao_limitada_numeracao_pdf_e_cip_tardia(self):
        paginas = ['texto'*5000]*20
        paginas[7] = 'créditos gráficos\n'*500 + 'Ficha catalográfica\nTítulo Especial\nISBN 9788572004824'
        ps = ia.selecionar_paginas(paginas)
        self.assertLessEqual(len(ps), 7)
        self.assertLessEqual(sum(len(x['texto']) for x in ps), 20000)
        self.assertTrue(any('Título Especial' in x['texto'] for x in ps))

    def test_politicas_cli_bloqueiam_comandos_rede_e_escrita(self):
        proc = mock.Mock(returncode=0)
        proc.communicate.return_value = (self.envelope(), '')
        proc.poll.return_value = 0
        with mock.patch.object(ia.subprocess, 'Popen', return_value=proc) as popen:
            ia.executar('/bin/agy', [{'pagina': 1, 'texto': 'dados'}], [])
        args = popen.call_args.args[0]
        rules = json.loads(args[args.index('--settings')+1])
        self.assertIn('command(*)', rules['permissions']['deny'])
        self.assertIn('write_file(*)', rules['permissions']['deny'])
        self.assertIn('read_url(*)', rules['permissions']['deny'])
        self.assertIn('--disable-slash-commands', args)
        self.assertNotIn('--dangerously-skip-permissions', args)

    def test_alerta_so_do_validador_final_tambem_aciona_camada(self):
        tree = ast.parse(pathlib.Path(ia.__file__).with_name('preparar-livros.py').read_text())
        processar = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'processar')
        bloco = next(n for n in processar.body if isinstance(n, ast.If) and any(
            isinstance(x, ast.FunctionDef) and x.name == 'confirmar_apple' for x in n.body))
        expressao = compile(ast.fix_missing_locations(ast.Expression(bloco.test)), '<gatilho>', 'eval')
        auditor = mock.Mock()
        auditor.auditar.return_value = [{'motivo': 'data só nas referências finais'}]
        ctx = {'usar_api': True, 'rev': {}, 'tipo_documento': 'livro', 'paginas': ['dados'],
               'linha': {'conflitos': [], 'titulo': 'Título', 'nmAutor0': 'Autor',
                         'editora': 'Editora', 'data': '2000'}, 'validacao_bibliografica': auditor}
        self.assertTrue(eval(expressao, ctx))
        ctx['rev'] = {'aprovado': True}
        self.assertFalse(eval(expressao, ctx))


if __name__ == '__main__':
    unittest.main()
