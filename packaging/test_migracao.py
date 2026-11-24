import io
import pathlib
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from migracao import criar_tar, verificar_tar


class MigracaoTest(unittest.TestCase):
    def test_preserva_dados_e_ignora_git_cache_links(self):
        with tempfile.TemporaryDirectory() as folder:
            base = pathlib.Path(folder)
            src = base / 'origem'
            src.mkdir()
            (src / 'ficha.json').write_text('{"id":42}')
            (src / 'livro.pdf').write_bytes(b'%PDF-exemplo')
            (src / '.git').mkdir()
            (src / '.git/config').write_text('nao arquivar')
            (src / 'link').symlink_to('/etc/passwd')
            archive = base / 'teste.tar.gz'
            records = criar_tar(archive, {'dados': src})
            self.assertEqual(verificar_tar(archive, records), 2)
            self.assertEqual(len([r for r in records if not r['incluido']]), 1)
            records[0]['sha256'] = 'divergente'
            with self.assertRaises(ValueError):
                verificar_tar(archive, records)

    def test_rejeita_caminho_inseguro(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = pathlib.Path(folder) / 'inseguro.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                info = tarfile.TarInfo('../fora')
                info.size = 1
                tar.addfile(info, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                verificar_tar(archive, [])

    def test_metadado_alterado_nao_e_alteracao_de_conteudo(self):
        with tempfile.TemporaryDirectory() as folder:
            base = pathlib.Path(folder)
            src = base / 'origem'
            src.mkdir()
            file = src / 'ficha.json'
            file.write_text('{"id":42}')
            original = tarfile.TarFile.add

            def add(tar, name, *args, **kwargs):
                import os
                result = original(tar, name, *args, **kwargs)
                os.utime(name, (1, 1))
                return result

            with patch.object(tarfile.TarFile, 'add', add):
                records = criar_tar(base / 'a.tgz', {'dados': src})
            self.assertEqual(verificar_tar(base / 'a.tgz', records), 1)

    def test_rejeita_conteudo_alterado_durante_copia(self):
        with tempfile.TemporaryDirectory() as folder:
            base = pathlib.Path(folder)
            src = base / 'origem'
            src.mkdir()
            (src / 'ficha.json').write_text('{"id":42}')
            original = tarfile.TarFile.add

            def add(tar, name, *args, **kwargs):
                result = original(tar, name, *args, **kwargs)
                pathlib.Path(name).write_text('{"id":43}')
                return result

            with patch.object(tarfile.TarFile, 'add', add):
                with self.assertRaises(RuntimeError):
                    criar_tar(base / 'a.tgz', {'dados': src})


if __name__ == '__main__':
    unittest.main()
