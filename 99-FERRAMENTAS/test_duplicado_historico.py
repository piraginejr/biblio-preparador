import importlib.util,pathlib,tempfile,unittest
from unittest import mock
s=importlib.util.spec_from_file_location('historico',pathlib.Path(__file__).with_name('biblioteca-local.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

class HistoricoTest(unittest.TestCase):
    def registro(self,paginas):
        a=m.assinatura_textual(paginas)
        return {'palavras_texto':a['palavras'],'hash_texto':a['hash_texto'],
            'simhash_texto':a['simhash'],'estado':'cadastrado - arquivos locais liberados',
            'id_remoto':20907,'arquivo':'teste.pdf','titulo':'Teste'}

    def test_texto_integral_guardado_dispensa_pdf_ja_liberado(self):
        paginas=[' '.join('palavra'+str(i) for i in range(300))]
        with mock.patch.object(m,'_arquivo_do_registro',side_effect=AssertionError('Não reler acervo')):
            _,d=m.localizar_duplicado_textual({}, {'livros':{'a'*64:self.registro(paginas)}},paginas)
        self.assertEqual(20907,d['id_remoto']);self.assertIn('prova_duplicado_integral',d)

    def test_referencia_de_outra_instalacao_nao_vira_registro_no_catalogo(self):
        paginas=[' '.join('palavra'+str(i) for i in range(300))]
        c={'livros':{},'referencias_remotas':{'a'*64:self.registro(paginas)}}
        _,d=m.localizar_duplicado_textual({},c,paginas,excluir_digest='a'*64)
        self.assertTrue(d['referencia_historica']);self.assertEqual({},c['livros'])

    def test_hash_de_pagina_vazia_nao_comprova_obra(self):
        paginas=[''];r=self.registro(paginas)
        self.assertEqual({},m.localizar_duplicado_textual({}, {'livros':{'a'*64:r}},paginas)[1])

    def test_amostra_de_livro_longo_nao_comprova_texto_inteiro(self):
        paginas=[' '.join('palavra'+str(i) for i in range(31000))]
        r=self.registro(paginas)
        with mock.patch.object(m,'_arquivo_do_registro',return_value=None):
            self.assertEqual({},m.localizar_duplicado_textual({}, {'livros':{'a'*64:r}},paginas)[1])

    def test_consolidacao_nao_reabre_duplicado_integral_para_corrigir(self):
        with tempfile.TemporaryDirectory() as td:
            c=m.inicializar(pathlib.Path(td)/'livros');h='a'*64
            p=c['documentos']/'artigo.pdf';p.write_bytes(b'%PDF-teste')
            fp=c['metadados']/'artigo.json';m.salvar_json(fp,{'tipo_documento':'documento',
                'titulo':'Artigo','arquivo':p.name,'pdf_original':m.relativo(c,p)})
            r={'hash_sha256':h,'estado':m.ESTADO_DUPLICADO_CONTEUDO,'arquivo':p.name,
                'metadados':m.relativo(c,fp),'caminho':m.relativo(c,p),'id_remoto':20910,
                'confirmado_por_api':'texto_integral','prova_duplicado_integral':{
                    'id_remoto':20910,'hash_texto_integral':'b'*64,'hash_destino':'c'*64}}
            cat={'livros':{h:r}}
            with mock.patch.object(m.api_envio,'validar',return_value=['não é ficha de novo envio']):
                m.consolidar_filas_especificas(c,cat)
            self.assertEqual(m.ESTADO_DUPLICADO_CONTEUDO,r['estado'])

if __name__=='__main__':unittest.main()
