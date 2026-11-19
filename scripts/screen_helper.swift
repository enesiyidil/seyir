import AppKit
import Foundation
import ImageIO
import Vision

private let arm: CGFloat = 46
private let thick: CGFloat = 8
private let inset: CGFloat = 10
private let box: CGFloat = 78

private final class CornerMark: NSView {
    let towardRight: Bool
    let towardDown: Bool

    init(towardRight: Bool, towardDown: Bool) {
        self.towardRight = towardRight
        self.towardDown = towardDown
        super.init(frame: NSRect(x: 0, y: 0, width: box, height: box))
        wantsLayer = true
    }

    required init?(coder: NSCoder) { nil }

    override func draw(_ dirtyRect: NSRect) {
        let path = NSBezierPath()
        path.lineWidth = thick
        path.lineCapStyle = .round
        path.lineJoinStyle = .round
        let x0 = towardRight ? inset : box - inset
        let y0 = towardDown ? box - inset : inset
        let x1 = towardRight ? inset + arm : box - inset - arm
        let y1 = towardDown ? box - inset - arm : inset + arm
        path.move(to: NSPoint(x: x1, y: y0))
        path.line(to: NSPoint(x: x0, y: y0))
        path.line(to: NSPoint(x: x0, y: y1))
        NSColor.black.withAlphaComponent(0.85).setStroke()
        path.lineWidth = thick + 4
        path.stroke()
        path.lineWidth = thick
        NSColor(calibratedRed: 1, green: 0.42, blue: 0.08, alpha: 1).setStroke()
        path.stroke()
    }

    override func hitTest(_ point: NSPoint) -> NSView? { nil }
}

private func showCorners() {
    let app = NSApplication.shared
    app.setActivationPolicy(.accessory)
    var windows: [NSWindow] = []
    for screen in NSScreen.screens {
        let frame = screen.frame
        let spots: [(CGFloat, CGFloat, Bool, Bool)] = [
            (frame.minX, frame.maxY - box, true, true),
            (frame.maxX - box, frame.maxY - box, false, true),
            (frame.minX, frame.minY, true, false),
            (frame.maxX - box, frame.minY, false, false),
        ]
        for (x, y, right, down) in spots {
            let window = NSWindow(
                contentRect: NSRect(x: x, y: y, width: box, height: box),
                styleMask: [.borderless],
                backing: .buffered,
                defer: false
            )
            window.isOpaque = false
            window.backgroundColor = .clear
            window.hasShadow = false
            window.ignoresMouseEvents = true
            window.level = .screenSaver
            window.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
            window.contentView = CornerMark(towardRight: right, towardDown: down)
            window.orderFrontRegardless()
            windows.append(window)
        }
    }
    withExtendedLifetime(windows) {
        app.run()
    }
}

private func ocr(_ path: String) {
    let url = URL(fileURLWithPath: path)
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        fputs("NO_IMAGE\n", stderr)
        exit(2)
    }
    let bounds = CGDisplayBounds(CGMainDisplayID())
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .fast
    request.usesLanguageCorrection = false
    request.recognitionLanguages = ["tr-TR", "en-US"]
    let handler = VNImageRequestHandler(cgImage: image, options: [:])
    do {
        try handler.perform([request])
    } catch {
        fputs("OCR \(error.localizedDescription)\n", stderr)
        exit(3)
    }
    print("SCREEN \(Int(bounds.width)) \(Int(bounds.height))")
    let observations = (request.results ?? []).sorted { lhs, rhs in
        let ly = lhs.boundingBox.midY
        let ry = rhs.boundingBox.midY
        if abs(ly - ry) > 0.01 { return ly > ry }
        return lhs.boundingBox.minX < rhs.boundingBox.minX
    }
    var count = 0
    for obs in observations {
        if count >= 70 { break }
        guard let candidate = obs.topCandidates(1).first, candidate.confidence > 0.35 else { continue }
        let box = obs.boundingBox
        let x = Int((box.midX) * bounds.width)
        let y = Int((1 - box.midY) * bounds.height)
        let text = candidate.string.replacingOccurrences(of: "\t", with: " ")
        if text.trimmingCharacters(in: .whitespaces).count < 2 { continue }
        print("\(x)\t\(y)\t\(text)")
        count += 1
    }
}

switch CommandLine.arguments.dropFirst().first ?? "" {
case "corners":
    showCorners()
case "ocr":
    let path = CommandLine.arguments.dropFirst(2).first ?? ""
    if path.isEmpty {
        fputs("usage: screen-helper ocr <image>\n", stderr)
        exit(2)
    }
    ocr(path)
default:
    fputs("usage: screen-helper corners | screen-helper ocr <image>\n", stderr)
    exit(2)
}
