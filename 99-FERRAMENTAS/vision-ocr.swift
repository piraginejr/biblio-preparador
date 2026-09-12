// vision-ocr.swift - OCR pelo Vision da Apple, uma linha por linha de texto.
//
// E o mesmo motor do app CartaoContatos (CardModel.swift, linha 35):
// VNRecognizeTextRequest com .accurate. Rede neural, sem pre-processamento
// de imagem - e bem melhor que o Tesseract em capa decorada, que e onde
// o nosso lote ainda falha.
//
// Compilar (uma vez):
//     swiftc -O vision-ocr.swift -o vision-ocr
//
// O ler-capa.py procura o binario "vision-ocr" ao lado dele e usa
// automaticamente quando encontra; sem ele, cai no Tesseract.

import Foundation
import Vision
import AppKit

let args = Array(CommandLine.arguments.dropFirst())
guard !args.isEmpty else {
    FileHandle.standardError.write(
        "uso: vision-ocr <imagem>\n     vision-ocr --idiomas\n".data(using: .utf8)!)
    exit(2)
}

// --idiomas: lista o que ESTE macOS reconhece. Melhor perguntar ao
// sistema do que confiar em lista decorada - muda a cada versao.
if args[0] == "--idiomas" {
    let r = VNRecognizeTextRequest()
    r.recognitionLevel = .accurate
    if let langs = try? r.supportedRecognitionLanguages() {
        print(langs.joined(separator: " "))
    } else {
        print("(nao consegui consultar)")
    }
    exit(0)
}

let modoJSON = args.contains("--json")
guard let caminhoImagem = args.first(where: { !$0.hasPrefix("--") }),
      let img = NSImage(contentsOfFile: caminhoImagem),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("nao consegui abrir a imagem\n".data(using: .utf8)!)
    exit(1)
}

let pedido = VNRecognizeTextRequest()
pedido.recognitionLevel = .accurate
pedido.usesLanguageCorrection = true
// portugues e espanhol primeiro: o acervo e majoritariamente nessas duas
pedido.recognitionLanguages = ["pt-BR", "es-ES", "en-US", "fr-FR"]

do {
    try VNImageRequestHandler(cgImage: cg, options: [:]).perform([pedido])
} catch {
    FileHandle.standardError.write("falha no Vision: \(error)\n".data(using: .utf8)!)
    exit(1)
}

// Ordena de cima para baixo. A ordem importa para remontar titulo
// quebrado em varias linhas; o PAPEL de cada linha quem decide e o
// identificar.py, por semantica - nao por posicao.
let obs = (pedido.results ?? []).sorted { $0.boundingBox.midY > $1.boundingBox.midY }

struct LinhaOCR: Codable {
    let texto: String
    let confianca: Float
    let x: Double
    let y: Double
    let largura: Double
    let altura: Double
}

if modoJSON {
    let linhas = obs.compactMap { o -> LinhaOCR? in
        guard let t = o.topCandidates(1).first, t.confidence > 0.3 else { return nil }
        let b = o.boundingBox
        return LinhaOCR(texto: t.string, confianca: t.confidence,
                        x: b.origin.x, y: b.origin.y,
                        largura: b.size.width, altura: b.size.height)
    }
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    if let dados = try? encoder.encode(linhas) {
        FileHandle.standardOutput.write(dados)
        FileHandle.standardOutput.write(Data("\n".utf8))
    }
    exit(0)
}

for o in obs {
    if let t = o.topCandidates(1).first, t.confidence > 0.3 {
        print(t.string)
    }
}
