# Engenharia do projeto — transformar o preparo de livros em aplicativo

## Objetivo maior

Transformar o conjunto atual de scripts do preparo de livros em um aplicativo
instalável, utilizável por voluntários, primeiro no macOS e depois no Windows.

O produto final deve permitir que uma pessoa não técnica:

- coloque livros, documentos, revistas, teses e artigos em uma entrada;
- execute o preparo;
- revise conflitos visualmente;
- envie o que estiver pronto para o Biblio;
- libere espaço local depois do cadastro;
- trabalhe com segurança, sem apagar originais antes da hora e sem duplicar
  cadastros.

## Nome provisório do produto

**Biblio Preparador**

Nome descritivo interno:

**Preparador Local do Acervo PIB Curitiba**

## Situação atual

Hoje já existe um sistema funcional, mas ele ainda é um conjunto de ferramentas
locais acionadas principalmente pelo arquivo:

```text
99-FERRAMENTAS/LIVROS.command
```

O sistema já faz:

- recebe materiais em `livros/00-ENTRADA`;
- converte formatos para PDF quando possível;
- faz ou corrige OCR;
- extrai capa;
- lê código de barras;
- procura ISBN;
- lê CIP/ficha catalográfica;
- consulta fontes bibliográficas;
- usa Open Library, Google Books, CBL, BnF, Internet Archive, Crossref,
  OpenAlex, CORE, OATD, Estante Virtual e Amazon conforme o caso;
- classifica livros, documentos, artigos, revistas, teses e dissertações;
- separa revisão, prontos, duplicados e descartes;
- possui bancada visual de revisão;
- envia pela API do Biblio;
- consulta duplicidade antes de enviar;
- guarda chave no Chaves do macOS;
- libera espaço de cadastrados/duplicados/descartes;
- registra aprendizados em listas incrementais.

O problema não é falta de inteligência do motor. O problema agora é transformar
isso em produto instalável e operável por outras pessoas.

## Princípio central de engenharia

Não devemos reescrever o motor do zero.

A primeira versão do aplicativo deve **embrulhar, organizar e estabilizar** o
que já funciona.

Do ponto de vista do operador, o aplicativo deve funcionar como um
**assistente guiado**:

1. oferecer uma bandeja de importação para selecionar arquivos, importar uma
   pasta local inteira ou abrir a pasta de entrada;
2. iniciar a preparação;
3. perguntar se deseja enviar o que ficou pronto;
4. perguntar se deseja liberar espaço;
5. abrir a revisão do que ficou pendente;
6. ao final da revisão, perguntar novamente se deseja enviar e limpar.

Portanto, o app não deve ser apenas uma cópia visual do menu antigo. O menu
continua existindo como base técnica, mas a experiência principal deve seguir o
fluxo natural do trabalho.

Arquitetura desejada:

```text
Aplicativo visual
  └─ chama o motor local
       ├─ biblioteca-local.py
       ├─ preparar-livros.py
       ├─ enviar-livro-api.py
       ├─ revisao-visual.py
       ├─ consultar_fontes_bibliograficas.py
       ├─ consultar-web-navegador.py
       └─ gerenciar-grobid.py
```

O motor continua testável pela linha de comando. A interface visual passa a ser
a camada de operação.

## Fases do projeto

### Fase 1 — aplicativo instalável para macOS

Objetivo:

- transformar o sistema atual em um app local para Mac;
- com instalador;
- com interface mais simples;
- com dependências verificadas automaticamente;
- mantendo o motor atual.

Resultado esperado:

- um voluntário recebe um instalador;
- instala o aplicativo;
- escolhe ou cria a biblioteca local;
- configura a chave da API;
- processa um lote;
- revisa pendências;
- envia materiais prontos;
- libera espaço.

Roteiro operacional:

- [Roteiro da fase 1 — aplicativo Mac instalável](APP-MAC-FASE1-ROTEIRO.md)

### Fase 2 — distribuição controlada para voluntários no macOS

Objetivo:

- sair do uso apenas nesta máquina;
- instalar em 2 a 5 Macs de voluntários;
- medir dificuldades reais;
- ajustar interface, logs, mensagens e instalador.

Resultado esperado:

- pacote estável para voluntários Mac;
- documentação curta de uso;
- rotina de suporte;
- forma de atualizar o app sem reinstalação manual complexa.

