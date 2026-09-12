# Regras operacionais para o Codex neste projeto

- Ao executar Python nesta pasta do Dropbox/macOS, sempre definir `PYTHONPYCACHEPREFIX` para uma pasta temporária gravável, por exemplo `/private/tmp/biblio-pycache`. Isso evita falhas de validação causadas pela tentativa do Python de gravar bytecode em `~/Library/Caches/com.apple.python/...`.
- Evitar buscas amplas e recursivas acima da raiz do projeto, especialmente em árvores do Dropbox/iCloud. Preferir buscas com profundidade limitada ou diretórios específicos.
- Ao validar mudanças no aplicativo, preferir comandos no formato:
  `PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache python3 -m py_compile ...`
  e
  `PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache python3 -m unittest ...`
