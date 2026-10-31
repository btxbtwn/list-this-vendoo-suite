import Foundation
import Observation

/// Editable copy of one draft. Numbers are edited as text and checked on save
/// so a half-typed price never silently becomes empty.
@MainActor
@Observable
final class DraftEditorModel {
    struct Form: Equatable {
        var title = ""
        var sellerInputs = SellerInputs()
        var fields = DraftFields()
        var price = ""
        var cost = ""
        var quantity = ""
        var weightOz = ""
        var labels = ""
    }

    let api: AnteroomAPI
    let draftID: String
    private(set) var summary: Draft
    var form = Form()
    private var saved = Form()
    private var updatedAt: String?
    private(set) var isLoading = true
    private(set) var isSaving = false
    private(set) var loadError: String?
    var saveError: String?
    var hasConflict = false

    init(api: AnteroomAPI, draft: Draft) {
        self.api = api
        draftID = draft.id
        summary = draft
        form.title = draft.title ?? ""
        form.sellerInputs = SellerInputs(notes: draft.notes)
        saved = form
    }

    var hasChanges: Bool { !isLoading && form != saved }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            apply(try await api.draft(draftID))
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
    }

    /// Returns the saved draft for inventory, or nil when the save failed.
    func save() async -> Draft? {
        guard let updatedAt else { return nil }
        let fields: DraftFields
        do {
            fields = try validatedFields()
        } catch {
            saveError = error.localizedDescription
            return nil
        }
        let title = form.title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else {
            saveError = "Enter a title."
            return nil
        }
        isSaving = true
        defer { isSaving = false }
        do {
            let detail = try await api.save(draftID, DraftSave(
                title: title, notes: try form.sellerInputs.encodedNotes(), expectedUpdatedAt: updatedAt, fields: fields
            ))
            apply(detail)
            return detail.summary
        } catch let error as APIError where error.isConflict {
            hasConflict = true
        } catch {
            saveError = error.localizedDescription
        }
        return nil
    }

    private func apply(_ detail: DraftDetail) {
        summary = detail.summary
        updatedAt = detail.updatedAt
        var next = Form()
        next.title = detail.title ?? ""
        next.sellerInputs = SellerInputs(notes: detail.notes)
        next.fields = detail.fields
        next.price = Self.text(detail.fields.price)
        next.cost = Self.text(detail.fields.cost)
        next.quantity = detail.fields.quantity.map { String($0) } ?? ""
        next.weightOz = Self.text(detail.fields.weightOz)
        next.labels = detail.fields.labels.joined(separator: ", ")
        form = next
        saved = next
    }

    private func validatedFields() throws -> DraftFields {
        var fields = form.fields
        fields.price = try Self.number(form.price, name: "Price")
        fields.cost = try Self.number(form.cost, name: "Cost")
        fields.weightOz = try Self.number(form.weightOz, name: "Weight")
        let quantity = form.quantity.trimmingCharacters(in: .whitespaces)
        if quantity.isEmpty {
            fields.quantity = nil
        } else if let value = Int(quantity), value >= 1 {
            fields.quantity = value
        } else {
            throw ValidationError("Quantity must be a whole number of 1 or more.")
        }
        fields.labels = form.labels
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        return fields
    }

    private static func number(_ text: String, name: String) throws -> Double? {
        var trimmed = text.trimmingCharacters(in: .whitespaces)
            .replacingOccurrences(of: "$", with: "")
        // A keypad that types "12,50" means 12.50; "1,200.00" uses grouping.
        trimmed = trimmed.contains(".")
            ? trimmed.replacingOccurrences(of: ",", with: "")
            : trimmed.replacingOccurrences(of: ",", with: ".")
        if trimmed.isEmpty { return nil }
        guard let value = Double(trimmed), value >= 0, value.isFinite else {
            throw ValidationError("\(name) must be a number.")
        }
        return value
    }

    private static func text(_ value: Double?) -> String {
        guard let value else { return "" }
        return value.formatted(.number.grouping(.never).precision(.fractionLength(0...2)).locale(Locale(identifier: "en_US_POSIX")))
    }
}

struct ValidationError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
