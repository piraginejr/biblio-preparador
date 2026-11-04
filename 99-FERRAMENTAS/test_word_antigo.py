import importlib.util,pathlib,tempfile,unittest
from unittest import mock
s=importlib.util.spec_from_file_location('word_antigo',pathlib.Path(__file__).with_name('biblioteca-local.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class WordAntigoTest(unittest.TestCase):
    def test_pdf_existente_nunca_e_substituido_pela_recuperacao(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td);origem=p/'a.doc';origem.write_bytes(bytes.fromhex('d0cf11e0a1b11ae1'))
            pdf=p/'a.pdf';pdf.write_bytes(b'original')
            with mock.patch.object(m.subprocess,'run') as run:
                self.assertFalse(m._converter_word_antigo_textutil(origem,pdf,'lo')[0])
            run.assert_not_called();self.assertEqual(b'original',pdf.read_bytes())

    def test_binario_sem_assinatura_ole_nao_vira_pdf_de_lixo(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td);origem=p/'a.doc';origem.write_bytes(b'binario desconhecido')
            with mock.patch.object(m.subprocess,'run') as run:
                self.assertFalse(m._converter_word_antigo_textutil(origem,p/'a.pdf','lo')[0])
            run.assert_not_called()

    def test_camada_recuperacao_antes_de_word_grafico(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td);origem=p/'a.doc';origem.write_bytes(b'DOC')
            with mock.patch.object(m,'localizar_soffice',return_value='lo'), \
                 mock.patch.object(m,'_converter_word_libreoffice',return_value=(False,'formato antigo')), \
                 mock.patch.object(m,'_converter_word_antigo_textutil',return_value=(True,'')) as recuperar:
                r=m.converter_word_para_pdf(origem,p/'a.pdf')
            self.assertTrue(r['ok']);self.assertIn('DOC antigo',r['motor']);recuperar.assert_called_once()

if __name__=='__main__':unittest.main()
