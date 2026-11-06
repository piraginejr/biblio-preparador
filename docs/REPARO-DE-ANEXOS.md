# Reparo de anexos perdidos

Este serviço é separado da preparação e das filas de novos cadastros. Preserva
o ID, a capa, a autoria e os demais metadados. Não faz OCR ou conversão automática.
No momento é uma ferramenta operacional, ainda sem botão na interface visual.

## Conferência antes do envio

1. Cruzar o relatório do administrador com o nome original do arquivo.
2. Conferir título, autoria, volume/edição e integridade do conteúdo recuperado.
3. Identificar o ID atual: números nos nomes de arquivos antigos não são IDs atuais.
4. Arquivo existente no servidor pode precisar apenas de correção de vínculo pelo
   gestor. A API documentada não oferece associação direta a um caminho existente.
5. Não substituir automaticamente registros apenas porque têm títulos semelhantes.
   Arquivos vazios, corrompidos, homônimos ou sem identificação ficam pendentes.

## Plano e execução

Um plano JSON contém `itens`, cada um com `id` inteiro, `titulo`, `pdf` (caminho
absoluto ou relativo ao plano), `sha256`, `confirmado: true` e `justificativa` da
identificação. Plano e diário ficam fora do Git, junto da auditoria do lote.

```sh
PYTHONPYCACHEPREFIX=/private/tmp/biblio-pycache python3 99-FERRAMENTAS/reparar_acervo.py PLANO.json --diario DIARIO.json
```

Sem `--enviar`, somente valida e simula. Com `--enviar`, consulta o ID e título,
registra a intenção antes da transferência e manda exclusivamente `action`, `id`
e `arquivo_digital` para `atualizar_livro`. A chave vem do Chaves do macOS.

O diário é exclusivo do reparo. Os recibos originais de cadastro e as filas normais
não são modificados. Há trava contra execuções simultâneas com o mesmo diário.
Uma tentativa confirmada não se repete. Qualquer tentativa incerta ou recusada
exige conferência antes de nova autorização; não há repetição automática.

O recibo confirma a atualização no mesmo ID. A API atual não fornece hash remoto
do anexo: abertura/download pelo site ou conferência pelo gestor ainda é necessária
para atestar a integridade da cópia armazenada. Não liberar os arquivos recuperados
somente com base no recibo.
