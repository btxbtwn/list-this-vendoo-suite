import SwiftUI

/// Mirrors the desktop General inspector's section headings and field groups
/// (listingFieldSections.ts). Native marketplace forms remain separate.
struct GeneralListingFields: View {
    @Binding var form: DraftEditorModel.Form
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        ListingInspectorSection("Listing") {
            WorkspaceField("Title") {
                TextField("Title", text: $form.title, axis: .vertical).lineLimit(1...3)
            }
            WorkspaceField("Description") {
                TextField("Describe your item", text: $form.fields.description, axis: .vertical).lineLimit(5...16)
            }
        }
        ListingInspectorSection("Pricing") {
            let layout = dynamicTypeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: 12))
                : AnyLayout(HStackLayout(alignment: .top, spacing: 12))
            layout {
                NumberField("Price", text: $form.price, prefix: "$")
                NumberField("Cost", text: $form.cost, prefix: "$")
            }
        }
        ListingInspectorSection("Condition") {
            TextRow("Condition", text: $form.fields.condition)
        }
        ListingInspectorSection("Item") {
            TextRow("Category", text: $form.fields.categoryPath)
            TextRow("Brand", text: $form.fields.brand)
            TextRow("Department", text: $form.fields.department)
        }
        ListingInspectorSection("Size") { TextRow("Size", text: $form.fields.size) }
        ListingInspectorSection("Color & material") {
            TextRow("Primary Color", text: $form.fields.primaryColor)
            TextRow("Secondary Color", text: $form.fields.secondaryColor)
        }
        ListingInspectorSection("Shipping") {
            TextRow("Inventory location", text: $form.fields.zipCode)
            NumberField("Package Weight (oz)", text: $form.weightOz)
            TextRow("Package Dimensions (LxWxH in)", text: $form.fields.packageDimensionsIn)
        }
        ListingInspectorSection("Inventory & identifiers") {
            WorkspaceField("Quantity") { TextField("1", text: $form.quantity).keyboardType(.numberPad) }
            TextRow("SKU", text: $form.fields.sku)
        }

    }
}

struct ListingInspectorSection<Content: View>: View {
    let title: String
    let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title).font(.subheadline.weight(.semibold)).accessibilityAddTraits(.isHeader)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 16)
        .overlay(alignment: .bottom) { WorkspaceStyle.border.frame(height: 1) }
    }
}