### Fase 3 — aplicativo para Windows

Objetivo:

- portar a mesma lógica para Windows;
- substituir ou abstrair dependências que são específicas do macOS;
- criar instalador Windows.

Resultado esperado:

- app Windows funcional;
- instalador Windows;
- uso da mesma API do Biblio;
- biblioteca local com estrutura compatível;
- OCR e capa resolvidos por alternativa ao Apple Vision.

### Fase 4 — integração opcional com serviços centrais

Objetivo:

- usar GROBID central via OpenVPN;
- futuramente considerar proxy pelo Biblio;
- talvez centralizar parte da fila, logs ou auditoria.

Documentos relacionados:

- [GROBID central via OpenVPN](GROBID-CENTRAL-OPENVPN.md)
- [Engenharia da fase 1 do GROBID](GROBID-FASE1-ENGENHARIA.md)

## Fase 1 em detalhe — Mac instalável

### Resultado da fase 1

A fase 1 termina quando existir um aplicativo Mac instalável que:

- abre por clique;
- não exige que o operador entenda terminal;
- mostra o estado da biblioteca;
- executa o ciclo completo;
- abre a bancada de revisão;
- envia tudo que estiver pronto;
- libera espaço com confirmação;
- verifica dependências;
- protege a chave da API;
- gera relatório de erro compreensível.

## Arquitetura da fase 1

```text
Biblio Preparador.app
  ├─ Interface local
  ├─ Motor Python existente
  ├─ Verificador de dependências
  ├─ Configurações do usuário
  ├─ Logs de execução
  ├─ Acesso ao Chaves do macOS
  └─ Biblioteca escolhida pelo usuário
```

O aplicativo não deve guardar o acervo dentro do pacote `.app`.

O acervo deve ficar em uma pasta escolhida pelo usuário, por exemplo:

```text
~/Biblioteca Biblio
```

ou em local de nuvem, se o usuário desejar.

## Decisões técnicas da fase 1

### 1. Motor preservado

O motor atual continua sendo Python.

Motivo:

- já foi testado com muitos lotes reais;
- contém regras aprendidas na prática;
- tem testes automatizados;
- já conversa com a API do Biblio;
- já possui integração com OCR, fontes bibliográficas e revisão.

### 2. Interface por cima do motor

A interface deve chamar comandos internos do motor e mostrar progresso.

Não devemos duplicar a lógica na interface.

Se a interface e o motor tiverem duas versões da mesma regra, elas vão divergir.

### 3. Estrutura de dados preservada

A estrutura atual de biblioteca deve ser preservada:

```text
00-ENTRADA
10-REVISAO
15-TESES-DISSERTACOES-E-TRABALHOS
16-ARTIGOS-E-DOCUMENTOS
17-REVISTAS-E-PERIODICOS
18-EXCECOES-DE-TAMANHO
19-DESCARTE
20-PRONTOS
30-ARQUIVADOS
_controle
_metadados
_capas
_preparados-envio
```

Motivo:

- já funciona;
- facilita retomada;
- permite auditoria;
- permite abrir arquivos no Finder;
- reduz risco de perda.

### 4. Configuração por usuário

Cada instalação deve ter:

- pasta da biblioteca;
- chave da API no Chaves do macOS;
- preferência de internet;
- preferência de GROBID;
- limites de tamanho;
- logs locais.

Essas configurações não devem ficar hardcoded no código.

### 5. Segurança antes de automação

O app deve continuar evitando:

- reenviar item incerto;
- apagar arquivo não cadastrado;
- cadastrar duplicata sem consulta prévia;
- sobrescrever revisão manual;
- aceitar ficha vazia como pronta.

## Componentes do app Mac

### 1. Tela inicial

Funções:

- mostrar biblioteca selecionada;
- mostrar quantidade em entrada, revisão, pronto, cadastrado e descarte;
- mostrar se API está configurada;
- mostrar se internet está disponível;
- mostrar se GROBID está disponível;
- botão para escolher/criar biblioteca.

### 2. Tela de preparo

Funções:

- executar ciclo completo;
- executar ciclo sem internet;
- reprocessar revisão;
- mostrar etapa atual;
- mostrar arquivo atual;
- mostrar porcentagem;
- mostrar bytes/tamanho quando houver conversão, OCR ou compactação;
- permitir cancelar com segurança.

