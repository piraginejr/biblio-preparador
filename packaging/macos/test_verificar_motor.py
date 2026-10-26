import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('verificar_motor', Path(__file__).with_name('verificar_motor.py'))
motor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(motor)


class ManifestoTest(unittest.TestCase):
    def test_instalacao_do_projeto_sem_manifesto_atualiza_identificador(self):
        with tempfile.TemporaryDirectory() as td:
            origem, destino = Path(td)/'origem', Path(td)/'destino'
            origem.mkdir(); destino.mkdir()
            (origem/'motor.py').write_text('novo')
            (destino/'motor.py').write_text('antigo')
            motor.gravar_manifesto(destino)
            motor.instalar(origem, destino)
            self.assertEqual('novo', (destino/'motor.py').read_text())
            self.assertTrue(motor.manifesto_valido(destino))

    def test_hashes_iguais_nao_escondem_manifesto_obsoleto(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p/'motor.py').write_text('antigo')
            motor.gravar_manifesto(p)
            (p/'motor.py').write_text('novo')
            self.assertFalse(motor.manifesto_valido(p))
            motor.gravar_manifesto(p)
            self.assertTrue(motor.manifesto_valido(p))
