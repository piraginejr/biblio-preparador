import importlib.util,json,pathlib,unittest

s=importlib.util.spec_from_file_location('autores_api',pathlib.Path(__file__).with_name('enviar-livro-api.py'))
a=importlib.util.module_from_spec(s);s.loader.exec_module(a)

class AutoresCompostosTest(unittest.TestCase):
    def test_preserva_nome_bibliografico_longo(self):
        for nome in ('Matos, Alderi Souza de','Pereira, Jose L G','Mesquita, José João de Moreira'):
            self.assertEqual(nome,a.nome_para_api(nome))

    def test_natural_longo_vai_sem_truncamento(self):
        self.assertEqual('França, Valdir Xavier de',a.nome_para_api('Valdir Xavier de França'))
        self.assertEqual('Caldas Filho, Carlos Ribeiro',a.nome_para_api('Carlos Ribeiro Caldas Filho'))

    def test_nomes_curtos_conservam_contrato_anterior(self):
        self.assertEqual('C. René Padilla',a.nome_para_api('Padilla, C. René'))
        self.assertEqual('Platão',a.nome_para_api('Platão'))

    def test_sufixo_jr_nao_e_confundido_com_prenome(self):
        self.assertEqual('Beck Jr., John C.',a.nome_para_api('Dr. John C. Beck, Jr.'))

    def test_payload_nao_desfaz_protecao(self):
        payload=a.montar_payload({'titulo':'Missão','tipo_documento':'documento',
            'autores':[{'nome':'Matos, Alderi Souza de','desc':'Autor'}]},tipo_api='documento')
        self.assertEqual('Matos, Alderi Souza de',json.loads(payload['autores'])[0]['nome'])

if __name__=='__main__':unittest.main()
