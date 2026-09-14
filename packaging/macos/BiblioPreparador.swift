import Cocoa
import WebKit

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

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    var window: NSWindow!
    var webView: WKWebView!
    var serverProcess: Process?
    var statusLabel: NSTextField!

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

            let url = URL(string: "http://127.0.0.1:\(defaultPort)/")!
            if !isBiblioAlive(port: defaultPort) {
                updateStatus("Abrindo o motor local…")
                log("servidor nao estava ativo; verificando porta presa")
                try recoverStaleBiblioServer(port: defaultPort)
                log("iniciando servidor")
                try startServer(tools: tools, livros: livros, port: defaultPort)
                try waitForServer(port: defaultPort, seconds: 25)
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
        try fm.createDirectory(at: support, withIntermediateDirectories: true)

        // Atualiza a ferramenta a cada abertura, mas preserva a biblioteca
        // local do operador. Isso permite evoluir o app sem apagar livros,
        // metadados, filas, capas ou revisões.
        for nome in ["99-FERRAMENTAS", "docs", "AGENTS.md", ".gitignore"] {
            let origem = base.appendingPathComponent(nome)
            guard fm.fileExists(atPath: origem.path) else { continue }
            let destino = support.appendingPathComponent(nome)
            if fm.fileExists(atPath: destino.path) {
                log("removendo: \(destino.path)")
                try fm.removeItem(at: destino)
            }
            log("copiando: \(origem.path) -> \(destino.path)")
            try fm.copyItem(at: origem, to: destino)
        }

        let livrosOrigem = base.appendingPathComponent("livros", isDirectory: true)
        let livrosDestino = support.appendingPathComponent("livros", isDirectory: true)
        if !fm.fileExists(atPath: livrosDestino.path),
           fm.fileExists(atPath: livrosOrigem.path) {
            try fm.copyItem(at: livrosOrigem, to: livrosDestino)
        }
        return support
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
        process.environment = environment
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        try process.run()
        serverProcess = process
        Thread.sleep(forTimeInterval: 0.35)
        if !process.isRunning {
            let data = output.fileHandleForReading.readDataToEndOfFile()
            let text = String(data: data, encoding: .utf8) ?? "sem saída do processo"
            log("motor Python encerrou imediatamente: \(text)")
            throw AppError("O motor local não iniciou. Detalhes: \(text)")
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
        if !pids.isEmpty {
            throw AppError(
                "A porta \(port) está ocupada por outro programa. Feche esse programa e abra o Biblio novamente."
            )
        }
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

    private func waitForServer(port: Int, seconds: Int) throws {
        let deadline = Date().addingTimeInterval(TimeInterval(seconds))
        while Date() < deadline {
            if isBiblioAlive(port: port) {
                return
            }
            Thread.sleep(forTimeInterval: 0.35)
        }
        throw AppError("O motor local não respondeu na porta \(port).")
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
