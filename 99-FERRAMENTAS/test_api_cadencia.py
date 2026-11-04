import importlib.util,pathlib,unittest
from unittest import mock
s=importlib.util.spec_from_file_location('api_cadencia',pathlib.Path(__file__).with_name('enviar-livro-api.py'))
a=importlib.util.module_from_spec(s);s.loader.exec_module(a)


class CadenciaTest(unittest.TestCase):
    def resposta(self,status,espera=''):
        r=mock.Mock(status_code=status,headers={'Retry-After':espera});r.json.return_value={'mensagem':'Tente novamente em 3s'};return r

    def test_429_aguarda_e_repete_apenas_consulta(self):
        sess=mock.Mock();sess.post.side_effect=[self.resposta(429,'4'),self.resposta(200)]
        dormir=mock.Mock();r=a.post_consulta_com_espera(sess,'segredo',{'action':'consultar_livro'},dormir)
        self.assertEqual(200,r.status_code);dormir.assert_called_once_with(4)
        self.assertEqual(2,sess.post.call_count)
        self.assertTrue(all('files' not in x.kwargs for x in sess.post.call_args_list))

    def test_limite_persistente_e_operacional_sem_repeticao_infinita(self):
        sess=mock.Mock();sess.post.return_value=self.resposta(429)
        with self.assertRaises(a.ConsultaTemporariamenteIndisponivel):
            a.post_consulta_com_espera(sess,'segredo',{'action':'consultar_livro'},mock.Mock())
        self.assertEqual(4,sess.post.call_count)

    def test_nunca_aplica_retry_a_cadastro_ou_edicao(self):
        for action in ('cadastrar_livro','atualizar_livro'):
            sess=mock.Mock()
            with self.assertRaises(ValueError):a.post_consulta_com_espera(sess,'x',{'action':action})
            sess.post.assert_not_called()


if __name__=='__main__':unittest.main()
