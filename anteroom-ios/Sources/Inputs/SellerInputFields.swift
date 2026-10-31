import SwiftUI

/// Native controls for the desktop ItemDetails contract, before generated fields.
struct SellerInputFields: View {
    @Binding var inputs: SellerInputs
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        ListingInspectorSection("Notes & Labels") {
            WorkspaceField("SKU") {
                TextField("Optional", text: $inputs.sku)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .accessibilityIdentifier("seller-sku")
            }
            WorkspaceField("Notes") {
                TextField("Provenance, sizing quirks, or anything the description should mention", text: $inputs.sellerNotes, axis: .vertical)
                    .lineLimit(2...6).accessibilityIdentifier("seller-notes")
            }
            WorkspaceField("Flaws") {
                TextField("Stains, holes, or wear to mention in the description", text: $inputs.knownFlaws, axis: .vertical)
                    .lineLimit(2...6).accessibilityIdentifier("seller-flaws")
            }
            WorkspaceField("Labels") {
                TextField("Separate labels with commas", text: $inputs.vendooLabels)
                    .onSubmit {
                        let labels = inputs.vendooLabels
                        inputs.vendooLabels = ""
                        inputs.addLabel(labels)
                    }
                    .accessibilityIdentifier("seller-labels")
            }
            if !inputs.labels.isEmpty {
                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(Array(inputs.labels.enumerated()), id: \.offset) { _, label in
                            Button { inputs.removeLabel(label) } label: {
                                Label(label, systemImage: "xmark.circle.fill")
                                    .font(.subheadline).padding(.horizontal, 12).frame(minHeight: 44)
                            }
                            .buttonStyle(.bordered)
                            .accessibilityLabel("Remove label \(label)")
                        }
                    }
                }
            }
        }
        ListingInspectorSection("Pricing & Shipping") {
            let layout = dynamicTypeSize.isAccessibilitySize
                ? AnyLayout(VStackLayout(alignment: .leading, spacing: 12))
                : AnyLayout(HStackLayout(alignment: .top, spacing: 12))
            layout {
                WorkspaceField("COG ($)") {
                    TextField("Cost of goods", text: $inputs.cog)
                        .keyboardType(.decimalPad).accessibilityIdentifier("seller-cog")
                }
                WorkspaceField("Package L×W×H") {
                    TextField("Length × width × height", text: $inputs.packageDimensions)
                        .autocorrectionDisabled().accessibilityIdentifier("seller-package")
                }
            }
        }
        ListingInspectorSection("Measurements (in)") {
            if dynamicTypeSize.isAccessibilitySize {
                garmentPicker.pickerStyle(.menu)
            } else {
                garmentPicker.pickerStyle(.segmented)
            }
            ForEach(measurementFields, id: \.key) { field in
                WorkspaceField(field.label) {
                    TextField("Inches", text: Binding(
                        get: { inputs.measurement(field.key) },
                        set: { inputs.setMeasurement(field.key, value: $0) }
                    ))
                    .keyboardType(.numbersAndPunctuation)
                    .accessibilityIdentifier("measurement-\(inputs.garment.rawValue)-\(field.key)")
                }
            }
            WorkspaceField("Other measurements") {
                TextField("Anything the fields above miss", text: $inputs.descriptionMeasurements, axis: .vertical)
                    .lineLimit(2...6).accessibilityIdentifier("seller-other-measurements")
            }
        }
    }

    private var garmentPicker: some View {
        Picker("Garment", selection: $inputs.garment) {
            ForEach(SellerInputs.Garment.allCases) { garment in
                Text(garment.label).tag(garment)
            }
        }
        .accessibilityIdentifier("seller-garment")
    }

    // Field keys and labels are the shared UI/JSON contract from desktop's
    // garmentMeasurements.ts and the backend GARMENT_MEASUREMENTS definition.
    private var measurementFields: [(key: String, label: String)] {
        switch inputs.garment {
        case .top: return [("pitToPit", "Pit to Pit"), ("length", "Length"), ("sleeve", "Sleeve")]
        case .pants: return [("waist", "Waist"), ("rise", "Rise"), ("inseam", "Inseam"), ("legOpening", "Leg Opening")]
        case .skirt: return [("waist", "Waist"), ("hip", "Hip"), ("length", "Length")]
        }
    }
}
