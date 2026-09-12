# Roteiro da fase 1 — aplicativo Mac instalável

## Objetivo da fase 1

Transformar o sistema atual de preparo de livros em um aplicativo Mac
instalável, sem reescrever o motor que já funciona.

O foco desta fase é sair de:

```text
abrir 99-FERRAMENTAS/LIVROS.command
```

para:

```text
abrir Biblio Preparador.app
```

com interface visual, diagnóstico, progresso e instalador.

## Resultado esperado

Ao final da fase 1, devemos ter:

- `Biblio Preparador.app`;
- instalador `.dmg` ou `.pkg`;
- primeira tela de configuração;
- seleção/criação da biblioteca local;
- botões para as operações principais;
- bancada visual integrada;
- logs acessíveis;
- verificador de dependências;
- envio pela API;
- liberação de espaço;
- documentação curta para voluntários.

## Estratégia

Preservar o motor atual.

O aplicativo visual será uma camada de controle por cima dos módulos existentes.

O motor continua podendo ser testado por comandos internos, mas o voluntário
não precisará vê-los.

## Etapa 0 — preparar a base antes do app

### Objetivo

Garantir que o motor atual esteja suficientemente estável para ser empacotado.

### Tarefas

- [ ] Rodar testes automatizados.
- [ ] Corrigir falhas críticas.
- [ ] Confirmar que o comando 1 processa um lote pequeno.
- [ ] Confirmar que o comando 17 abre a revisão visual.
- [ ] Confirmar que o comando 16 envia tudo que está pronto.
- [ ] Confirmar que o comando 12 libera espaço corretamente.
- [ ] Confirmar que revisões manuais sobrevivem ao reprocessamento.
- [ ] Criar commit de estabilização.

### Critério de aceite

O sistema atual deve funcionar pelo menu antes de ser transformado em app.

## Etapa 1 — inventário do motor

### Objetivo

Separar claramente o que é motor do produto, dado do usuário, cache,
dependência externa e ferramenta antiga.

### Tarefas

- [ ] Listar módulos essenciais.
- [ ] Listar módulos auxiliares.
- [ ] Listar scripts históricos que não entram no app.
- [ ] Listar arquivos JSON de aprendizado.
- [ ] Listar pastas do acervo.
- [ ] Listar arquivos de controle.
- [ ] Listar dependências Python.
- [ ] Listar dependências externas do sistema.

### Entregável

Documento:

```text
docs/APP-MAC-INVENTARIO.md
```

## Etapa 2 — definir a tecnologia da interface Mac

### Opções possíveis

#### Opção A — app nativo simples

Interface nativa para macOS chamando o motor Python.

Vantagens:

- experiência mais parecida com aplicativo Mac;
- melhor integração com arquivos, permissões e Chaves do macOS.

Desvantagens:

- mais trabalho de desenvolvimento visual;
- mais cuidado com empacotamento.

#### Opção B — app web local empacotado

O app abre uma janela local, parecida com a bancada visual atual.

Vantagens:

- reaproveita bastante da bancada visual;
- mais fácil portar depois para Windows;
- uma interface web pode ser compartilhada entre sistemas.

Desvantagens:

- precisa empacotar servidor local;
- aparência pode parecer menos “nativa”.

#### Opção C — wrapper inicial do menu atual

Primeira versão apenas coloca botões sobre os comandos existentes.

Vantagens:

- mais rápido;
- menor risco;
- útil para piloto.

Desvantagens:

- menos bonito;
- ainda não resolve toda a experiência do usuário.

### Recomendação

Usar uma abordagem progressiva:

1. começar pela opção C para empacotar o fluxo real;
2. evoluir para opção B, reaproveitando a bancada visual;
3. só considerar nativo completo se houver necessidade.

Essa escolha acelera a entrega e facilita o futuro Windows.

## Etapa 3 — criar camada única de comandos do motor

### Objetivo

Evitar que a interface chame diretamente dezenas de scripts diferentes.

Criar uma camada única, por exemplo:

```text
99-FERRAMENTAS/biblio_app_service.py
```

Essa camada deve oferecer operações de alto nível:

- status da biblioteca;
- verificar dependências;
- processar ciclo completo;
- processar ciclo sem internet;
- reprocessar revisão;
- atualizar filas;
- enviar tudo;
- enviar por tipo;
- liberar espaço;
- abrir revisão visual;
- testar API;
- testar GROBID;
- abrir logs.

### Critério de aceite

A interface visual deve chamar essa camada, e não conhecer detalhes internos de
cada script.

## Etapa 4 — configuração do app

### Objetivo

Tirar caminhos fixos do ambiente de desenvolvimento.

### Configurações necessárias

- pasta da biblioteca;
- URL da API do Biblio;
- uso de internet;
- uso de GROBID;
- URL do GROBID central, se houver;
- limite de tamanho;
- local dos logs;
- preferências de envio.

### Armazenamento sugerido

Configurações comuns:

