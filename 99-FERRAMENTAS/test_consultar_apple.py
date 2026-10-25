import copy
import pathlib
import tempfile
import unittest
from unittest import mock

import consultar_apple as apple


class AppleTest(unittest.TestCase):
    def setUp(self):
        self.paginas = ['O Caminho da Fé\nAutor: Maria Silva\nEditora Vida, 2002']
        self.resposta = {'titulo': 'O Caminho da Fé', 'autores': ['Maria Silva'],
                         'editora': 'Vida', 'data': '2002', 'evidencias': [
            {'campo': 'titulo', 'pagina': 1, 'trecho': 'O Caminho da Fé'},
            {'campo': 'nmAutor0', 'pagina': 1, 'trecho': 'Autor: Maria Silva'},
            {'campo': 'editora', 'pagina': 1, 'trecho': 'Editora Vida, 2002'},
            {'campo': 'data', 'pagina': 1, 'trecho': 'Editora Vida, 2002'}]}
        self.fontes = {'catálogo': {'titulo': 'O Caminho da Fé', 'autores': ['Silva, Maria'],
                                    'editora': 'Vida', 'ano': '2002'}}

    def test_citacao_real_e_fonte_confirmam_campos(self):
        dados = apple.conferir(self.resposta, self.paginas, self.fontes)
        self.assertEqual(4, len(dados))
        self.assertTrue(all(s['fontes_confirmadoras'] == ['catálogo'] for s in dados))

    def test_trecho_inventado_nao_confirma(self):
        self.resposta['evidencias'][2]['trecho'] = 'Editora Vida, São Paulo, 2002'
        s = apple.conferir(self.resposta, self.paginas, self.fontes)[2]
        self.assertFalse(s['evidencias'])
        self.assertFalse(s['fontes_confirmadoras'])

    def test_citacao_real_com_valor_inventado_nao_confirma(self):
        self.resposta['editora'] = 'XYZ'
        s = apple.conferir(self.resposta, self.paginas, self.fontes)[2]
        self.assertFalse(s['evidencias'])

    def test_omissao_de_citacao_pode_ser_localizada_sem_fingir_evidencia_da_ia(self):
        self.resposta['evidencias'] = []
        dados = apple.conferir(self.resposta, self.paginas, self.fontes,
                              trechos={1: self.paginas[0]})
        self.assertEqual('localização literal pelo motor', dados[0]['evidencias'][0]['origem'])
        self.assertTrue(dados[0]['fontes_confirmadoras'])
        self.resposta['editora'] = 'Inventada'
        dados = apple.conferir(self.resposta, self.paginas, self.fontes,
                              trechos={1: self.paginas[0]})
        self.assertFalse(dados[2]['evidencias'])

    def test_homonimo_ou_isbn_volume_divergente_nao_confirma(self):
        for campo, valor in [('autores', ['Outra Pessoa']), ('isbn', '9781234567897'), ('volume', '2')]:
            fontes = copy.deepcopy(self.fontes)
            fontes['catálogo'][campo] = valor
            dados = apple.conferir(self.resposta, self.paginas, fontes,
                                   {'isbn': '9788572004824', 'volume': '1'})
            self.assertTrue(all(not s['fontes_confirmadoras'] for s in dados))

    def test_isbn10_equivale_13(self):
        self.assertEqual('9788572004824', apple.isbn_normalizado('85-7200-482-3'))

    def test_sugestao_sem_confirmacao_nao_altera_ficha(self):
        linha = {'titulo': 'antigo', 'conflitos': ['titulo so do nome do arquivo: antigo']}
        antes = copy.deepcopy(linha)
        a = {'sugestoes': apple.conferir(self.resposta, self.paginas, {})}
        self.assertEqual([], apple.aplicar_confirmadas(linha, a))
        self.assertEqual(antes, linha)

    def test_confirmadas_resolvem_fallback_sem_apagar_divergencia_isbn(self):
        linha = {'titulo': 'antigo', 'conflitos': [
            'titulo so do nome do arquivo: antigo', 'ISBN: edição divergente']}
        a = {'sugestoes': apple.conferir(self.resposta, self.paginas, self.fontes)}
        apple.aplicar_confirmadas(linha, a)
        self.assertEqual('O Caminho da Fé', linha['titulo'])
        self.assertEqual(['ISBN: edição divergente'], linha['conflitos'])
        self.assertEqual(4, len(a['campos_aplicados']))

    def test_confirmacao_libera_fallback_e_completa_campos_obrigatorios(self):
        linha = {'titulo': 'arquivo', 'nmLingua': 'portugues',
                 'conflitos': ['titulo so do nome do arquivo: arquivo']}
        a = {'sugestoes': apple.conferir(self.resposta, self.paginas, self.fontes)}
        apple.aplicar_confirmadas(linha, a)
        self.assertFalse(linha['conflitos'])
        self.assertTrue(all(linha.get(c) for c in ('titulo', 'nmAutor0', 'editora', 'data', 'nmLingua')))

    def test_erro_temporario_em_cache_nao_impede_nova_analise(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pdf = pathlib.Path(d) / 'livro.pdf'
            pdf.write_bytes(b'amostra')
            with mock.patch.object(apple, 'binario', return_value='/bin/modelo'), \
                 mock.patch.object(apple, 'executar', return_value=json.dumps(self.resposta)) as rodar, \
                 mock.patch.object(apple.shutil, 'which', return_value=None):
                a = apple.analisar(pdf, self.paginas, self.fontes)
                pathlib.Path(a['cache']).write_text('{"erro":"temporário"}')
                b = apple.analisar(pdf, self.paginas, self.fontes)
            self.assertEqual(2, rodar.call_count)
            self.assertEqual('revisão assistida', b['estado'])

    def test_numero_pagina_invalido_e_resposta_malformada(self):
        self.resposta['evidencias'][0]['pagina'] = 999
        dados = apple.conferir(self.resposta, self.paginas, self.fontes)
        self.assertFalse(dados[0]['evidencias'])
        self.assertEqual([], apple.conferir([], self.paginas, {}))

    def test_entrada_curta_e_numerada(self):
        selecionadas = apple.selecionar_paginas(['texto' * 10000] * 30)
        self.assertLessEqual(sum(len(x['texto']) for x in selecionadas), 5100)
        self.assertTrue(all(1 <= x['pagina'] <= 30 for x in selecionadas))

    def test_cip_no_fim_da_pagina_vence_creditos_de_capa(self):
        paginas = [''] * 8
        paginas[7] = 'Capa: Victor Burton\n' + 'crédito gráfico\n' * 80 + 'Ficha Catalográfica\nCIP\nDomínios da história / Ciro Cardoso\n'
        selecionadas = apple.selecionar_paginas(paginas)
        self.assertIn('Ciro Cardoso', selecionadas[0]['texto'])
        self.assertNotIn('Victor Burton', selecionadas[0]['texto'])
        self.assertLessEqual(sum(len(x['texto']) for x in selecionadas), 2700)

    def test_falha_nao_interrompe_lote(self):
        with mock.patch.object(apple, 'binario', side_effect=RuntimeError('modelo indisponível')):
            self.assertEqual('falha', apple.analisar('nada.pdf', ['x'])['estado'])

    def test_cache_reutiliza_modelo_e_reavalia_fontes(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            pdf = pathlib.Path(d) / 'livro.pdf'
            pdf.write_bytes(b'pdf simulado')
            with mock.patch.object(apple, 'binario', return_value='/bin/modelo'), \
                 mock.patch.object(apple, 'executar', return_value=json.dumps(self.resposta)) as rodar, \
                 mock.patch.object(apple.shutil, 'which', return_value=None):
                a = apple.analisar(pdf, self.paginas, self.fontes)
                b = apple.analisar(pdf, self.paginas, {})
            self.assertEqual(1, rodar.call_count)
            self.assertTrue(a['sugestoes'][0]['fontes_confirmadoras'])
            self.assertFalse(b['sugestoes'][0]['fontes_confirmadoras'])


if __name__ == '__main__':
    unittest.main()
