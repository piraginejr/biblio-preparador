import importlib.util,json,pathlib,tempfile,unittest
from unittest import mock
import consultar_claude as ia


class GeminiReservaTest(unittest.TestCase):
    def test_cota_esgotada_aciona_reserva_mas_nao_muda_decisao_humana(self):
        with mock.patch.object(ia,'status',return_value={'ativo':True,'gemini_reserva':True}), \
             mock.patch.object(ia,'_analisar_modelo',side_effect=[
                 {'estado':'falha','tipo_falha':'cota'},
                 {'estado':'revisão assistida','modelo':ia.MODELO_GEMINI,'provedor':'Gemini'}]) as run:
            r=ia.analisar('pdf',[])
        self.assertEqual('Gemini',r['provedor']);self.assertEqual(2,run.call_count)
        self.assertEqual(ia.MODELO_GEMINI,run.call_args.args[-2])
        self.assertEqual(300,run.call_args.args[-1])
        with mock.patch.object(ia,'status',return_value={'ativo':True,'gemini_reserva':True}), \
             mock.patch.object(ia,'_analisar_modelo',return_value={'estado':'preservado'}) as run:
            ia.analisar('pdf',[],contexto={'revisao_manual_aprovada':True})
        self.assertEqual(1,run.call_count)

    def test_nao_duplica_analise_quando_claude_respondeu(self):
        with mock.patch.object(ia,'status',return_value={'ativo':True,'gemini_reserva':True}), \
             mock.patch.object(ia,'_analisar_modelo',return_value={'estado':'revisão assistida'}) as run:
            ia.analisar('pdf',[])
        self.assertEqual(1,run.call_count)

    def test_falha_autenticacao_nao_gasta_outro_modelo(self):
        with mock.patch.object(ia,'status',return_value={'ativo':True,'gemini_reserva':True}), \
             mock.patch.object(ia,'_analisar_modelo',return_value={'estado':'falha','tipo_falha':'autenticacao'}) as run:
            ia.analisar('pdf',[])
        self.assertEqual(1,run.call_count)

    def test_cota_e_pausa_persistem_sem_gravar_chave(self):
        with tempfile.TemporaryDirectory() as td,mock.patch.object(ia,'pasta_config',return_value=pathlib.Path(td)):
            ia._registrar_pausa(ia.MODELO,'cota')
            self.assertGreater(ia._pausa_modelo(ia.MODELO),ia.time.time()+3500)
            self.assertEqual(0o600,(pathlib.Path(td)/'pausas-modelos.json').stat().st_mode&0o777)

    def test_distingue_cota_tempo_e_login(self):
        self.assertEqual('cota',ia._falha_cli('RESOURCE_EXHAUSTED quota exceeded').tipo)
        self.assertEqual('tempo',ia._falha_cli('print_timeout').tipo)
        self.assertEqual('autenticacao',ia._falha_cli('401 unauthorized').tipo)

    def test_esquema_gemini_sem_enum_nulo_mantem_validacao_local(self):
        self.assertNotIn('enum',ia.esquema_transporte(ia.MODELO_GEMINI)['properties']['tipo_documento'])
        self.assertIn(None,ia.esquema_transporte(ia.MODELO)['properties']['tipo_documento']['enum'])
        r={c:None for c in ia.provas.CAMPOS}
        r.update(tipo_documento='tipo inventado',autores=[],evidencias=[],observacoes=[])
        with self.assertRaisesRegex(ValueError,'tipo de material'):
            ia.validar_envelope(json.dumps({'status':'SUCCESS','structured_output':r}))

    def test_reabrir_app_nao_perde_motivo_de_pausa_autenticacao(self):
        with tempfile.TemporaryDirectory() as td,mock.patch.object(ia,'pasta_config',return_value=pathlib.Path(td)):
            ia._registrar_pausa(ia.MODELO,'autenticacao')
            self.assertEqual('autenticacao',ia._tipo_pausa(ia.MODELO))

    def test_desativar_claude_nao_apaga_reserva_configurada(self):
        with tempfile.TemporaryDirectory() as td,mock.patch.object(ia,'pasta_config',return_value=pathlib.Path(td)):
            ia.configurar_reserva(True)
            self.assertTrue(ia.configurar(False)['gemini_reserva'])


if __name__=='__main__':unittest.main()