### 3. Tela de revisão

Baseada na bancada visual atual.

Funções obrigatórias:

- mostrar PDF ativo;
- mostrar capa;
- permitir navegar páginas;
- permitir abrir PDF fora do app;
- editar metadados;
- consultar por ISBN;
- substituir capa por arquivo local;
- substituir capa por URL;
- confirmar divergência;
- salvar e validar;
- salvar e ir ao próximo;
- encerrar com tela de conclusão.

Regra:

- ao salvar/validar, o item deve sair da revisão e ir para a fila correta.

### 4. Tela de envio

Funções:

- atualizar filas;
- mostrar quantos livros, documentos, acadêmicos e revistas estão prontos;
- enviar tudo;
- enviar por tipo;
- confirmar envio público;
- mostrar resposta da API;
- reconciliar duplicatas;
- pular erro individual e continuar o lote;
- no final, checar se item incerto foi realmente cadastrado.

### 5. Tela de limpeza

Funções:

- simular liberação de espaço;
- mostrar o que será removido;
- confirmar;
- mover para Lixeira;
- limpar pastas vazias;
- preservar metadados, hashes, IDs e histórico.

### 6. Tela de diagnóstico

Funções:

- verificar dependências;
- testar API;
- testar internet;
- testar GROBID;
- abrir pasta de logs;
- gerar pacote de suporte.

## Dependências no Mac

### Essenciais

- Python próprio ou empacotado;
- poppler;
- zbar;
- ocrmypdf;
- Ghostscript;
- Apple Vision bridge;
- requests;
- bibliotecas Python do projeto;
- acesso ao Chaves do macOS.

### Opcionais

- Playwright para Estante Virtual/Amazon;
- LibreOffice para Word, PowerPoint e alguns formatos de documento;
- GROBID local ou central;
- spaCy NER.

## Estratégia para dependências

Há três caminhos possíveis:

### Caminho A — instalador leve com verificador

O app instala o mínimo e orienta a instalação das dependências externas.

Vantagens:

- menor instalador;
- mais simples de atualizar.

Desvantagens:

- voluntário pode travar em Homebrew, permissões ou dependências.

### Caminho B — instalador com tudo que for possível embutido

O app leva Python, bibliotecas e binários auxiliares sempre que a licença e o
tamanho permitirem.

Vantagens:

- melhor experiência para voluntários;
- menos suporte.

Desvantagens:

- instalador maior;
- mais trabalho de empacotamento;
- precisa cuidar de licenças e atualizações.

### Caminho C — híbrido

Recomendado para a fase 1.

O app leva o motor Python e dependências Python controladas. Ferramentas grandes
ou externas são verificadas e instaladas/orientadas separadamente.

Exemplo:

- app leva motor e interface;
- app verifica poppler, zbar, Ghostscript, LibreOffice;
- se faltar algo, mostra botão ou instrução clara;
- Apple Vision usa recurso nativo do macOS;
- GROBID pode ser local ou central.

## Instalador Mac

Entregáveis desejados:

- `.app` para abrir por clique;
- `.dmg` ou `.pkg` para instalação;
- pasta de aplicativo em `/Applications`;
- assistente inicial para escolher biblioteca;
- verificação de permissões;
- criação de atalhos se necessário.

Etapas futuras:

- assinatura do app;
- notarização pela Apple;
- atualização automática ou semiautomática.

Na fase 1 interna, assinatura/notarização podem ficar para depois, desde que os
voluntários piloto saibam liberar o app nas permissões do macOS.

## Organização dos dados do usuário

Separar claramente:

| Tipo | Local |
|---|---|
| Aplicativo | `/Applications/Biblio Preparador.app` |
| Biblioteca/acervo | pasta escolhida pelo usuário |
| Configurações | pasta de suporte do usuário |
| Chave API | Chaves do macOS |
| Logs | pasta de suporte do usuário ou `_controle/logs` |
| Caches | pasta de suporte, não misturados ao acervo |

O app nunca deve depender de estar dentro do Dropbox.

## Compatibilidade com a instalação atual

A instalação atual deve ser tratada como ambiente de desenvolvimento e acervo
real.

O app precisa conseguir apontar para a biblioteca já existente sem recriá-la.

Antes de qualquer migração:

- fazer backup de `_controle`;
- preservar `revisoes-manuais.json`;
- preservar catálogo;
- preservar filas;
- preservar históricos de envio;
- preservar listas de aprendizado.

