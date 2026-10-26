import pathlib
import tempfile
import unittest
import zipfile
import importar_compactados as imp


class CompactadosTest(unittest.TestCase):
    def test_extrais_documentos_sem_executaveis_e_sem_sobrescrever(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            arquivo = raiz / 'livros.zip'
            with zipfile.ZipFile(arquivo, 'w') as z:
                z.writestr('Autor/Livro.pdf', b'%PDF-teste')
                z.writestr('instalar.exe', b'nao executar')
                z.writestr('outro.zip', b'nao recursivo')
            r = imp.extrair(arquivo, raiz / 'saida')
            self.assertTrue(r['ok'])
            self.assertEqual(['Autor/Livro.pdf'], r['extraidos'])
            self.assertEqual(2, len(r['ignorados']))
            self.assertEqual(b'%PDF-teste', (raiz / 'saida/Autor/Livro.pdf').read_bytes())
            with self.assertRaises(FileExistsError):
                imp.extrair(arquivo, raiz / 'saida')

    def test_traversal_nao_escapa(self):
        for nome in ('../fora.pdf', '/fora.pdf', 'C:\\fora.pdf', 'a/../../fora.pdf'):
            with self.subTest(nome=nome), self.assertRaises(ValueError):
                imp.caminho_seguro(nome)

    def test_limite_e_links(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            arquivo = raiz / 'livros.zip'
            with zipfile.ZipFile(arquivo, 'w') as z:
                z.writestr('livro.pdf', b'123456')
            with self.assertRaisesRegex(ValueError, 'tamanho'):
                imp.extrair(arquivo, raiz / 'grande', max_item=3)
            with zipfile.ZipFile(arquivo, 'w') as z:
                info = zipfile.ZipInfo('link.pdf')
                info.create_system = 3
                info.external_attr = 0o120777 << 16
                z.writestr(info, '../alvo')
            with self.assertRaisesRegex(ValueError, 'link'):
                imp.extrair(arquivo, raiz / 'link')

    def test_manifesto_impede_reextracao(self):
        with tempfile.TemporaryDirectory() as td:
            raiz = pathlib.Path(td)
            entrada, controle = raiz / 'entrada', raiz / 'controle'
            entrada.mkdir()
            controle.mkdir()
            with zipfile.ZipFile(entrada / 'livros.zip', 'w') as z:
                z.writestr('livro.pdf', b'%PDF-teste')
            primeiro = imp.preparar(entrada, controle)
            self.assertEqual(primeiro, imp.preparar(entrada, controle))
            self.assertEqual(1, len(list(entrada.rglob('*.pdf'))))

