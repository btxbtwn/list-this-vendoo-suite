import Foundation

/// The desktop ItemDetails notes contract. Keep the original document so
/// editing a known field never drops agent-managed or future fields.
struct SellerInputs: Equatable, Sendable {
    enum Garment: String, CaseIterable, Identifiable, Sendable {
        case top, pants, skirt
        var id: String { rawValue }
        var label: String { rawValue.capitalized }
    }

    private let originalNotes: String
    var sku: String
    var sellerNotes: String
    var knownFlaws: String
    var descriptionMeasurements: String
    var cog: String
    var packageDimensions: String
    var vendooLabels: String
    var garment: Garment
    private var measurements: [String: [String: String]]

    init(notes: String? = nil) {
        let raw = notes ?? ""
        originalNotes = raw
        let object = Self.object(raw)
        sku = object?["sku"] as? String ?? ""
        sellerNotes = object?["sellerNotes"] as? String ?? (object == nil ? raw : "")
        knownFlaws = object?["knownFlaws"] as? String ?? ""
        descriptionMeasurements = object?["descriptionMeasurements"] as? String ?? ""
        cog = object?["cog"] as? String ?? ""
        packageDimensions = object?["packageDimensions"] as? String ?? ""
        vendooLabels = object?["vendooLabels"] as? String ?? ""
        garment = Garment(rawValue: object?["garment"] as? String ?? "") ?? .top
        measurements = ((object?["measurements"] as? [String: Any]) ?? [:]).compactMapValues { group in
            (group as? [String: Any])?.compactMapValues { $0 as? String }
        }
    }

    var labels: [String] {
        vendooLabels.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }

    mutating func addLabel(_ value: String) {
        for candidate in value.split(separator: ",") {
            let label = candidate.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !label.isEmpty, !labels.contains(where: { $0.caseInsensitiveCompare(label) == .orderedSame }) else { continue }
            vendooLabels = (labels + [label]).joined(separator: ", ")
        }
    }

    mutating func removeLabel(_ value: String) {
        vendooLabels = labels.filter { $0.caseInsensitiveCompare(value) != .orderedSame }.joined(separator: ", ")
    }

    func measurement(_ key: String) -> String { measurements[garment.rawValue]?[key] ?? "" }

    mutating func setMeasurement(_ key: String, value: String) {
        measurements[garment.rawValue, default: [:]][key] = value
    }

    func encodedNotes() throws -> String {
        let baseline = Self(notes: originalNotes)
        if self == baseline { return originalNotes }
        var object = Self.object(originalNotes) ?? (originalNotes.isEmpty ? [:] : ["sellerNotes": originalNotes])
        let textValues = [
            ("sku", sku, baseline.sku), ("sellerNotes", sellerNotes, baseline.sellerNotes),
            ("knownFlaws", knownFlaws, baseline.knownFlaws),
            ("descriptionMeasurements", descriptionMeasurements, baseline.descriptionMeasurements),
            ("cog", cog, baseline.cog), ("packageDimensions", packageDimensions, baseline.packageDimensions),
            ("vendooLabels", vendooLabels, baseline.vendooLabels),
        ]
        for (key, value, before) in textValues where value != before { object[key] = value }
        if garment != baseline.garment || measurements != baseline.measurements { object["garment"] = garment.rawValue }
        var all = object["measurements"] as? [String: Any] ?? [:]
        for (group, fields) in measurements {
            var values = all[group] as? [String: Any] ?? [:]
            for (key, value) in fields where value != baseline.measurements[group]?[key] { values[key] = value }
            all[group] = values
        }
        if measurements != baseline.measurements { object["measurements"] = all }
        let data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
        return String(decoding: data, as: UTF8.self)
    }

    private static func object(_ raw: String) -> [String: Any]? {
        (try? JSONSerialization.jsonObject(with: Data(raw.utf8))) as? [String: Any]
    }
}