## Testes da fase 1

### Testes técnicos

- rodar testes Python;
- validar importações;
- validar menu atual;
- validar bancada visual;
- validar envio em simulação;
- validar consulta à API;
- validar liberação de espaço em simulação;
- validar reprocessamento de revisão.

### Testes com lote real

Lote mínimo:

- 5 livros com ISBN;
- 5 livros antigos sem ISBN;
- 3 documentos;
- 3 artigos;
- 3 teses/dissertações;
- 2 revistas;
- 2 arquivos Word;
- 1 PowerPoint;
- 1 EPUB;
- 2 duplicatas conhecidas.

### Critérios de aceite

A fase 1 só deve ser considerada concluída quando:

- o app abre por clique;
- instala em um Mac limpo ou quase limpo;
- identifica dependências faltantes;
- processa lote real;
- permite revisão visual;
- envia materiais prontos;
- não reenvia duplicatas;
- libera espaço corretamente;
- gera logs compreensíveis;
- recupera de falhas sem perder revisão manual.

## Roteiro de execução da fase 1

### Etapa 1 — congelar o motor atual

Objetivo:

- definir uma versão-base do motor antes da embalagem.

Ações:

- rodar testes;
- corrigir falhas críticas;
- registrar commit;
- documentar comandos principais;
- separar código essencial de scripts antigos de mineração da revista.

Entregável:

- versão-base do motor.

### Etapa 2 — separar núcleo, interface e dados

Objetivo:

- impedir que o app dependa do layout atual de desenvolvimento.

Ações:

- identificar módulos do núcleo;
- identificar arquivos de configuração;
- identificar arquivos de aprendizado;
- identificar dados do usuário;
- criar camada única de configuração da biblioteca.

Entregável:

- mapa de arquivos do produto.

### Etapa 3 — criar interface inicial do app Mac

Objetivo:

- substituir o menu de terminal por uma janela.

Ações:

- tela inicial;
- botões equivalentes aos comandos principais;
- área de progresso;
- área de logs amigáveis;
- abertura da bancada visual;
- retorno ao menu principal após revisão.

Decisão de layout aprovada em 13/09/2026:

- o app deve seguir um fluxo assistido em cinco etapas: **Importar**,
  **Preparar**, **Enviar**, **Revisar** e **Concluir**;
- a preparação deve trocar de tela quando iniciar, mostrando progresso,
  atividade em tempo real e o arquivo atual em um único centro de progresso;
- a tela de envio deve abrir automaticamente ao final da preparação quando
  houver itens prontos, além de permanecer acessível pelo passo **Enviar**;
- a bancada de revisão deve reaproveitar a versão visual já testada e aprovada,
  com três colunas fixas: lista à esquerda, PDF no centro e metadados à
  direita;
- a bancada de revisão não deve empilhar as colunas em telas menores; se faltar
  largura, deve usar rolagem horizontal;
- a única mudança visual obrigatória na bancada aprovada é adotar fundo claro
  compatível com a paleta do app;
- o operador deve conseguir voltar para **Enviar** ou avançar para
  **Concluir** por uma faixa discreta, sem alterar a estrutura da bancada.

Arquivos de referência do protótipo aprovado:

- `/Users/piraginejr/.codex/visualizations/2026/07/27/019fa273-6b82-7741-802f-cb5b4cb585b1/biblio-app-mockups-lateral.html`
- `/Users/piraginejr/.codex/visualizations/2026/07/27/019fa273-6b82-7741-802f-cb5b4cb585b1/biblio-revisao-bancada-aprovada.html`

Entregável:

- protótipo funcional local.

### Etapa 4 — empacotar dependências

Objetivo:

- fazer o app rodar fora do ambiente de desenvolvimento.

Ações:

- definir Python embutido ou ambiente próprio;
- empacotar dependências Python;
- verificar binários externos;
- criar verificador de dependências;
- criar mensagens de correção.

Entregável:

- app executável fora da pasta atual.

### Etapa 5 — criar instalador Mac

Objetivo:

- permitir instalação por voluntário.

Ações:

- gerar `.app`;
- gerar `.dmg` ou `.pkg`;
- criar assistente inicial;
- testar instalação em outra pasta/usuário;
- documentar permissões macOS.

