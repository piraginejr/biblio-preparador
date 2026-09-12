# Engenharia da fase 1 — GROBID central para o Biblio

## Finalidade da fase 1

Implantar e validar um serviço GROBID central, acessível pelos computadores dos
voluntários através da OpenVPN, sem ainda transformar isso em uma funcionalidade
definitiva do Biblio.

A fase 1 é uma fase de prova controlada. Ela deve responder quatro perguntas:

1. O GROBID roda de modo estável no servidor?
2. O acesso pela OpenVPN é suficiente para proteger o serviço?
3. O aplicativo local consegue usar o GROBID sem travar quando ele falha?
4. A qualidade dos metadados acadêmicos melhora o suficiente para justificar a
   integração definitiva?

## Escopo

### Incluído

- Subir GROBID em contêiner no servidor.
- Restringir o acesso à rede interna da OpenVPN.
- Configurar limpeza defensiva de temporários e logs.
- Criar teste de saúde do serviço.
- Configurar o aplicativo local para usar a URL central.
- Testar com lote pequeno de artigos, teses, dissertações e trabalhos acadêmicos.
- Medir tempo, erros e melhora dos metadados.
- Registrar o resultado da fase 1 em relatório.

### Fora do escopo nesta fase

- Login integrado ao Biblio.
- Tela administrativa no site.
- Fila central de documentos.
- Upload definitivo pelo Biblio.
- Auditoria por usuário.
- Transformar GROBID em serviço público na internet.
- Processar livros comuns por padrão.

Esses itens ficam para fases posteriores.

## Arquitetura da fase 1

```text
Computador do voluntário
  └─ Aplicativo Biblio local
       └─ OpenVPN ativa
            └─ IP interno do servidor
                 └─ Porta interna do GROBID
                      └─ Contêiner GROBID
```

O app local continua sendo o controlador do processo. O GROBID central é apenas
uma camada de enriquecimento de metadados para material acadêmico.

## Decisão técnica principal

O serviço será acessível pelo endereço interno da OpenVPN, não pelo domínio
público do Biblio.

Exemplo de formato esperado:

```text
http://IP_INTERNO_DA_VPN:8070
```

O IP real deve ser preenchido apenas quando formos configurar o servidor.

## Requisitos antes de começar

| Requisito | Situação esperada |
|---|---|
| Servidor com OpenVPN funcionando | já existe |
| IP interno do servidor na VPN conhecido | a confirmar |
| Acesso administrativo ao servidor | necessário |
| Docker ou Podman disponível | a verificar |
| Porta escolhida para GROBID | sugestão: `8070` |
| Firewall configurável | necessário |
| Um Mac de teste conectado à VPN | necessário |
| Lote de teste com 10 materiais acadêmicos | necessário |

## Materiais de teste

O lote de teste deve conter preferencialmente:

- 3 artigos acadêmicos;
- 3 dissertações ou teses;
- 2 trabalhos acadêmicos;
- 2 documentos que parecem acadêmicos, mas não têm metadados claros.

O objetivo não é testar livros comuns. O GROBID é especialmente útil em
estrutura acadêmica: título, autores, resumo, periódico, DOI, instituição e
referências.

## Critério para enviar um arquivo ao GROBID

O app só deve tentar GROBID quando houver indícios de que o material é:

- artigo;
- tese;
- dissertação;
- trabalho acadêmico;
- capítulo acadêmico;
- documento com resumo, palavras-chave, DOI, referências ou instituição.

O app deve evitar GROBID quando o material parecer:

- livro devocional;
- livro comum;
- revista inteira;
- apostila simples;
- documento sem estrutura acadêmica;
- arquivo muito grande acima do limite configurado.

## Política de falha

O GROBID nunca deve parar o preparo.

Se ocorrer erro, o aplicativo deve:

1. registrar que a camada GROBID falhou;
2. registrar o motivo;
3. continuar para as outras camadas;
4. não mover o material para erro fatal apenas por falha do GROBID.

