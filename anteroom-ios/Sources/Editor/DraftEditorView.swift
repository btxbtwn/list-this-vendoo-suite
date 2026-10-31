import SwiftUI

struct DraftEditorView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var model: DraftEditorModel
    @State private var confirmDiscard = false
    @State private var showingAssistant = false
    @State private var showingHistory = false
    private let onSaved: (Draft) -> Void

    init(api: AnteroomAPI, draft: Draft, onSaved: @escaping (Draft) -> Void) {
        _model = State(initialValue: DraftEditorModel(api: api, draft: draft))
        self.onSaved = onSaved
    }

    var body: some View {
        @Bindable var model = model
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let loadError = model.loadError {
                    WorkspaceSection("Couldn't load listing") {
                        Text(loadError).foregroundStyle(.red)
                        Button("Try again") { Task { await model.load() } }
                    }
                }
                HStack(spacing: 8) {
                    Image(systemName: "square.and.pencil")
                    Text("General").fontWeight(.semibold)
                        .padding(.horizontal, 12).padding(.vertical, 8)
                        .background(WorkspaceStyle.surface, in: RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(WorkspaceStyle.border, lineWidth: 1))
                    Spacer()
                    Text(model.isLoading ? "Loading…" : model.loadError != nil ? "Not loaded" : model.hasChanges ? "Unsaved changes" : "Saved draft")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .font(.subheadline)
                .padding(.horizontal, 4)

                ListingInspectorSection("Photos") {
                    PhotoStrip(api: model.api, draftID: model.draftID)
                }
                SellerInputFields(inputs: $model.form.sellerInputs)
                GeneralListingFields(form: $model.form)
            }
            .padding(16)
        }
        .background(WorkspaceStyle.background)
        .toolbarBackground(WorkspaceStyle.background, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .scrollDismissesKeyboard(.interactively)
        .disabled(model.isLoading && model.loadError == nil)
        .overlay { if model.isLoading { ProgressView() } }
        .navigationTitle(model.form.title.isEmpty ? "Draft" : model.form.title)
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(model.hasChanges)
        .toolbar {
            if model.hasChanges {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { confirmDiscard = true }
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Menu("Listing actions", systemImage: "ellipsis.circle") {
                    Button("Listing assistant", systemImage: "sparkles") { showingAssistant = true }
                    Button("Listing history", systemImage: "clock.arrow.circlepath") { showingHistory = true }
                }
                .frame(minWidth: 44, minHeight: 44)
                .disabled(model.hasChanges || model.isLoading || model.isSaving || model.loadError != nil)
                .accessibilityHint("Save changes first to open the assistant or listing history")
            }
            ToolbarItem(placement: .topBarTrailing) {
                if model.isSaving {
                    ProgressView()
                } else {
                    Button("Save") { save() }
                        .fontWeight(.semibold)
                        .buttonStyle(.borderedProminent)
                        .disabled(!model.hasChanges || model.isSaving)
                }
            }
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done") { hideKeyboard() }
            }
        }
        .confirmationDialog("Discard your changes?", isPresented: $confirmDiscard, titleVisibility: .visible) {
            Button("Discard changes", role: .destructive) { dismiss() }
        }
        .alert("Couldn't save", isPresented: saveErrorShown) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(model.saveError ?? "")
        }
        .alert("Changed on another device", isPresented: $model.hasConflict) {
            Button("Reload", role: .destructive) { Task { await model.load() } }
            Button("Keep editing", role: .cancel) {}
        } message: {
            Text("Reloading shows the latest version and drops your edits here.")
        }
        .sheet(isPresented: $showingAssistant, onDismiss: {
            Task {
                guard !model.hasChanges else { return }
                await model.load()
                if model.loadError == nil { onSaved(model.summary) }
            }
        }) {
            ListingAssistantView(api: model.api, listingID: model.draftID)
        }
        .sheet(isPresented: $showingHistory, onDismiss: {
            Task {
                guard !model.hasChanges else { return }
                await model.load()
                if model.loadError == nil { onSaved(model.summary) }
            }
        }) {
            ListingHistoryView(api: model.api, listingID: model.draftID)
        }
        .task { await model.load() }
    }

    private var saveErrorShown: Binding<Bool> {
        Binding(get: { model.saveError != nil }, set: { if !$0 { model.saveError = nil } })
    }

    private func save() {
        hideKeyboard()
        Task {
            if let draft = await model.save() {
                onSaved(draft)
            }
        }
    }

    private func hideKeyboard() {
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
    }
}

struct TextRow: View {
    let label: String
    @Binding var text: String

    init(_ label: String, text: Binding<String>) {
        self.label = label
        _text = text
    }

    var body: some View {
        WorkspaceField(label) {
            TextField(label, text: $text, axis: .vertical).lineLimit(1...4)
        }
    }
}

struct NumberField: View {
    let label: String
    @Binding var text: String
    var prefix: String?

    init(_ label: String, text: Binding<String>, prefix: String? = nil) {
        self.label = label
        _text = text
        self.prefix = prefix
    }

    var body: some View {
        WorkspaceField(label) {
            HStack(spacing: 2) {
                if let prefix, !text.isEmpty {
                    Text(prefix).foregroundStyle(.secondary)
                }
                TextField("0", text: $text)
                    .accessibilityLabel(label)
                    .keyboardType(.decimalPad)
            }
        }
    }
}
