#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
#  Biblio Preparador — empacotamento Mac fase 1
# =============================================================================
# Este construtor cria um .app mínimo sem alterar o motor já funcional.
#
# O app gerado:
#   - não executa OCR, envio nem preparo durante o build;
#   - não copia o acervo local;
#   - não guarda livros dentro do .app;
#   - abre a interface visual local em uma pasta de trabalho externa do usuário.
#
# Pasta externa usada no Mac do operador:
#   ~/Library/Application Support/Biblio Preparador/revista
#
# Nessa pasta ficam uma duplicata funcional do pacote-base:
#   99-FERRAMENTAS/  cópia das ferramentas empacotadas
#   docs/            documentação operacional
#   livros/          biblioteca local criada pelo fluxo já existente
# =============================================================================

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_NAME="Biblio Preparador"
APP_BUNDLE="$ROOT/dist/$APP_NAME.app"
CONTENTS="$APP_BUNDLE/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
PACKAGE_BASE="$RESOURCES/pacote-base"

copiar_limpo() {
  local origem="$1"
  local destino="$2"
  mkdir -p "$destino"
  (cd "$origem" && tar \
    --exclude='.DS_Store' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='_resultado-capas.txt' \
    --exclude='_resultado-ner.txt' \
    --exclude='baixar-voice-fgbmfi.log' \
    --exclude='vision-ocr' \
    --exclude='vision-barcode' \
    -cf - .) | (cd "$destino" && tar -xf -)
}

rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS" "$PACKAGE_BASE"

ICON_WORK="/private/tmp/BiblioPreparadorIcon.iconset"
ICON_TMP="/private/tmp/BiblioPreparadorIcon.icns"
rm -rf "$ICON_WORK" "$ICON_TMP"
python3 "$ROOT/packaging/macos/make_app_icon.py" "$ICON_WORK"
python3 "$ROOT/packaging/macos/make_app_icon.py" "$ICON_TMP"
cp "$ICON_TMP" "$RESOURCES/BiblioPreparadorIcon.icns"
rm -rf "$ICON_WORK" "$ICON_TMP"

cat > "$CONTENTS/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>pt_BR</string>
  <key>CFBundleDisplayName</key>
  <string>Biblio Preparador</string>
  <key>CFBundleExecutable</key>
  <string>BiblioPreparador</string>
  <key>CFBundleIconFile</key>
  <string>BiblioPreparadorIcon.icns</string>
  <key>CFBundleIdentifier</key>
  <string>br.org.pibcuritiba.biblio-preparador</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>Biblio Preparador</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>0.1.0</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

SWIFT_CACHE="/private/tmp/biblio-swift-cache"
mkdir -p "$SWIFT_CACHE"

CLANG_MODULE_CACHE_PATH="$SWIFT_CACHE/clang" \
MODULE_CACHE_DIR="$SWIFT_CACHE/modules" \
xcrun swiftc \
  -O \
  -target arm64-apple-macosx12.0 \
  -framework Cocoa \
  -framework WebKit \
  "$ROOT/packaging/macos/BiblioPreparador.swift" \
  -o "$MACOS/BiblioPreparador"

copiar_limpo "$ROOT/99-FERRAMENTAS" "$PACKAGE_BASE/99-FERRAMENTAS"
copiar_limpo "$ROOT/docs" "$PACKAGE_BASE/docs"

# Além do CFBundleIconFile, aplicamos também o ícone customizado no próprio
# bundle. Isso ajuda o Finder a exibir a arte imediatamente, especialmente em
# pastas sincronizadas como Dropbox/iCloud, onde o cache visual pode insistir
# no ícone genérico por algum tempo.
if command -v Rez >/dev/null 2>&1 && command -v DeRez >/dev/null 2>&1 && command -v SetFile >/dev/null 2>&1; then
  ICON_RSRC="$RESOURCES/BiblioPreparadorIcon.rsrc"
  DeRez -only icns "$RESOURCES/BiblioPreparadorIcon.icns" > "$ICON_RSRC" 2>/dev/null || true
  if [ -s "$ICON_RSRC" ]; then
    Rez -append "$ICON_RSRC" -o "$APP_BUNDLE/Icon"$'\r' 2>/dev/null || true
    SetFile -a C "$APP_BUNDLE" 2>/dev/null || true
    SetFile -a V "$APP_BUNDLE/Icon"$'\r' 2>/dev/null || true
  fi
  rm -f "$ICON_RSRC"
fi

for arquivo in AGENTS.md .gitignore; do
  if [ -f "$ROOT/$arquivo" ]; then
    cp "$ROOT/$arquivo" "$PACKAGE_BASE/$arquivo"
  fi
done

# O acervo e os estados locais nunca entram no app. Criamos só a estrutura
# vazia esperada pelo comando e pelas filas, para documentar a intenção do
# pacote e permitir que o primeiro uso comece de uma biblioteca limpa.
mkdir -p \
  "$PACKAGE_BASE/livros/00-ENTRADA" \
  "$PACKAGE_BASE/livros/10-REVISAO" \
  "$PACKAGE_BASE/livros/15-TESES-DISSERTACOES-E-TRABALHOS" \
  "$PACKAGE_BASE/livros/16-ARTIGOS-E-DOCUMENTOS" \
  "$PACKAGE_BASE/livros/17-REVISTAS-E-PERIODICOS" \
  "$PACKAGE_BASE/livros/18-EXCECOES-DE-TAMANHO" \
  "$PACKAGE_BASE/livros/19-DESCARTE" \
  "$PACKAGE_BASE/livros/20-PRONTOS" \
  "$PACKAGE_BASE/livros/30-ARQUIVADOS" \
  "$PACKAGE_BASE/livros/_controle" \
  "$PACKAGE_BASE/livros/_metadados" \
  "$PACKAGE_BASE/livros/_capas" \
  "$PACKAGE_BASE/livros/_capas300" \
  "$PACKAGE_BASE/livros/_preparados-envio"

echo "App criado em:"
echo "  $APP_BUNDLE"
echo ""
echo "Para testar:"
echo "  open \"$APP_BUNDLE\""
