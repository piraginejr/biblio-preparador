// Le códigos de barras em uma imagem usando o Vision nativo do macOS.
// Saída JSON: [{"valor":"978...","tipo":"EAN13","confianca":1.0}]

import Foundation
import Vision
import AppKit

let args = Array(CommandLine.arguments.dropFirst())
guard let caminho = args.first,
      let imagem = NSImage(contentsOfFile: caminho),
      let cg = imagem.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write(Data("não consegui abrir a imagem\n".utf8))
    exit(1)
}

let pedido = VNDetectBarcodesRequest()
// ISBN impresso em livros usa EAN-13. Restringir o modelo a esse formato
// também evita carregar detectores desnecessários em máquinas mais antigas.
pedido.symbologies = [.ean13]

do {
    try VNImageRequestHandler(cgImage: cg, options: [:]).perform([pedido])
} catch {
    FileHandle.standardError.write(Data("falha no Vision: \(error)\n".utf8))
    exit(1)
}

struct Codigo: Codable {
    let valor: String
    let tipo: String
    let confianca: Float
}

let codigos = (pedido.results ?? []).compactMap { item -> Codigo? in
    guard let valor = item.payloadStringValue, !valor.isEmpty else { return nil }
    return Codigo(valor: valor, tipo: item.symbology.rawValue,
                  confianca: item.confidence)
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.withoutEscapingSlashes]
if let dados = try? encoder.encode(codigos) {
    FileHandle.standardOutput.write(dados)
    FileHandle.standardOutput.write(Data("\n".utf8))
}
