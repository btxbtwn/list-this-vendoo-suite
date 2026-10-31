#if LAYOUT_REVIEW
import SwiftUI

/// Standalone simulator harness using production layout components and invented
/// sample data. No sign-in, seller data, API requests or marketplace actions.
@main
struct LayoutReviewApp: App {
    var body: some Scene {
        WindowGroup {
            NavigationStack {
                List {
                    Section("Drafts") {
                        sample("Linen button-down shirt", icon: "tshirt.fill", color: .blue)
                        sample("Leather shoulder bag", icon: "bag.fill", color: .brown)
                        sample("Vintage cotton crewneck sweatshirt with embroidered detail", icon: "tshirt.fill", color: .green)
                    }
                    Section {
                        Text("Sample listings · layout review only").font(.footnote).foregroundStyle(.secondary)
                    }
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
                .background(WorkspaceStyle.sidebar)
                .navigationTitle("Inventory")
                .navigationBarTitleDisplayMode(.inline)
            }
            .tint(WorkspaceStyle.accent)
        }
    }

    private func sample(_ title: String, icon: String, color: Color) -> some View {
        NavigationLink {
            EditorLayoutReview(title: title)
        } label: {
            InventoryRowContent(title: title, updated: Date().addingTimeInterval(-3600)) {
                Image(systemName: icon).resizable().scaledToFit().padding(8)
                    .foregroundStyle(color).background(WorkspaceStyle.surface)
            }
        }
        .listRowBackground(Color.clear)
        .listRowSeparator(.hidden)
    }
}

private struct EditorLayoutReview: View {
    let title: String
    @State private var form = DraftEditorModel.Form()

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("General").font(.subheadline.weight(.semibold))
                ListingInspectorSection("Photos") {
                    HStack(spacing: 8) {
                        ForEach(0..<3) { _ in
                            Image(systemName: "tshirt.fill").resizable().scaledToFit().padding(20)
                                .foregroundStyle(.blue)
                                .frame(maxWidth: .infinity).frame(height: 104)
                                .background(WorkspaceStyle.surface, in: RoundedRectangle(cornerRadius: 8))
                        }
                    }
                }
                SellerInputFields(inputs: $form.sellerInputs)
                GeneralListingFields(form: $form)
            }
            .padding(16)
        }
        .background(WorkspaceStyle.background)
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            form.title = title
            form.fields.description = "Soft woven linen with a relaxed fit and button front. Lightly worn and ready for a new home."
            form.price = "32"
            form.cost = "8"
            form.sellerInputs = SellerInputs(notes: #"{"sellerNotes":"Estate sale find","knownFlaws":"Small mark near hem","cog":"8","packageDimensions":"12x9x3","garment":"top","measurements":{"top":{"pitToPit":"22.5","length":"27","sleeve":"9"}}}"#)
            form.quantity = "1"
            form.fields.brand = "Sample brand"
        }
    }
}
#endif
