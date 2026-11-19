import AVFoundation
import Foundation
import Speech

private let turkish = Locale(identifier: "tr-TR")

private func authorize() -> Bool {
    if SFSpeechRecognizer.authorizationStatus() == .authorized {
        return true
    }
    let group = DispatchGroup()
    group.enter()
    var ok = false
    SFSpeechRecognizer.requestAuthorization { status in
        ok = status == .authorized
        fputs("AUTH \(status.rawValue)\n", stderr)
        fflush(stderr)
        group.leave()
    }
    let deadline = Date().addingTimeInterval(15)
    while group.wait(timeout: .now()) == .timedOut {
        if Date() > deadline {
            return false
        }
        RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.2))
    }
    return ok
}

private func transcribeFile(_ path: String) {
    SFSpeechRecognizer.requestAuthorization { status in
        DispatchQueue.main.async {
            fputs("AUTH \(status.rawValue)\n", stderr)
            fflush(stderr)
            guard status == .authorized else {
                fputs("PERMISSION_NEEDED\n", stderr)
                fflush(stderr)
                exit(4)
            }
            guard let recognizer = SFSpeechRecognizer(locale: turkish), recognizer.isAvailable else {
                fputs("NO_RECOGNIZER\n", stderr)
                fflush(stderr)
                exit(3)
            }
            let request = SFSpeechURLRecognitionRequest(url: URL(fileURLWithPath: path))
            request.shouldReportPartialResults = true
            request.contextualStrings = ["Cursor", "cursora", "ajana", "gönder", "agent", "sohbet", "yaz"]
            let lock = NSLock()
            var spoken = ""
            var finished = false
            func finish() {
                lock.lock()
                if finished {
                    lock.unlock()
                    return
                }
                finished = true
                let text = spoken
                lock.unlock()
                print(text)
                fflush(stdout)
                exit(text.isEmpty ? 1 : 0)
            }
            recognizer.recognitionTask(with: request) { result, error in
                if let result {
                    lock.lock()
                    spoken = result.bestTranscription.formattedString
                    let done = result.isFinal
                    lock.unlock()
                    if done {
                        finish()
                    }
                } else if let error {
                    fputs("ERR \(error.localizedDescription)\n", stderr)
                    fflush(stderr)
                    finish()
                }
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
                finish()
            }
        }
    }
    dispatchMain()
}

private func listen() {
    guard authorize() else {
        fputs("PERMISSION_NEEDED\n", stderr)
        exit(4)
    }
    guard let recognizer = SFSpeechRecognizer(locale: turkish), recognizer.isAvailable else {
        fputs("NO_RECOGNIZER\n", stderr)
        exit(3)
    }
    let engine = AVAudioEngine()
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.shouldReportPartialResults = false
    let input = engine.inputNode
    let format = input.outputFormat(forBus: 0)
    input.installTap(onBus: 0, bufferSize: 2048, format: format) { buffer, _ in
        request.append(buffer)
    }
    engine.prepare()
    do {
        try engine.start()
    } catch {
        fputs("MIC \(error.localizedDescription)\n", stderr)
        exit(5)
    }
    fputs("LISTENING\n", stderr)
    fflush(stderr)
    recognizer.recognitionTask(with: request) { result, error in
        if let result, result.isFinal {
            let text = result.bestTranscription.formattedString
            if !text.isEmpty {
                print(text)
                fflush(stdout)
            }
        } else if let error {
            fputs("ERR \(error.localizedDescription)\n", stderr)
            fflush(stderr)
        }
    }
    dispatchMain()
}

switch CommandLine.arguments.dropFirst().first ?? "" {
case "transcribe":
    let path = CommandLine.arguments.dropFirst(2).first ?? ""
    if path.isEmpty {
        fputs("usage: speech transcribe <wav>\n", stderr)
        exit(2)
    }
    transcribeFile(path)
case "listen":
    listen()
default:
    fputs("usage: speech transcribe <wav> | speech listen\n", stderr)
    exit(2)
}
