import pathlib
import tempfile
import unittest
from unittest import mock
import converter_html as h


class ConverterHTMLTest(unittest.TestCase):
    def test_frames_nao_geram_falso_pdf_branco(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/'pagina.htm';p.write_text('<frameset><frame src="ausente.htm"></frameset>')
            with mock.patch.object(h,'_converter_chromium') as navegador:
                ok,erro=h.converter(p,p.with_suffix('.pdf'))
            self.assertFalse(ok);self.assertIn('frames',erro);navegador.assert_not_called()
    def test_destino_existente_preservado(self):
        with tempfile.TemporaryDirectory() as td:
            origem=pathlib.Path(td)/'teste.htm';origem.write_text('<h1>Título</h1>')
            destino=origem.with_suffix('.pdf');destino.write_bytes(b'%PDF-original')
            with mock.patch.object(h,'_converter_chromium') as navegador:
                self.assertFalse(h.converter(origem,destino)[0])
            navegador.assert_not_called()
            self.assertEqual(b'%PDF-original',destino.read_bytes())

    def test_codificacao_e_entidades(self):
        with tempfile.TemporaryDirectory() as td:
            p=pathlib.Path(td)/'teste.htm'
            p.write_bytes('<meta charset="windows-1252"><title>Fé &amp; missão</title>'.encode('cp1252'))
            self.assertEqual('Fé & missão',h.titulo_do_html(p))

    def test_alternativa_local_remove_rede_scripts_e_css(self):
        with tempfile.TemporaryDirectory() as td:
            pasta=pathlib.Path(td);(pasta/'capa.jpg').write_bytes(b'jpg')
            p=h._HTMLLocal(pasta)
            p.feed('<base href="https://host"><script>segredo</script><style>@import "https://host"</style><img src="//host/capa"><img src="capa.jpg" onerror="falha()"><p style="background:url(https://host)">Fé</p>')
            saida=''.join(p.partes)
            self.assertNotIn('https:',saida);self.assertNotIn('//host',saida)
            self.assertNotIn('segredo',saida);self.assertNotIn('onerror',saida)
            self.assertIn('file:',saida);self.assertIn('Fé',saida)

    def test_libreoffice_recebe_copia_sanitizada_e_perfil_isolado(self):
        with tempfile.TemporaryDirectory() as td:
            pasta=pathlib.Path(td);origem=pasta/'pagina.htm';origem.write_text('<h1>Fé</h1><script>ruído</script>')
            def executar(cmd,**kwargs):
                entrada=pathlib.Path(cmd[-1]);self.assertNotEqual(origem,entrada)
                self.assertNotIn('<script>',entrada.read_text())
                self.assertTrue(any(x.startswith('-env:UserInstallation=') for x in cmd))
                (pathlib.Path(cmd[cmd.index('--outdir')+1])/'pagina-local.pdf').write_bytes(b'%PDF-validado')
                return mock.Mock(returncode=0)
            with mock.patch.dict(h.os.environ,{'BIBLIO_SOFFICE':'/teste/soffice'}), mock.patch.object(h.subprocess,'run',side_effect=executar):
                self.assertTrue(h._converter_libreoffice(origem,pasta/'destino.pdf')[0])