Motivos possíveis:

- VPN desconectada;
- serviço indisponível;
- timeout;
- PDF muito grande;
- resposta inválida;
- metadados insuficientes;
- erro HTTP;
- contêiner reiniciando.

Mensagem desejada ao operador:

```text
GROBID central indisponível; prosseguindo sem essa camada.
```

## Etapas da execução

### Etapa 1 — levantamento do servidor

Confirmar:

- sistema operacional;
- se Docker ou Podman está instalado;
- IP interno da OpenVPN;
- se a porta 8070 está livre;
- espaço em disco disponível;
- memória disponível;
- política atual de firewall.

Resultado esperado:

- ficha técnica simples do servidor;
- decisão se usaremos Docker ou Podman;
- IP e porta definidos.

### Etapa 2 — subir o GROBID em contêiner

Subir GROBID em modo serviço, com reinício automático.

Regras:

- usar imagem oficial ou amplamente adotada;
- limitar exposição à interface/IP da VPN;
- não publicar no IP público;
- definir reinício automático;
- registrar caminho de logs;
- registrar versão da imagem usada.

Resultado esperado:

- contêiner ativo;
- serviço respondendo localmente no servidor.

### Etapa 3 — restringir acesso

Configurar o acesso para que a porta do GROBID responda apenas pela VPN.

Testes obrigatórios:

- do próprio servidor: deve responder;
- de um cliente conectado à VPN: deve responder;
- de fora da VPN pelo IP público: não deve responder.

Se responder pelo IP público, a fase 1 não pode avançar.

### Etapa 4 — limpeza defensiva

Criar rotina de limpeza para:

- temporários antigos;
- logs antigos ou grandes;
- eventuais arquivos deixados por falha;
- monitoramento simples de uso de disco.

Política inicial:

- apagar temporários com mais de 24 horas;
- rotacionar logs;
- registrar execução da limpeza;
- alertar manualmente se disco estiver alto.

Resultado esperado:

- script de limpeza criado;
- execução manual testada;
- agendamento documentado.

### Etapa 5 — teste de saúde

Criar uma forma simples de verificar se o GROBID está vivo.

O teste deve responder:

- serviço acessível;
- tempo de resposta;
- versão ou identificação do serviço, quando disponível;
- erro claro quando indisponível.

Resultado esperado:

- comando ou função de teste documentado;
- app local capaz de mostrar “GROBID disponível” ou “indisponível”.

### Etapa 6 — configuração no app local

O app deve permitir configurar:

- usar GROBID central: sim/não;
- URL do serviço;
- timeout;
- tamanho máximo de envio;
- testar conexão;
- usar apenas quando VPN estiver ativa.

Para a fase 1, essa configuração pode ficar em arquivo interno do app, desde que
seja fácil de mudar durante o teste.

### Etapa 7 — integração mínima no fluxo

O app deve chamar o GROBID somente como uma camada da cascata de metadados.

Ordem sugerida:

1. detectar tipo provável do material;
2. se for acadêmico, testar se GROBID está habilitado;
3. enviar ao GROBID;
4. interpretar retorno;
5. preencher metadados acadêmicos quando confiáveis;
6. registrar evidência;
7. continuar o fluxo normal.

O GROBID não deve apagar dados melhores já obtidos por ISBN, CIP ou revisão
manual.

## Regras de prioridade dos metadados

O retorno do GROBID deve ser tratado como forte para:

- título acadêmico;
- autores;
- resumo;
- DOI;
- periódico;
- instituição;
- ano;
- referências.

Mas não deve vencer automaticamente:

- ISBN confirmado;
- ficha catalográfica completa;
- revisão manual validada;
- dados já confirmados pela API do Biblio.

Regra prática:

```text
Revisão manual > API Biblio/duplicidade > ISBN confirmado > CIP/ficha catalográfica > GROBID acadêmico > capa/OCR solto > nome do arquivo
```

