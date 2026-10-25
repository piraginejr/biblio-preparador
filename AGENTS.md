# Regras operacionais para o Codex neste projeto

- Ao executar Python nesta pasta do Dropbox/macOS, sempre definir `PYTHONPYCACHEPREFIX` para uma pasta temporária gravável, por exemplo `/private/tmp/biblio-pycache`. Isso evita falhas de validação causadas pela tentativa do Python de gravar bytecode em `~/Library/Caches/com.apple.python/...`.
- Evitar buscas amplas e recursivas acima da raiz do projeto, especialmente em árvores do Dropbox/iCloud. Preferir buscas com profundidade limitada ou diretórios específicos.
- Ao validar mudanças no aplicativo, preferir comandos no formato:
  `PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache python3 -m py_compile ...`
  e
  `PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache python3 -m unittest ...`
- Mudanças no motor só estão entregues ao app Mac depois de reconstruir o pacote e comparar os hashes de `99-FERRAMENTAS` no projeto, em `dist/Biblio Preparador.app/Contents/Resources/pacote-base` e na instalação ativa em Application Support. Use `packaging/macos/verificar_motor.py --comparar`. O app copia o pacote-base sobre a instalação em cada abertura; atualizar apenas Application Support perde a mudança na abertura seguinte.
- Não interromper OCR/preparação ativa para instalar atualização. Uma página recarregada não recarrega módulos Python do servidor: fechar/reabrir o app após concluir a tarefa e conferir a versão em `/api/health`.
- Correções de cadastros remotos preservam ID e diário original. Reenvio de substituição requer o ID antigo explicitamente e deve registrar o par antigo/novo; nunca reabrir automaticamente um cadastro confirmado.
