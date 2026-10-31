import hashlib
import json
import pathlib
import tempfile
import unittest
import residuos_ciclo as residuos


class ResiduosTest(unittest.TestCase):
    def contexto(self,td):
        r=pathlib.Path(td)/'biblioteca';e=r/'00-ENTRADA';c=r/'_controle'
        e.mkdir(parents=True);c.mkdir()
        return {'raiz':r,'entrada':e,'controle':c}

    def salvar(self,p,d):p.write_text(json.dumps(d))

    def test_recibo_revisado_exige_hash_e_preserva_origem_externa(self):
        with tempfile.TemporaryDirectory() as td:
            c=self.contexto(td);p=c['entrada']/'legado.cpt';p.write_bytes(b'base antiga')
            externo=pathlib.Path(td)/'nuvem-original.cpt';externo.write_bytes(p.read_bytes())
            itens=[{'arquivo':str(x),'sha256':residuos.sha(x),'aprovado':True} for x in (p,externo)]
            self.salvar(c['controle']/'residuos-ciclo.json',{'itens':itens})
            plano=residuos.planejar(c,{'livros':{}},{})
            self.assertEqual(['00-ENTRADA/legado.cpt'],[x['arquivo'] for x in plano])
            p.write_bytes('novo conteúdo'.encode())
            self.assertEqual([],residuos.planejar(c,{'livros':{}},{}))
            self.assertTrue(externo.exists())

    def test_pacote_misto_preservado_ate_todos_documentos_resolvidos(self):
        with tempfile.TemporaryDirectory() as td:
            c=self.contexto(td);p=c['entrada']/'livros.zip';p.write_bytes(b'pacote')
            raw_a=hashlib.sha256(b'word a').hexdigest();raw_b=hashlib.sha256(b'word b').hexdigest()
            cat={'livros':{'pdf-a':{'estado':'cadastrado - arquivos locais liberados'},
                           'pdf-b':{'estado':'conflito'}}}
            hist={'a':{'assinatura':raw_a,'hash_sha256':'pdf-a'},
                  'b':{'assinatura':raw_b,'hash_sha256':'pdf-b'}}
            self.salvar(c['controle']/'importacoes-compactados.json',{'itens':{
                residuos.sha(p):{'ok':True,'origem':str(p),'destino':str(c['entrada']/'_descompactados/livros'),
                'extraidos':['a.doc','b.doc'],'hashes_extraidos':{'a.doc':raw_a,'b.doc':raw_b},'ignorados':[]}}})
            self.assertEqual([],residuos.planejar(c,cat,hist))
            cat['livros']['pdf-b']['estado']='cadastrado - arquivos locais liberados'
            self.assertEqual(1,len(residuos.planejar(c,cat,hist)))
            cat['livros']['pdf-b']['correcao_remota_pendente']=True
            self.assertEqual([],residuos.planejar(c,cat,hist))

    def test_arquivos_novos_e_recibos_com_pendencia_nao_somem(self):
        with tempfile.TemporaryDirectory() as td:
            c=self.contexto(td);p=c['entrada']/'novo.doc';p.write_bytes(b'novo')
            cat={'livros':{'h':{'estado':'resultado incerto - nao reenviar sem conferencia'}}}
            self.assertEqual([],residuos.planejar(c,cat,{}))
            self.salvar(c['controle']/'residuos-ciclo.json',{'itens':[{
                'arquivo':str(p),'sha256':residuos.sha(p),'aprovado':True,'hashes_catalogo':['h']}]})
            self.assertEqual([],residuos.planejar(c,cat,{}))

    def test_link_para_origem_externa_bloqueado(self):
        with tempfile.TemporaryDirectory() as td:
            c=self.contexto(td);p=pathlib.Path(td)/'nuvem.doc';p.write_bytes(b'original')
            link=c['entrada']/'atalho.doc';link.symlink_to(p)
            self.assertIsNone(residuos.local_entrada(c,str(link)))

    def test_legado_nao_usa_conversao_antiga_para_ignorar_pendencia_nova(self):
        with tempfile.TemporaryDirectory() as td:
            c=self.contexto(td);p=c['entrada']/'antigo.zip';p.write_bytes(b'pacote')
            destino=str(c['entrada']/'_descompactados/antigo')
            cat={'livros':{'antigo':{'estado':'cadastrado - arquivos locais liberados'},
                           'novo':{'estado':'pronto para cadastro'}}}
            hist={destino+'/obra.doc':{'assinatura':'raw','hash_sha256':'antigo'},
                  'outra-origem':{'assinatura':'raw','hash_sha256':'novo'}}
            self.salvar(c['controle']/'importacoes-compactados.json',{'itens':{
                residuos.sha(p):{'ok':True,'origem':str(p),'destino':destino,
                                 'extraidos':['obra.doc'],'ignorados':[]}}})
            self.assertEqual([],residuos.planejar(c,cat,hist))