## Dados a registrar por arquivo

Cada tentativa com GROBID deve registrar:

- arquivo;
- tipo provável;
- enviado ou não enviado;
- motivo se não enviado;
- tempo de resposta;
- sucesso ou falha;
- campos extraídos;
- campos aproveitados;
- campos rejeitados;
- motivo da rejeição;
- se houve melhora no estado final.

Isso é essencial para medir se a camada vale a pena.

## Relatório da fase 1

Ao final do lote de teste, gerar um relatório com:

- quantidade de arquivos testados;
- quantos foram enviados ao GROBID;
- quantos retornaram metadados úteis;
- quantos passaram de revisão para pronto;
- quantos permaneceram em revisão;
- tempo médio por arquivo;
- erros encontrados;
- exemplos de acerto;
- exemplos de erro;
- decisão recomendada para a fase 2.

## Critérios de aceite

A fase 1 será considerada bem-sucedida se:

- GROBID rodar no servidor de modo estável;
- porta pública estiver fechada;
- acesso pela OpenVPN funcionar;
- app local não travar quando o serviço cair;
- pelo menos 10 materiais acadêmicos forem testados;
- pelo menos parte relevante dos metadados acadêmicos melhorar;
- houver relatório de resultado;
- houver decisão clara de avançar, ajustar ou abandonar a camada.

## Critérios para interromper a fase 1

Interromper e revisar se:

- o serviço ficar exposto publicamente;
- o servidor tiver uso excessivo de CPU/memória;
- o app travar quando GROBID falha;
- o ganho de metadados for irrelevante;
- a limpeza de temporários não for confiável;
- houver risco de acumular PDFs no servidor.

## Plano de retorno

Se a fase 1 falhar:

1. desabilitar GROBID no app local;
2. parar o contêiner;
3. fechar a porta;
4. remover temporários;
5. preservar relatório técnico;
6. manter o fluxo antigo funcionando.

Nenhum material do acervo deve depender exclusivamente do GROBID para continuar.

## Entregáveis da fase 1

- Serviço GROBID rodando no servidor.
- Acesso restrito pela OpenVPN.
- Teste de saúde.
- Limpeza defensiva.
- Configuração local no app.
- Integração mínima no fluxo acadêmico.
- Lote de teste processado.
- Relatório de resultado.
- Decisão para fase 2.

## Checklist de execução

### Servidor

- [ ] Confirmar IP interno da VPN.
- [ ] Confirmar Docker ou Podman.
- [ ] Definir porta.
- [ ] Subir GROBID.
- [ ] Restringir porta à VPN.
- [ ] Testar acesso local.
- [ ] Testar acesso pela VPN.
- [ ] Testar bloqueio pelo IP público.
- [ ] Criar limpeza.
- [ ] Documentar versão.

### App local

- [ ] Adicionar configuração do GROBID central.
- [ ] Adicionar teste de conexão.
- [ ] Definir timeout.
- [ ] Definir limite de tamanho.
- [ ] Chamar apenas para material acadêmico.
- [ ] Registrar motivo quando não usar.
- [ ] Garantir fallback sem travar.
- [ ] Registrar campos aproveitados.

### Teste

- [ ] Separar lote de 10 materiais acadêmicos.
- [ ] Rodar sem GROBID e registrar base.
- [ ] Rodar com GROBID.
- [ ] Comparar ganho.
- [ ] Revisar erros.
- [ ] Atualizar regras do app se necessário.
- [ ] Gerar relatório.

## Próximo passo prático

Antes de executar comandos no servidor, preencher os campos:

| Campo | Valor |
|---|---|
| IP interno da OpenVPN | |
| Porta escolhida | 8070 |
| Docker ou Podman | |
| Caminho de scripts no servidor | |
| Pasta temporária do GROBID | |
| Primeiro computador de teste | |

Com esses dados preenchidos, a fase 1 pode ser executada passo a passo.
