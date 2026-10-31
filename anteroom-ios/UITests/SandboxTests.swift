import XCTest

@MainActor
final class SandboxTests: XCTestCase {
    func testCreateAndReopenDraft() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["ANTEROOM_SANDBOX_URL"] = "http://localhost:4320"
        app.launch()
        let create = app.buttons["New listing"].firstMatch
        XCTAssertTrue(create.waitForExistence(timeout: 30))
        create.tap()
        let title = app.textFields["Listing title"].waitForExistence(timeout: 5) ? app.textFields["Listing title"] : app.textViews["Listing title"]
        XCTAssertTrue(title.waitForExistence(timeout: 10))
        title.tap()
        let name = "Simulator draft \(UUID().uuidString.prefix(8))"
        title.typeText(name)
        app.buttons["Create draft"].tap()
        XCTAssertTrue(app.navigationBars[name].waitForExistence(timeout: 15))
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts[name].waitForExistence(timeout: 30))
    }
}

@MainActor
final class SellerInputSandboxTests: XCTestCase {
    func testSellerInputsAndMeasurementsSurviveReopen() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchEnvironment["ANTEROOM_SANDBOX_URL"] = "http://localhost:4320"
        app.launch()
        let create = app.buttons["New listing"].firstMatch
        XCTAssertTrue(create.waitForExistence(timeout: 30))
        create.tap()
        let title = app.textFields["Listing title"].waitForExistence(timeout: 5) ? app.textFields["Listing title"] : app.textViews["Listing title"]
        let name = "Seller inputs \(UUID().uuidString.prefix(8))"
        title.tap()
        title.typeText(name)
        app.buttons["Create draft"].tap()
        XCTAssertTrue(app.navigationBars[name].waitForExistence(timeout: 15))

        enter("seller-notes", text: "Found at a local estate sale", app: app)
        enter("seller-flaws", text: "Small mark near hem", app: app)
        enter("seller-labels", text: "Spring, Ready", app: app)
        attach(app, name: "Seller notes flaws and labels")
        enter("seller-cog", text: "8.50", app: app)
        enter("seller-package", text: "12x9x3", app: app)
        enter("measurement-top-pitToPit", text: "22.5", app: app)
        let picker = app.segmentedControls["seller-garment"]
        XCTAssertTrue(picker.exists)
        picker.buttons["Pants"].tap()
        enter("measurement-pants-waist", text: "16", app: app)
        reveal(picker, app: app)
        picker.buttons["Top"].tap()
        XCTAssertEqual(field("measurement-top-pitToPit", app: app).value as? String, "22.5")
        attach(app, name: "Seller inputs before save")
        let done = app.toolbars.buttons["Done"].firstMatch
        if done.exists { done.tap() }
        app.navigationBars[name].buttons["Save"].tap()
        XCTAssertTrue(app.navigationBars[name].buttons["Save"].waitForExistence(timeout: 10))
        let saved = NSPredicate(format: "enabled == false")
        expectation(for: saved, evaluatedWith: app.navigationBars[name].buttons["Save"])
        waitForExpectations(timeout: 15)

        app.terminate()
        app.launch()
        let row = app.staticTexts[name]
        XCTAssertTrue(row.waitForExistence(timeout: 30))
        row.tap()
        XCTAssertTrue(app.navigationBars[name].waitForExistence(timeout: 15))
        XCTAssertEqual(field("seller-notes", app: app).value as? String, "Found at a local estate sale")
        XCTAssertEqual(field("seller-flaws", app: app).value as? String, "Small mark near hem")
        XCTAssertEqual(field("seller-package", app: app).value as? String, "12x9x3")
        XCTAssertEqual(field("measurement-top-pitToPit", app: app).value as? String, "22.5")
        reveal(app.segmentedControls["seller-garment"], app: app)
        app.segmentedControls["seller-garment"].buttons["Pants"].tap()
        XCTAssertEqual(field("measurement-pants-waist", app: app).value as? String, "16")
        attach(app, name: "Reopened garment measurements")
    }

    private func enter(_ id: String, text: String, app: XCUIApplication) {
        let control = field(id, app: app)
        control.tap()
        control.typeText(text)
    }

    private func field(_ id: String, app: XCUIApplication) -> XCUIElement {
        let control = app.descendants(matching: .any).matching(identifier: id).firstMatch
        XCTAssertTrue(control.waitForExistence(timeout: 10), "Missing native seller field: \(id)")
        reveal(control, app: app)
        return control
    }

    private func reveal(_ control: XCUIElement, app: XCUIApplication) {
        for _ in 0..<12 {
            if control.isHittable { return }
            app.scrollViews.firstMatch.swipeUp()
        }
        // A previously edited field may now be above the viewport.
        for _ in 0..<12 {
            if control.isHittable { return }
            app.scrollViews.firstMatch.swipeDown()
        }
        XCTAssertTrue(control.isHittable)
    }

    private func attach(_ app: XCUIApplication, name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
