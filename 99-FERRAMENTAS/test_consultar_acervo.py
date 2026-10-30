import importlib.util
import json
import pathlib
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('consulta_acervo', pathlib.Path(__file__).with_name('consultar-acervo.py'))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


class ConsultaAcervoTest(unittest.TestCase):
    def test_opf_isbn_consulta_sem_upload_sem_alterar_original(self):
        with tempfile.TemporaryDirectory() as td:
            entrada = pathlib.Path(td)/'origem'; entrada.mkdir()
            opf = entrada/'livro.opf'
            opf.write_text('<package><metadata><title>Livro</title><creator>Autor</creator><identifier>9788587646293</identifier></metadata></package>')
            antes = opf.read_bytes()
            sessao = mock.MagicMock()
            sessao.__enter__.return_value = sessao
            resp = sessao.post.return_value; resp.status_code = 200
            resp.json.return_value = {'encontrado':True,'isbn':'9788587646293','id':123,'total_matches':1}
            out = mod.executar(entrada, pathlib.Path(td)/'relatorios',sessao=sessao,chave='teste')
            self.assertEqual('já existente por ISBN',out[0]['resultado'])
            self.assertEqual(antes,opf.read_bytes())
            kwargs = sessao.post.call_args.kwargs
            self.assertEqual('consultar_livro',kwargs['json']['action'])
            self.assertNotIn('files',kwargs)

    def test_nome_arquivo_nao_confirma_identidade(self):
        with mock.patch.object(mod,'identificar',return_value={'titulo':'pista','autores':[], 'isbns':[], 'fonte':'arquivo'}):
            with mock.patch.object(mod.api,'consultar_livro',return_value={'encontrado':False}):
                out = mod.consultar(pathlib.Path('pista.pdf'),mock.Mock(),'teste')
        self.assertEqual('precisa conferir',out['resultado'])

    def test_varios_isbns_nao_aprovam_automaticamente(self):
        with mock.patch.object(mod,'identificar',return_value={'titulo':'Coleção','autores':[], 'isbns':['9788587646293','9788551018743'], 'fonte':'PDF'}):
            with mock.patch.object(mod.api,'consultar_livro',side_effect=lambda s,c,**kw:{'encontrado':True,'isbn':kw['isbn'],'criterios_enviados':{'isbn':kw['isbn']}}):
                out = mod.consultar(pathlib.Path('colecao.pdf'),mock.Mock(),'teste')
        self.assertEqual('precisa conferir',out['resultado'])

    def test_pdf_leitura_limitada_sem_ocr(self):
        with mock.patch.object(mod.subprocess,'run',return_value=mock.Mock(returncode=0,stdout='ISBN 9788587646293')) as run:
            out = mod.identificar(pathlib.Path('Livro.pdf'))
        self.assertEqual(['9788587646293'],out['isbns'])
        self.assertEqual(['pdftotext','-f','1','-l','12','Livro.pdf','-'],run.call_args.args[0])