```text
~/Library/Application Support/Biblio Preparador/config.json
```

Chave da API:

```text
Chaves do macOS
```

## Etapa 5 — interface inicial

### Tela inicial

Deve mostrar:

- biblioteca selecionada;
- entrada;
- revisão;
- prontos;
- cadastrados;
- duplicados;
- descartes;
- estado da API;
- estado do GROBID;
- estado das dependências.

### Botões principais

- Preparar novo lote.
- Reavaliar revisão.
- Abrir revisão visual.
- Enviar tudo pronto.
- Enviar por tipo.
- Liberar espaço.
- Diagnóstico.
- Configurações.

### Progresso

O app deve mostrar:

- etapa atual;
- arquivo atual;
- porcentagem quando disponível;
- contador de itens;
- mensagem clara quando pular uma camada;
- erro recuperável sem parecer travamento.

## Etapa 6 — logs e suporte

### Objetivo

Permitir entender o que aconteceu sem depender da memória do operador.

### Funções

- ver último processamento;
- abrir pasta de logs;
- gerar pacote de suporte;
- copiar resumo técnico;
- mostrar erros recentes em linguagem simples.

### Pacote de suporte

Deve conter:

- versão do app;
- sistema operacional;
- dependências encontradas;
- últimos logs;
- status da biblioteca;
- erros recentes;
- nunca incluir chave da API;
- nunca incluir PDFs completos sem confirmação.

## Etapa 7 — empacotar Python e dependências

### Objetivo

Fazer o aplicativo rodar fora da pasta de desenvolvimento.

### Tarefas

- [ ] Definir ambiente Python do app.
- [ ] Congelar dependências Python.
- [ ] Incluir módulos do motor.
- [ ] Incluir listas de aprendizado.
- [ ] Incluir arquivos Swift/binários do Vision.
- [ ] Criar verificador de binários externos.
- [ ] Testar em pasta limpa.

### Atenção

Não colocar dentro do app:

- PDFs;
- acervo;
- caches grandes;
- logs antigos;
- chaves;
- arquivos temporários.

## Etapa 8 — instalador Mac

### Objetivo

Criar um pacote que possa ser entregue a voluntários.

### Primeira versão

Pode ser:

- `.dmg` com o app;
- instrução “arraste para Aplicativos”;
- primeira execução cria configuração.

### Versão posterior

Pode evoluir para:

- `.pkg`;
- assinatura;
- notarização;
- atualização automática.

### Testes do instalador

- instalar em outra pasta;
- abrir sem terminal;
- escolher biblioteca;
- configurar API;
- processar lote pequeno;
- remover app sem remover biblioteca.

## Etapa 9 — piloto Mac

### Lote de teste

Usar um lote misto:

- livros com ISBN;
- livros sem ISBN;
- livros antigos;
- documentos;
- artigos;
- teses/dissertações;
- revistas;
- Word;
- PowerPoint;
- EPUB;
- duplicatas.

### Métricas

Registrar:

- tempo de instalação;
- dependências faltantes;
- erros;
- quantidade processada;
- quantidade pronta;
- quantidade em revisão;
- quantidade enviada;
- duplicatas evitadas;
- tempo de revisão manual.

## Etapa 10 — Mac 1.0 interno

### Entregáveis

- instalador;
- documentação curta;
- relatório do piloto;
- lista de problemas conhecidos;
- rotina de atualização;
- rotina de suporte.

### Critério de conclusão

Um voluntário consegue preparar e enviar um lote real sem usar terminal.

## Ordem recomendada de execução agora

1. Criar inventário do motor.
2. Criar camada única de serviço do app.
3. Adaptar a bancada visual para ser chamada como módulo do app.
4. Criar protótipo de tela inicial.
5. Criar diagnóstico de dependências.
6. Empacotar protótipo como `.app`.
7. Testar em pasta limpa.
8. Criar `.dmg`.
9. Fazer piloto.

## Decisões pendentes

| Decisão | Opção recomendada inicial |
|---|---|
| Tecnologia da interface | web local empacotada ou wrapper simples |
| Instalador | `.dmg` na primeira versão |
| Python | ambiente próprio empacotado |
| OCR no Mac | Apple Vision mantido |
| GROBID | opcional, local ou central |
| Atualização | manual no piloto |
| Windows | somente depois do Mac estabilizado |

## Relação com o GROBID

O GROBID não é o centro do aplicativo.

Ele é uma camada especializada para material acadêmico dentro do app.

Na fase Mac, o app deve aceitar:

- GROBID desligado;
- GROBID local;
- GROBID central via OpenVPN.

Se o GROBID falhar, o preparo continua.

## Relação com Windows

Tudo que for construído na fase Mac deve evitar depender demais de recursos
exclusivos do Mac, exceto onde isso for inevitável.

Especialmente:

- separar OCR como provedor;
- separar cofre de chave como provedor;
- separar abertura de arquivos como provedor;
- separar instalador como etapa própria.

Essa preparação torna a fase Windows mais barata.
