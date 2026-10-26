import pathlib
import tempfile
import unittest
import triagem_entrada as triagem


class TriagemTest(unittest.TestCase):
    def test_documentos_e_anexos_nao_sao_descartados(self):
        with tempfile.TemporaryDirectory() as td:
            entrada = pathlib.Path(td)
            for nome in ('pesquisa.txt','artigo.html','arquivo.hlp','livro.opf',
                         'capa.jpg','obra.zip','documento.doc','indice.ind','arquivo.desconhecido'):
                p=entrada/nome
                p.write_text('https://exemplo.org é uma referência do conteúdo')
                self.assertEqual('',triagem.motivo(p,entrada),nome)
            p=entrada/'link.url';p.write_text('[InternetShortcut]')
            self.assertIn('atalho',triagem.motivo(p,entrada))

    def test_fontes_de_html_e_links_na_pasta_de_recursos_preservados(self):
        with tempfile.TemporaryDirectory() as td:
            entrada=pathlib.Path(td)
            recurso=entrada/'pagina_files';recurso.mkdir()
            for nome in ('fonte.ttf','icone.url'):
                p=recurso/nome;p.write_bytes(b'dados')
                self.assertEqual('',triagem.motivo(p,entrada))
            p=entrada/'fonte.otf';p.write_bytes(b'fonte')
            self.assertIn('tipográfica',triagem.motivo(p,entrada))
            (entrada/'livro.opf').write_text('metadados')
            self.assertEqual('',triagem.motivo(p,entrada))

    def test_separacao_registra_e_nunca_sobrescreve_ou_segue_link(self):
        with tempfile.TemporaryDirectory() as td:
            raiz=pathlib.Path(td)
            c={'raiz':raiz,'entrada':raiz/'00-ENTRADA','controle':raiz/'_controle',
               'descarte':raiz/'19-DESCARTE'}
            for p in c.values():p.mkdir(exist_ok=True)
            link=c['entrada']/'site.url';link.write_text('site')
            (c['entrada']/'simbolico.url').symlink_to(link)
            itens=triagem.organizar(c)
            self.assertEqual(1,len(itens))
            self.assertFalse(link.exists())
            self.assertEqual(1,len(triagem.para_limpeza(c)))
            link.write_text('site')
            novo=triagem.organizar(c)
            self.assertNotEqual(itens[0]['arquivo'],novo[0]['arquivo'])
            self.assertEqual(2,len(triagem.para_limpeza(c)))
            (raiz/itens[0]['arquivo']).write_text('mudou depois da separação')
            self.assertEqual(1,len(triagem.para_limpeza(c)))
