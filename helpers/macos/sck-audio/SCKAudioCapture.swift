// SCKAudioCapture.swift — debriefMeet
// Capture audio système via ScreenCaptureKit (macOS 13+).
// Version production de l'helper validé en Phase 0.5 (ex-SCKAudioPOC).
// Fonctionne avec tous les périphériques de sortie : AirPods, USB, intégré.
// Nécessite la permission "Enregistrement de l'écran".
//
// Mode persistant : le stream SCK reste actif en permanence pour éviter
// les coupures audio et changements de qualité lors des démarrages/arrêts.
//
// Protocole stdin  :
//   "START" → commencer l'écriture PCM sur stdout
//   "STOP"  → arrêter l'écriture (le stream SCK continue)
//   "QUIT"  → arrêt propre (stopCapture + exit 0)
// Protocole stderr : "FORMAT:<sr>:<ch>" émis une fois au démarrage du stream
// Protocole stdout : PCM float32 LE interleaved, uniquement en mode RECORDING

import ScreenCaptureKit
import AVFoundation
import CoreMedia
import Foundation

guard #available(macOS 13.0, *) else {
    fputs("[ERREUR] macOS 13.0+ requis\n", stderr)
    exit(1)
}

fputs("[SCK] macOS \(ProcessInfo.processInfo.operatingSystemVersionString)\n", stderr)

// MARK: - État global

nonisolated(unsafe) var gRecording = false
nonisolated(unsafe) var gShouldExit = false

// MARK: - Utilitaires

struct CaptureError: Error, CustomStringConvertible {
    let description: String
    init(_ msg: String) { description = msg }
}

// MARK: - Sortie audio

@available(macOS 13.0, *)
final class AudioOutput: NSObject, SCStreamOutput, SCStreamDelegate, @unchecked Sendable {

    func stream(_ stream: SCStream,
                didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of outputType: SCStreamOutputType) {
        guard outputType == .audio, gRecording else { return }
        guard let data = pcmData(from: sampleBuffer) else { return }
        FileHandle.standardOutput.write(data)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fputs("[ERREUR] Stream arrêté : \(error)\n", stderr)
        gShouldExit = true
    }

    // Extrait PCM float32 interleaved depuis un CMSampleBuffer SCK.
    private func pcmData(from sampleBuffer: CMSampleBuffer) -> Data? {
        guard let fmtDesc = CMSampleBufferGetFormatDescription(sampleBuffer) else { return nil }
        let format = AVAudioFormat(cmAudioFormatDescription: fmtDesc)
        let frameCount = AVAudioFrameCount(CMSampleBufferGetNumSamples(sampleBuffer))
        guard let pcmBuf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount)
        else { return nil }
        pcmBuf.frameLength = frameCount
        guard CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sampleBuffer, at: 0, frameCount: Int32(frameCount),
            into: pcmBuf.mutableAudioBufferList
        ) == noErr else { return nil }
        guard let channelData = pcmBuf.floatChannelData else { return nil }
        let frames = Int(pcmBuf.frameLength)
        let nch    = Int(format.channelCount)
        var pcm = [Float32](repeating: 0, count: frames * nch)
        for f in 0..<frames {
            for c in 0..<nch { pcm[f * nch + c] = channelData[c][f] }
        }
        return pcm.withUnsafeBytes { Data($0) }
    }
}

// MARK: - Capture principale

@available(macOS 13.0, *)
func runCapture() async throws {
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
    guard let display = content.displays.first else {
        throw CaptureError("Aucun display disponible")
    }

    let config = SCStreamConfiguration()
    config.capturesAudio               = true
    config.excludesCurrentProcessAudio = true
    config.sampleRate                  = 48_000
    config.channelCount                = 2
    config.width                       = 2
    config.height                      = 2
    config.minimumFrameInterval        = CMTime(value: 1, timescale: 1)  // 1 fps minimum

    let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
    let output = AudioOutput()
    let stream = SCStream(filter: filter, configuration: config, delegate: output)
    try stream.addStreamOutput(output, type: .audio,
                               sampleHandlerQueue: .global(qos: .userInitiated))
    try await stream.startCapture()

    // Format annoncé une seule fois, dès que le stream est actif
    fputs("FORMAT:\(config.sampleRate):\(config.channelCount)\n", stderr)
    fputs("[OK] SCK active — attente START/STOP/QUIT sur stdin\n", stderr)

    signal(SIGINT,  { _ in gShouldExit = true })
    signal(SIGTERM, { _ in gShouldExit = true })

    // Commandes stdin dans un thread dédié (readLine bloque jusqu'à chaque ligne)
    Thread.detachNewThread {
        while let line = readLine() {
            switch line.trimmingCharacters(in: .whitespaces) {
            case "START":
                gRecording = true
                fputs("[OK] Enregistrement démarré\n", stderr)
            case "STOP":
                gRecording = false
                fputs("[OK] Enregistrement arrêté\n", stderr)
            case "QUIT":
                gShouldExit = true
                return
            default:
                break
            }
        }
        gShouldExit = true  // EOF stdin (parent terminé) → quitter
    }

    while !gShouldExit {
        try await Task.sleep(nanoseconds: 50_000_000)  // 50 ms
    }

    try await stream.stopCapture()
    fputs("[OK] SCK arrêtée\n", stderr)
}

// MARK: - Entrée

Task {
    do {
        try await runCapture()
    } catch {
        fputs("[ERREUR] \(error)\n", stderr)
        exit(2)
    }
    exit(0)
}

dispatchMain()
