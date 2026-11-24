# Dependências: fotografia do Mac de origem

Inventário de 24/11/2026, não um instalador universal nem garantia de
compatibilidade com versões futuras de macOS/Python. Recriar os ambientes;
não copiar o diretório de um ambiente virtual entre usuários/computadores.

| Camada | Encontrado no Mac de origem |
|---|---|
| Arquitetura | arm64 / Apple Silicon |
| Launcher Python | tenta `/usr/bin/python3` primeiro |
| Requests nesse Python | 2.32.5 |
| Playwright nesse Python | 1.60.0 |
| Requests no venv NER | 2.34.2 |
| Playwright no venv NER | 1.62.0 |
| spaCy no venv NER | 3.8.15 |
| Python Homebrew | python@3.12 3.12.13_4 |
| Poppler | 26.07.0 |
| OCRmyPDF | 17.8.1 |
| Tesseract | 5.5.3 |
| Pacote de idiomas Tesseract | 4.1.0 |
| Ghostscript | 10.07.1 |
| zbar | 0.23.93_4 |

O arquivo `requirements-mac.txt` registra apenas os dois pacotes do Python
usado pelo launcher; não instala o restante da tabela. A camada NER é separada
e tem sua rotina em `99-FERRAMENTAS/INSTALAR-NER.command`.
Playwright também precisa do navegador instalado em seu ambiente.

Outras dependências funcionais documentadas no projeto: Xcode/Command Line
Tools e Swift; LibreOffice para documentos; Calibre para ebooks; a configuração
do GROBID/VPN e as ferramentas/logins de IA efetivamente utilizados.

Não instalar pacotes no Python de outro aplicativo supondo que o Biblio os
encontrará. Conferir o Python selecionado pelo launcher e então aplicar os
requisitos nesse ambiente. Se necessário, adaptar o seletor em uma mudança
separada e testada; esta migração não altera o motor nem o launcher.

Seguir [o roteiro de migração](../docs/MIGRACAO-E-CONTINUIDADE.md) antes de
processar, reenviar ou limpar materiais.
