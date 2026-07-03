// AudioTapPOC.swift — debriefMeet Phase 0.5
// Capture audio système via Core Audio taps (macOS 14.2+).
// Ne nécessite PAS la permission "Enregistrement de l'écran", seulement NSAudioCaptureUsageDescription.
//
// Protocole stdout :
//   - Ligne d'en-tête sur stderr : "FORMAT:<sampleRate>:<channels>"
//   - Ensuite : PCM float32 little-endian interleaved sur stdout.
//
// Usage : ./AudioTapPOC [durée_secondes]   (0 = infini jusqu'à signal)

import CoreAudio
import AVFoundation
import Foundation

// MARK: - Garde version

guard #available(macOS 14.2, *) else {
    fputs("[ERREUR] macOS 14.2+ requis (actuel: \(ProcessInfo.processInfo.operatingSystemVersionString))\n", stderr)
    exit(1)
}

fputs("[POC] macOS \(ProcessInfo.processInfo.operatingSystemVersionString)\n", stderr)

let durationSec = Double(CommandLine.arguments.dropFirst().first ?? "0") ?? 0.0

// MARK: - Flag d'arrêt (global pour les signal handlers C)
nonisolated(unsafe) var gShouldExit = false

// MARK: - Utilitaires

func fourCC(_ s: OSStatus) -> String {
    let v = UInt32(bitPattern: s)
    let chars = [
        Character(Unicode.Scalar((v >> 24) & 0xFF)!),
        Character(Unicode.Scalar((v >> 16) & 0xFF)!),
        Character(Unicode.Scalar((v >>  8) & 0xFF)!),
        Character(Unicode.Scalar( v        & 0xFF)!),
    ]
    let str = String(chars)
    return str.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == " ") } ? str : "0x\(String(v, radix:16))"
}

struct POCError: Error, CustomStringConvertible {
    let description: String
    init(_ msg: String) { description = msg }
}

// MARK: - Création du tap

@available(macOS 14.2, *)
func creerTap() throws -> (id: AudioObjectID, uid: String) {
    let tapDesc = CATapDescription()
    tapDesc.name = "debriefMeet-poc-tap"
    // exclusive=true + processes vide → capter TOUS les processus
    tapDesc.isExclusive = true  // tap ALL processes
    tapDesc.isMixdown   = true  // stereo mixdown
    tapDesc.isMono      = false // stereo (pas mono)
    // CATapMuteBehavior(rawValue:0) = CATapUnmuted : audio capturé ET envoyé au matériel
    tapDesc.muteBehavior = CATapMuteBehavior(rawValue: 0)!
    tapDesc.isPrivate = true    // invisible dans le Centre de contrôle

    // Pré-assigner l'UUID pour pouvoir l'utiliser ensuite dans l'aggregate device
    let tapUUID = UUID()
    tapDesc.uuid = tapUUID

    var tapID: AudioObjectID = kAudioObjectUnknown
    let status = AudioHardwareCreateProcessTap(tapDesc, &tapID)
    guard status == noErr else {
        fputs("[ERREUR] AudioHardwareCreateProcessTap: \(status) (\(fourCC(status)))\n", stderr)
        throw POCError("Création tap: \(status)")
    }
    let uid = tapUUID.uuidString
    fputs("[OK] Tap créé — AudioObjectID=\(tapID)  UID=\(uid)\n", stderr)
    return (tapID, uid)
}

// MARK: - Aggregate device

@available(macOS 14.2, *)
func creerAggregateDevice(tapUID: String) throws -> AudioObjectID {
    let aggUID = "com.sylvaingarcia.debriefmeet.poc.\(tapUID.prefix(8))"
    let desc: [String: Any] = [
        kAudioAggregateDeviceNameKey      as String: "debriefMeet POC",
        kAudioAggregateDeviceUIDKey       as String: aggUID,
        kAudioAggregateDeviceIsPrivateKey as String: 1,
        // kAudioAggregateDeviceTapListKey = "taps", kAudioSubTapUIDKey = "uid"
        kAudioAggregateDeviceTapListKey   as String: [
            [kAudioSubTapUIDKey as String: tapUID]
        ],
        kAudioAggregateDeviceTapAutoStartKey as String: 1,
    ]
    var aggID: AudioObjectID = kAudioObjectUnknown
    let status = AudioHardwareCreateAggregateDevice(desc as CFDictionary, &aggID)
    guard status == noErr else {
        fputs("[ERREUR] AudioHardwareCreateAggregateDevice: \(status) (\(fourCC(status)))\n", stderr)
        throw POCError("Aggregate device: \(status)")
    }
    fputs("[OK] Aggregate device — AudioObjectID=\(aggID)\n", stderr)
    return aggID
}

// MARK: - Capture AVAudioEngine

@available(macOS 14.2, *)
func demarrerCapture(aggDeviceID: AudioObjectID) throws -> AVAudioEngine {
    let engine = AVAudioEngine()
    let inputNode = engine.inputNode

    // Pointer l'input de l'engine sur l'aggregate device contenant le tap
    guard let au = inputNode.audioUnit else {
        throw POCError("inputNode.audioUnit est nil")
    }
    var devID = aggDeviceID
    let status = AudioUnitSetProperty(
        au,
        kAudioOutputUnitProperty_CurrentDevice,
        kAudioUnitScope_Global,
        0,
        &devID,
        UInt32(MemoryLayout<AudioDeviceID>.size)
    )
    guard status == noErr else {
        fputs("[ERREUR] AudioUnitSetProperty CurrentDevice: \(status) (\(fourCC(status)))\n", stderr)
        throw POCError("Set device: \(status)")
    }

    let fmt = inputNode.outputFormat(forBus: 0)
    let sr  = Int(fmt.sampleRate)
    let ch  = Int(fmt.channelCount)
    fputs("FORMAT:\(sr):\(ch)\n", stderr)
    fputs("[OK] Capture démarrée — float32 \(sr)Hz \(ch)ch sur stdout\n", stderr)

    inputNode.installTap(onBus: 0, bufferSize: 4096, format: fmt) { buf, _ in
        guard let data = buf.floatChannelData else { return }
        let frames = Int(buf.frameLength)
        let nch    = Int(buf.format.channelCount)
        var pcm = [Float32](repeating: 0, count: frames * nch)
        for f in 0..<frames {
            for c in 0..<nch { pcm[f * nch + c] = data[c][f] }
        }
        pcm.withUnsafeBytes { FileHandle.standardOutput.write(Data($0)) }
    }

    try engine.start()
    return engine
}

// MARK: - Main

do {
    let tap    = try creerTap()
    let aggID  = try creerAggregateDevice(tapUID: tap.uid)
    let engine = try demarrerCapture(aggDeviceID: aggID)

    signal(SIGINT,  { _ in gShouldExit = true })
    signal(SIGTERM, { _ in gShouldExit = true })

    let deadline = durationSec > 0
        ? Date().addingTimeInterval(durationSec)
        : Date.distantFuture
    while !gShouldExit && Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.05))
    }

    engine.inputNode.removeTap(onBus: 0)
    engine.stop()
    AudioHardwareDestroyAggregateDevice(aggID)
    AudioHardwareDestroyProcessTap(tap.id)
    fputs("[OK] Terminé\n", stderr)
    exit(0)

} catch {
    fputs("[ERREUR] \(error)\n", stderr)
    exit(2)
}
