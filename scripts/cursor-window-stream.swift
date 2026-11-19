import AppKit
import CoreGraphics
import CoreMedia
import CoreVideo
import Foundation
import ScreenCaptureKit

final class FrameOutput: NSObject, SCStreamOutput {
    private let lock = NSLock()
    private var started = false

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of type: SCStreamOutputType
    ) {
        guard type == .screen, CMSampleBufferGetImageBuffer(sampleBuffer) != nil else {
            return
        }
        guard let pixel = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        CVPixelBufferLockBaseAddress(pixel, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixel, .readOnly) }
        let width = CVPixelBufferGetWidth(pixel)
        let height = CVPixelBufferGetHeight(pixel)
        let rowBytes = CVPixelBufferGetBytesPerRow(pixel)
        guard let base = CVPixelBufferGetBaseAddress(pixel) else { return }
        lock.lock()
        if !started {
            started = true
            fputs("SIZE \(width) \(height)\n", stderr)
            fflush(stderr)
        }
        lock.unlock()
        let packed = width * 4
        if rowBytes == packed {
            let data = Data(bytes: base, count: packed * height)
            FileHandle.standardOutput.write(data)
        } else {
            var data = Data(count: packed * height)
            data.withUnsafeMutableBytes { raw in
                guard let dst = raw.baseAddress else { return }
                for y in 0..<height {
                    memcpy(dst.advanced(by: y * packed), base.advanced(by: y * rowBytes), packed)
                }
            }
            FileHandle.standardOutput.write(data)
        }
    }
}

@main
struct CursorWindowStream {
    static func main() {
        fputs("STARTING\n", stderr)
        fflush(stderr)
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        DispatchQueue.main.async {
            Task { @MainActor in
                await run()
            }
        }
        app.run()
    }

    @MainActor
    static func run() async {
        fputs("CAPTURE\n", stderr)
        fflush(stderr)
        let allowed = CGPreflightScreenCaptureAccess()
        fputs("PREFLIGHT \(allowed)\n", stderr)
        fflush(stderr)
        if !allowed {
            let granted = CGRequestScreenCaptureAccess()
            fputs(granted ? "REQUEST granted\n" : "PERMISSION_NEEDED\n", stderr)
            fflush(stderr)
            if !granted {
                exit(4)
            }
        }
        let project = CommandLine.arguments.dropFirst().first ?? ""
        do {
            fputs("LISTING\n", stderr)
            fflush(stderr)
            let content = try await SCShareableContent.current
            let matches = content.windows.filter { window in
                let owner = window.owningApplication?.applicationName ?? ""
                guard owner == "Cursor" else { return false }
                if project.isEmpty { return true }
                let title = window.title ?? ""
                return title.localizedCaseInsensitiveContains(project)
            }
            let pool = matches.isEmpty && project.isEmpty ? [] : matches
            let windows = pool.isEmpty && !project.isEmpty
                ? content.windows.filter { ($0.owningApplication?.applicationName ?? "") == "Cursor" }
                : pool
            guard let window = windows.max(by: { area($0) < area($1) }) else {
                fputs("NO_WINDOW\n", stderr)
                exit(2)
            }
            let scale = 2
            var width = max(2, Int(window.frame.width) * scale)
            var height = max(2, Int(window.frame.height) * scale)
            width -= width % 2
            height -= height % 2
            let filter = SCContentFilter(desktopIndependentWindow: window)
            let config = SCStreamConfiguration()
            config.width = width
            config.height = height
            config.pixelFormat = kCVPixelFormatType_32BGRA
            config.showsCursor = true
            config.minimumFrameInterval = CMTime(value: 1, timescale: 8)
            config.queueDepth = 4
            let output = FrameOutput()
            let stream = SCStream(filter: filter, configuration: config, delegate: nil)
            try stream.addStreamOutput(
                output,
                type: .screen,
                sampleHandlerQueue: DispatchQueue(label: "cursor-window-frames")
            )
            try await stream.startCapture()
            // NSApplication.run keeps the process alive.
        } catch {
            fputs("CAPTURE_ERROR \(error.localizedDescription)\n", stderr)
            exit(3)
        }
    }

    static func area(_ window: SCWindow) -> CGFloat {
        window.frame.width * window.frame.height
    }
}
