import Foundation

@main
struct SellerInputsTests {
    static func main() throws {
        let raw = #"{"sellerNotes":"Original provenance","knownFlaws":"Small mark","sku":"A-17","cog":"8.50","packageDimensions":"12x9x3","vendooLabels":"Spring, Ready","garment":"top","measurements":{"top":{"pitToPit":"22 1/2","length":"27","futureField":true},"pants":{"waist":"16","inseam":"30"}},"categoryOverride":"Clothing > Shirts","future":{"enabled":true,"ids":[1,2]}}"#
        var notes = SellerInputs(notes: raw)
        precondition(notes.sellerNotes == "Original provenance")
        precondition(notes.knownFlaws == "Small mark")
        precondition(notes.sku == "A-17" && notes.cog == "8.50")
        precondition(notes.packageDimensions == "12x9x3")
        precondition(notes.labels == ["Spring", "Ready"])
        precondition(notes.measurement("pitToPit") == "22 1/2")
        let untouched = try notes.encodedNotes()
        precondition(untouched == raw, "An untouched save must preserve original bytes")
        notes.knownFlaws = "Mark near hem"
        notes.setMeasurement("sleeve", value: "9")
        notes.garment = .pants
        precondition(notes.measurement("waist") == "16")
        notes.setMeasurement("rise", value: "11")
        notes.garment = .top
        precondition(notes.measurement("sleeve") == "9", "Switching garments must not discard entered measurements")
        notes.addLabel("spring")
        precondition(notes.labels.count == 2, "Labels are unique ignoring case")
        notes.addLabel("Sold")
        notes.removeLabel("READY")
        precondition(notes.labels == ["Spring", "Sold"])
        let encoded = try notes.encodedNotes()
        let object = try JSONSerialization.jsonObject(with: Data(encoded.utf8)) as! [String: Any]
        precondition(object["categoryOverride"] as? String == "Clothing > Shirts")
        precondition((object["future"] as? [String: Any])?["enabled"] as? Bool == true)
        let all = object["measurements"] as! [String: [String: Any]]
        precondition(all["top"]?["futureField"] as? Bool == true)
        precondition(all["top"]?["length"] as? String == "27")
        precondition(all["pants"]?["inseam"] as? String == "30")
        precondition(all["pants"]?["rise"] as? String == "11")
        let reopened = SellerInputs(notes: encoded)
        precondition(reopened.knownFlaws == "Mark near hem" && reopened.sellerNotes == "Original provenance")
        precondition(reopened.measurement("pitToPit") == "22 1/2")
        var plain = SellerInputs(notes: "Keep this seller narrative exactly")
        plain.sku = "B-2"
        let reopenedPlain = SellerInputs(notes: try plain.encodedNotes())
        precondition(reopenedPlain.sellerNotes == "Keep this seller narrative exactly")
        var clear = SellerInputs(notes: raw)
        clear.knownFlaws = ""
        clear.setMeasurement("length", value: "")
        let cleared = SellerInputs(notes: try clear.encodedNotes())
        precondition(cleared.knownFlaws.isEmpty && cleared.measurement("length").isEmpty)
        precondition(cleared.measurement("pitToPit") == "22 1/2")
        var revert = SellerInputs(notes: raw)
        revert.sku = "Changed"
        revert.sku = "A-17"
        precondition(revert == SellerInputs(notes: raw))
        let reverted = try revert.encodedNotes()
        precondition(reverted == raw)
        print("Seller input preservation tests passed")
    }
}
