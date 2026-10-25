import Cocoa
import WebKit
import CryptoKit

let appId = "biblio-preparador-visual"
let defaultPort = 65087
let logURL = URL(fileURLWithPath: "/private/tmp/biblio-preparador.log")

func log(_ message: String) {
    let line = "[\(Date())] \(message)\n"
    if let data = line.data(using: .utf8) {
        if FileManager.default.fileExists(atPath: logURL.path),
           let handle = try? FileHandle(forWritingTo: logURL) {
            defer { try? handle.close() }
            _ = try? handle.seekToEnd()
            try? handle.write(contentsOf: data)
        } else {
            try? data.write(to: logURL)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var serverProcess: Process?
    var statusLabel: NSTextField!
    var serverURL: URL?
    var serverOutput = ""
    let serverOutputQueue = DispatchQueue(label: "biblio-preparador.server-output")

    func applicationDidFinishLaunching(_ notification: Notification) {
        buildWindow()
        DispatchQueue.global(qos: .userInitiated).async {
            self.prepareAndOpen()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let process = serverProcess, process.isRunning {
            process.terminate()
        }
    }

    private func buildWindow() {
        let content = NSView()
        content.translatesAutoresizingMaskIntoConstraints = false

        statusLabel = NSTextField(labelWithString: "Iniciando Biblio Preparador…")
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.font = .systemFont(ofSize: 13, weight: .medium)
        statusLabel.textColor = .secondaryLabelColor

        let config = WKWebViewConfiguration()
        webView = WKWebView(frame: .zero, configuration: config)
        webView.translatesAutoresizingMaskIntoConstraints = false
        webView.navigationDelegate = self
        webView.uiDelegate = self

        content.addSubview(statusLabel)
        content.addSubview(webView)

        NSLayoutConstraint.activate([
            statusLabel.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 14),
            statusLabel.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -14),
            statusLabel.topAnchor.constraint(equalTo: content.topAnchor, constant: 10),
            statusLabel.heightAnchor.constraint(equalToConstant: 22),

            webView.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            webView.topAnchor.constraint(equalTo: statusLabel.bottomAnchor, constant: 8),
            webView.bottomAnchor.constraint(equalTo: content.bottomAnchor),
        ])

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1320, height: 860),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Biblio Preparador"
        window.center()
        window.contentView = content
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func prepareAndOpen() {
        do {
            log("prepareAndOpen iniciado")
            let support = try prepareSupportFolder()
            log("support: \(support.path)")
            let tools = support.appendingPathComponent("99-FERRAMENTAS", isDirectory: true)
            let livros = support.appendingPathComponent("livros", isDirectory: true)
            try FileManager.default.createDirectory(at: livros, withIntermediateDirectories: true)

            var url = URL(string: "http://127.0.0.1:\(defaultPort)/")!
            if isBiblioAlive(port: defaultPort) && !isCurrentEngine(tools: tools, port: defaultPort) {
                throw AppError("Uma versão anterior do Biblio ainda está aberta. Conclua o processamento, encerre o app anterior e abra novamente para usar as melhorias instaladas.")
            }
            if !isBiblioAlive(port: defaultPort) {
                updateStatus("Abrindo o motor local…")
                log("servidor nao estava ativo; verificando porta presa")
                try recoverStaleBiblioServer(port: defaultPort)
                let portToStart = try listeningPids(on: defaultPort).isEmpty ? defaultPort : 0
                if portToStart == 0 {
                    log("porta \(defaultPort) continua ocupada; usando porta livre automática")
                }
                log("iniciando servidor")
                try startServer(tools: tools, livros: livros, port: portToStart)
                url = try waitForServerURL(defaultPort: defaultPort, seconds: 25)
            }

            DispatchQueue.main.async {
                self.statusLabel.stringValue = "Biblio Preparador"
                self.webView.load(URLRequest(url: url))
            }
        } catch {
            log("erro: \(error.localizedDescription)")
            DispatchQueue.main.async {
                self.statusLabel.stringValue = "Não foi possível abrir o Biblio Preparador"
                self.showError(error.localizedDescription)
            }
        }
    }

    private func prepareSupportFolder() throws -> URL {
        let fm = FileManager.default
        let appSupport = try fm.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let support = appSupport
            .appendingPathComponent("Biblio Preparador", isDirectory: true)
            .appendingPathComponent("revista", isDirectory: true)
        guard let base = Bundle.main.resourceURL?.appendingPathComponent("pacote-base", isDirectory: true) else {
            throw AppError("Pacote interno não encontrado.")
        }
        log("base: \(base.path)")
        try verifyEngineFiles(in: base.appendingPathComponent("99-FERRAMENTAS"))
        try fm.createDirectory(at: support, withIntermediateDirectories: true)

        // Atualiza a ferramenta a cada abertura, mas preserva a biblioteca
        // local do operador. Isso permite evoluir o app sem apagar livros,
        // metadados, filas, capas ou revisões.
        for nome in ["99-FERRAMENTAS", "docs", "AGENTS.md", ".gitignore"] {
            let origem = base.appendingPathComponent(nome)
            guard fm.fileExists(atPath: origem.path) else { continue }
            let destino = support.appendingPathComponent(nome)
            if nome == "99-FERRAMENTAS" {
                try installTools(from: origem, to: destino)
                continue
            }
            if fm.fileExists(atPath: destino.path) {
                log("removendo: \(destino.path)")
                try fm.removeItem(at: destino)
            }
            log("copiando: \(origem.path) -> \(destino.path)")
            try fm.copyItem(at: origem, to: destino)
        }
        try verifyEngineFiles(in: support.appendingPathComponent("99-FERRAMENTAS"))

        let livrosOrigem = base.appendingPathComponent("livros", isDirectory: true)
        let livrosDestino = support.appendingPathComponent("livros", isDirectory: true)
        if !fm.fileExists(atPath: livrosDestino.path),
           fm.fileExists(atPath: livrosOrigem.path) {
            try fm.copyItem(at: livrosOrigem, to: livrosDestino)
        }
        return support
    }

    private func verifyEngineFiles(in tools: URL) throws {
        let data = try Data(contentsOf: tools.appendingPathComponent("versao-motor.json"))
        guard let manifest = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let files = manifest["arquivos"] as? [String: String] else {
            throw AppError("Pacote do motor sem identificação de versão válida.")
        }
        for (name, expected) in files {
            let data = try Data(contentsOf: tools.appendingPathComponent(name))
            let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
            if actual != expected {
                throw AppError("O arquivo \(name) não corresponde à versão empacotada. Reinstale o pacote atualizado.")
            }
        }
        log("Motor verificado: \(manifest["versao"] ?? "")")
    }

    private let memoryFiles: Set<String> = ["titulos-ruidosos-conhecidos.json",
        "autores-ruidosos-conhecidos.json", "editoras-cidades.json",
        "periodicos-conhecidos.json", "autores-conhecidos.json"]

    private func installTools(from source: URL, to target: URL) throws {
        let fm = FileManager.default
        try fm.createDirectory(at: target, withIntermediateDirectories: true)
        guard let paths = fm.enumerator(atPath: source.path) else { return }
        for case let relative as String in paths {
            let src = source.appendingPathComponent(relative)
            let dst = target.appendingPathComponent(relative)
            var directory: ObjCBool = false
            guard fm.fileExists(atPath: src.path, isDirectory: &directory) else { continue }
            if directory.boolValue {
                try fm.createDirectory(at: dst, withIntermediateDirectories: true)
                continue
            }
            if memoryFiles.contains(src.lastPathComponent), fm.fileExists(atPath: dst.path),
               var fresh = try JSONSerialization.jsonObject(with: Data(contentsOf: src)) as? [String:Any],
               let previous = try JSONSerialization.jsonObject(with: Data(contentsOf: dst)) as? [String:Any] {
                for key in ["itens", "autores", "editoras", "periodicos"] {
                    guard let old = previous[key] as? [[String:Any]] else { continue }
                    var list = fresh[key] as? [[String:Any]] ?? []
                    var seen = Set(try list.map { try JSONSerialization.data(withJSONObject:$0, options:.sortedKeys) })
                    for row in old {
                        let bytes = try JSONSerialization.data(withJSONObject:row, options:.sortedKeys)
                        if seen.insert(bytes).inserted { list.append(row) }
                    }
                    fresh[key] = list
                }
                try JSONSerialization.data(withJSONObject:fresh, options:[.sortedKeys,.prettyPrinted]).write(to:dst, options:.atomic)
            } else if !fm.contentsEqual(atPath: src.path, andPath: dst.path) {
                try Data(contentsOf: src).write(to: dst, options: .atomic)
                let attrs = try fm.attributesOfItem(atPath: src.path)
                if let permissions = attrs[.posixPermissions] {
                    try fm.setAttributes([.posixPermissions: permissions], ofItemAtPath: dst.path)
                }
            }
        }
        // Não remove binários Vision nem memórias locais ausentes do pacote.
    }

    private func isCurrentEngine(tools: URL, port: Int) -> Bool {
        var bytes = Data()
        for name in ["biblio_app_visual.py", "preparar-livros.py", "biblioteca-local.py", "enviar-livro-api.py", "consultar_apple.py", "piloto-apple-bibliografia.swift", "revisao-visual.py"] {
            guard let data = try? Data(contentsOf: tools.appendingPathComponent(name)) else { return false }
            bytes.append(data)
        }
        let expected = String(SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined().prefix(16))
        let semaphore = DispatchSemaphore(value: 0)
        var matches = false
        var req = URLRequest(url: URL(string: "http://127.0.0.1:\(port)/api/health")!)
        req.timeoutInterval = 2
        URLSession.shared.dataTask(with: req) { data, _, _ in
            defer { semaphore.signal() }
            if let data, let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                matches = obj["versao_motor"] as? String == expected
            }
        }.resume()
        _ = semaphore.wait(timeout: .now() + 3)
        return matches
    }

    private func findPython() throws -> URL {
        let candidates = [
            "/usr/bin/python3",
            "/Library/Developer/CommandLineTools/usr/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
        ]
        for path in candidates where FileManager.default.isExecutableFile(atPath: path) {
            return URL(fileURLWithPath: path)
        }
        throw AppError("Python 3 não foi encontrado neste Mac.")
    }

    private func startServer(tools: URL, livros: URL, port: Int) throws {
        let process = Process()
        process.executableURL = try findPython()
        process.currentDirectoryURL = tools
        process.arguments = [
            "biblio_app_visual.py",
            "--raiz", livros.path,
            "--porta", String(port),
        ]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPYCACHEPREFIX"] = "/private/tmp/biblio-pycache"
        environment["PYTHONWARNINGS"] = "ignore:urllib3 v2 only supports OpenSSL"
        process.environment = environment
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty,
                  let text = String(data: data, encoding: .utf8) else { return }
            self?.recordServerOutput(text)
        }
        try process.run()
        serverProcess = process
        Thread.sleep(forTimeInterval: 0.35)
        if !process.isRunning {
            output.fileHandleForReading.readabilityHandler = nil
            let data = output.fileHandleForReading.readDataToEndOfFile()
            let text = (serverOutputSnapshot() + (String(data: data, encoding: .utf8) ?? ""))
                .trimmingCharacters(in: .whitespacesAndNewlines)
            log("motor Python encerrou imediatamente: \(text)")
            throw AppError("O motor local não iniciou. Detalhes: \(text.isEmpty ? "sem saída do processo" : text)")
        }
    }

    private func recordServerOutput(_ text: String) {
        serverOutputQueue.sync {
            serverOutput += text
        }
        for line in text.split(whereSeparator: \.isNewline) {
            let lineText = String(line)
            log("motor: \(lineText)")
            if let range = lineText.range(
                of: #"http://127\.0\.0\.1:\d+/"#,
                options: .regularExpression
            ) {
                let found = String(lineText[range])
                if let url = URL(string: found) {
                    serverURL = url
                }
            }
        }
    }

    private func serverOutputSnapshot() -> String {
        serverOutputQueue.sync {
            serverOutput
        }
    }

    private func recoverStaleBiblioServer(port: Int) throws {
        let pids = try listeningPids(on: port)
        if pids.isEmpty {
            return
        }
        var recovered = false
        for pid in pids {
            let command = processCommand(pid: pid)
            log("porta \(port) ocupada por pid \(pid): \(command)")
            if command.contains("biblio_app_visual.py") {
                log("encerrando servidor Biblio preso: \(pid)")
                kill(pid, SIGTERM)
                Thread.sleep(forTimeInterval: 1.0)
                if !processExists(pid) {
                    recovered = true
                    continue
                }
                log("servidor Biblio ainda ativo; forçando encerramento: \(pid)")
                kill(pid, SIGKILL)
                Thread.sleep(forTimeInterval: 0.5)
                recovered = true
            }
        }
        if recovered {
            try waitForPortToBeFree(port: port, seconds: 8)
            return
        }
        log("porta \(port) continua ocupada por outro programa; o app usará porta livre automática")
    }

    private func listeningPids(on port: Int) throws -> [Int32] {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        process.arguments = ["-ti", "tcp:\(port)", "-sTCP:LISTEN"]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = Pipe()
        try process.run()
        process.waitUntilExit()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        let text = String(data: data, encoding: .utf8) ?? ""
        return text
            .split(whereSeparator: \.isNewline)
            .compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }
    }

    private func waitForPortToBeFree(port: Int, seconds: Int) throws {
        let deadline = Date().addingTimeInterval(TimeInterval(seconds))
        while Date() < deadline {
            if (try? listeningPids(on: port).isEmpty) == true {
                log("porta \(port) liberada")
                return
            }
            Thread.sleep(forTimeInterval: 0.25)
        }
        throw AppError("A porta \(port) ficou presa e não liberou para reiniciar o Biblio.")
    }

    private func processCommand(pid: Int32) -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["-p", "\(pid)", "-o", "command="]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            return String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        } catch {
            return ""
        }
    }

    private func processExists(_ pid: Int32) -> Bool {
        kill(pid, 0) == 0
    }

    private func waitForServerURL(defaultPort: Int, seconds: Int) throws -> URL {
        let deadline = Date().addingTimeInterval(TimeInterval(seconds))
        while Date() < deadline {
            if isBiblioAlive(port: defaultPort) {
                return URL(string: "http://127.0.0.1:\(defaultPort)/")!
            }
            if let url = serverURL, let port = url.port, isBiblioAlive(port: port) {
                log("motor respondeu em porta alternativa: \(port)")
                return url
            }
            if let process = serverProcess, !process.isRunning {
                let text = serverOutputSnapshot()
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                throw AppError("O motor local encerrou antes de responder. Detalhes: \(text.isEmpty ? "sem saída do processo" : text)")
            }
            Thread.sleep(forTimeInterval: 0.35)
        }
        let text = serverOutputSnapshot()
            .trimmingCharacters(in: .whitespacesAndNewlines)
        throw AppError("O motor local não respondeu. Detalhes: \(text.isEmpty ? "nenhuma saída do motor" : text)")
    }

    private func isBiblioAlive(port: Int) -> Bool {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/health") else {
            return false
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.5
        let semaphore = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: request) { data, _, _ in
            defer { semaphore.signal() }
            guard
                let data,
                let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                object["app"] as? String == appId
            else { return }
            ok = true
        }.resume()
        _ = semaphore.wait(timeout: .now() + 2.0)
        return ok
    }

    private func updateStatus(_ text: String) {
        DispatchQueue.main.async {
            self.statusLabel.stringValue = text
        }
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Biblio Preparador"
        alert.informativeText = message
        alert.alertStyle = .critical
        alert.runModal()
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.canCreateDirectories = false
        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }
}

struct AppError: LocalizedError {
    let message: String

    init(_ message: String) {
        self.message = message
    }

    var errorDescription: String? {
        message
    }
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
