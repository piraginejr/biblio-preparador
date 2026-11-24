# Biblio Preparador

Preparação, OCR, catalogação, revisão visual e envio de materiais para o Biblio.
O motor Python existente é compartilhado pelo fluxo de terminal e pelo app Mac
nativo com WebView; não são dois motores independentes.

## Continuar em outro Mac

Comece por [Migração e continuidade](docs/MIGRACAO-E-CONTINUIDADE.md).
É necessário transferir **o código pelo Git e o estado operacional por uma
cópia privada**. Clonar o repositório sozinho não recupera filas, PDFs ou
decisões locais que estejam fora do Git.

```bash
git clone --branch codex/app-mac-biblio https://github.com/piraginejr/biblio-preparador.git
cd biblio-preparador
```

- App Mac: branch `codex/app-mac-biblio`.
- Motor legado: branch `desenvolvimento-biblio`.
- Não desenvolver nem publicar alterações em `main`.
- Regras de entrega, preservação e backups: [AGENTS.md](AGENTS.md).
- Engenharia: [docs/ENGENHARIA-APP-BIBLIO.md](docs/ENGENHARIA-APP-BIBLIO.md).
- Dependências: [packaging/DEPENDENCIAS-MAC.md](packaging/DEPENDENCIAS-MAC.md).
- Reparo de anexos existentes, sem ficha nova: [docs/REPARO-DE-ANEXOS.md](docs/REPARO-DE-ANEXOS.md).

O construtor atual gera um aplicativo para Mac Apple Silicon (arm64).
Windows ainda não tem instalador; Mac Intel requer adaptação e validação.

## Segurança

Senhas, acervo, filas, caches, auditorias privadas e pacotes de migração não
devem ir para o GitHub. Os dados do operador ficam fora do `.app`, em
`~/Library/Application Support/Biblio Preparador/revista`.

Antes de enviar novamente um material, preservar e conferir os diários de
envio. Nunca tratar a ausência de arquivos locais já liberados como autorização
para recriar cadastros remotos.