Entregável:

- primeiro instalador Mac.

### Etapa 6 — piloto controlado

Objetivo:

- testar com pessoas reais e lotes reais.

Ações:

- instalar em 1 ou 2 Macs;
- processar lote pequeno;
- registrar dificuldades;
- medir aproveitamento;
- ajustar mensagens e interface.

Entregável:

- relatório do piloto.

### Etapa 7 — versão Mac 1.0 interna

Objetivo:

- entregar app Mac utilizável pelos voluntários.

Ações:

- corrigir problemas do piloto;
- criar documentação curta;
- definir rotina de atualização;
- definir canal de suporte;
- criar pacote final.

Entregável:

- Biblio Preparador Mac 1.0 interno.

## Engenharia futura do Windows

O Windows não deve ser apenas uma cópia cega do Mac.

Diferenças importantes:

- não há Apple Vision nativo;
- Chaves do macOS deve virar Windows Credential Manager;
- `.command` não existe;
- permissões e caminhos são diferentes;
- LibreOffice e poppler têm instalação diferente;
- OCR terá outro motor ou serviço;
- instalador será `.msi` ou `.exe`;
- atalhos e atualizações seguem padrão Windows.

Para permitir Windows, o app deve separar provedores:

| Função | macOS | Windows |
|---|---|---|
| OCR visual | Apple Vision | a definir |
| chave segura | Chaves do macOS | Windows Credential Manager |
| abrir PDF | Preview/Chrome/app padrão | app padrão |
| conversão Office | LibreOffice | LibreOffice ou motor Windows |
| instalador | DMG/PKG | MSI/EXE |
| GROBID | local/central | preferencialmente central |

## Decisão importante para Windows

Para Windows, o GROBID central via OpenVPN pode ser ainda mais importante,
porque evita instalar uma pilha acadêmica pesada em cada máquina.

O mesmo vale para OCR avançado, se no futuro decidirmos usar um serviço central.

## Riscos do projeto

| Risco | Mitigação |
|---|---|
| Reescrever demais e perder regras aprendidas | manter motor atual e cobrir com testes |
| Voluntário não conseguir instalar dependências | instalador híbrido e diagnóstico claro |
| Perder revisões manuais | preservar `_controle` e testar migração |
| Duplicar cadastros | consulta prévia API e trava por hash |
| App parecer travado | progresso por etapa e por arquivo |
| Diferença Mac/Windows quebrar OCR | camada de provedores |
| GROBID consumir servidor | VPN, limites e fallback |
| Dropbox/nuvem interferir nos arquivos | separar app, cache e biblioteca |

## Métricas de sucesso

### Técnicas

- taxa de instalação bem-sucedida;
- tempo médio por lote;
- quantidade de travamentos;
- quantidade de itens enviados sem intervenção;
- quantidade de itens em revisão;
- quantidade de duplicatas evitadas;
- tempo médio de revisão manual.

### Operacionais

- voluntário consegue usar sem terminal;
- operador entende o que aconteceu;
- suporte consegue diagnosticar erro por log;
- app permite retomar depois de interrupção;
- arquivos locais podem ser liberados com segurança.

## O que não podemos perder do sistema atual

- aprendizado incremental;
- listas de títulos ruidosos;
- lista de autores ruidosos;
- periódicos conhecidos;
- revisões manuais por hash;
- consulta de duplicidade na API;
- fila preservada;
- simulação antes de apagar;
- confirmação antes de enviar;
- separação por tipo de material;
- bancada visual.

## Próximo documento necessário

Depois deste plano-mestre, o próximo documento deve ser:

```text
docs/APP-MAC-FASE1-ROTEIRO.md
```

Ele deve transformar a fase 1 em tarefas executáveis, na ordem:

1. inventário do motor;
2. mapa de arquivos;
3. escolha da tecnologia da interface Mac;
4. protótipo;
5. empacotamento;
6. instalador;
7. piloto.

## Decisão atual

O caminho recomendado é:

1. preservar o motor Python atual;
2. criar app Mac como camada visual e instalável;
3. usar instalador híbrido na primeira fase;
4. tratar GROBID central como serviço opcional dentro do app;
5. só depois iniciar a engenharia Windows.

Essa abordagem reduz risco porque aproveita o que já foi validado com lotes
reais e evita jogar fora meses de aprendizado do preparo de livros.
