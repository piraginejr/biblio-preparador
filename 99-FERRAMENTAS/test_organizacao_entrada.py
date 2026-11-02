import importlib.util
import json
import pathlib
import tempfile
import unittest

s=importlib.util.spec_from_file_location('organizacao_local',pathlib.Path(__file__).with_name('biblioteca-local.py'))
b=importlib.util.module_from_spec(s);s.loader.exec_module(b)


class OrganizacaoEntradaTest(unittest.TestCase):
    def test_move_preservando_hash_historico_e_limpa_so_depois_de_resolvido(self):
        with tempfile.TemporaryDirectory() as td:
            c=b.inicializar(pathlib.Path(td)/'biblioteca')
            p=c['entrada']/'original.doc';p.write_bytes(b'documento')
            pdf=c['pronto']/'convertido.pdf';pdf.write_bytes(b'%PDF-1.7')
            digest=b.residuos_ciclo.sha(p)
            hist={str(p):{'assinatura':digest,'hash_sha256':'pdf'}}
            b.salvar_json(c['controle']/'importacoes-organizadas.json',{'versao':7,'itens':hist})
            cat={'livros':{'pdf':{'correcao_remota_pendente':True,'caminho':str(pdf.relative_to(c['raiz']))}}}
            plano=b.residuos_ciclo.planejar_pendencias(c,cat,hist)
            self.assertTrue(p.exists())
            op=b.organizar_residuos_entrada(c,[],plano,hist,pathlib.Path(td)/'lixo')
            self.assertFalse(p.exists());novo=c['raiz']/plano[0]['destino']
            self.assertEqual(digest,b.residuos_ciclo.sha(novo));self.assertTrue(pdf.exists())
            self.assertEqual(1,len(op['originais_preservados_em_pendencias']))
            self.assertEqual(7,json.loads((c['controle']/'importacoes-organizadas.json').read_text())['versao'])
            self.assertEqual([],b.residuos_ciclo.planejar(c,cat,hist))
            cat['livros']['pdf'].update(correcao_remota_pendente=False,estado='cadastrado',id_remoto=42)
            self.assertEqual([str(novo.relative_to(c['raiz']))],[x['arquivo'] for x in b.residuos_ciclo.planejar(c,cat,hist)])

    def test_revalida_a_copia_preservada_antes_de_levar_pacote_a_lixeira(self):
        with tempfile.TemporaryDirectory() as td:
            c=b.inicializar(pathlib.Path(td)/'biblioteca');p=c['entrada']/'obra.zip';p.write_bytes(b'pacote')
            item={'arquivo':str(p.relative_to(c['raiz'])),'sha256':b.sha256(p),
                  'copia_preservada':{'arquivo':'00-ENTRADA/ausente.doc','sha256':'abc'}}
            op=b.organizar_residuos_entrada(c,[item],[],{},pathlib.Path(td)/'lixo')
            self.assertTrue(p.exists());self.assertEqual([],op['residuos_ciclo_removidos'])


if __name__=='__main__':unittest.main()
