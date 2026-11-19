import AppKit
import ApplicationServices
import CryptoKit
import Foundation
import Vision

// Local, user-directed input. Only the active window of the requested application is inspected.
struct InputError: Error {
  let message: String
  let code: String
  init(_ message: String, code: String = "input") {
    self.message = message
    self.code = code
  }
}
let workspace = NSWorkspace.shared
func normalized(_ s: String) -> String {
  s.folding(
    options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "tr_TR")
  )
  .lowercased().replacingOccurrences(of: "ı", with: "i").trimmingCharacters(
    in: .whitespacesAndNewlines)
}
func attribute(_ e: AXUIElement, _ name: String) -> CFTypeRef? {
  var v: CFTypeRef?
  guard AXUIElementCopyAttributeValue(e, name as CFString, &v) == .success else { return nil }
  return v
}
func element(_ e: AXUIElement, _ key: String) -> AXUIElement? {
  guard let v = attribute(e, key), CFGetTypeID(v) == AXUIElementGetTypeID() else { return nil }
  return (v as! AXUIElement)
}
func str(_ e: AXUIElement, _ key: String) -> String { attribute(e, key) as? String ?? "" }
func labels(_ e: AXUIElement) -> [String] {
  ["AXTitle", "AXDescription", "AXPlaceholderValue", "AXIdentifier", "AXHelp", "AXDOMIdentifier"]
    .map { normalized(str(e, $0)) }.filter { !$0.isEmpty }
}
func nodes(_ root: AXUIElement, _ predicate: (AXUIElement, String) -> Bool) -> [AXUIElement] {
  var queue = [root]
  var index = 0
  var result = [AXUIElement]()
  var visited = Set<AXUIElement>()
  while index < queue.count && index < 2600 {
    let e = queue[index]
    index += 1
    guard visited.insert(e).inserted else { continue }
    let role = str(e, "AXRole")
    if predicate(e, role) { result.append(e) }
    if let children = attribute(e, "AXChildren") as? [AXUIElement] {
      queue.append(contentsOf: children)
    }
  }
  return result
}
func waitFor<T>(_ seconds: Double, _ f: () -> T?) -> T? {
  let deadline = Date().addingTimeInterval(seconds)
  repeat {
    if let v = f() { return v }
    RunLoop.current.run(until: Date().addingTimeInterval(0.04))
  } while Date() < deadline
  return nil
}
let textRoles = ["AXTextArea", "AXTextField", "AXComboBox"]
func editable(_ e: AXUIElement) -> Bool {
  textRoles.contains(str(e, "AXRole")) && str(e, "AXSubrole") != "AXSecureTextField"
    && (attribute(e, "AXEnabled") as? Bool) != false
}
func isComposer(_ e: AXUIElement) -> Bool {
  guard editable(e) else { return false }
  let tags = labels(e) + ((attribute(e, "AXDOMClassList") as? [String]) ?? []).map(normalized)
  let clues = [
    "composer", "prosemirror", "tiptap", "type a message", "bir ileti yaz", "bir mesaj yaz",
    "mesaj yaz", "ask for follow-up", "ask anything", "takip sorusu", "follow up",
    "mesaj kutusu", "send a message", "message input", "chat input", "prompt-textarea",
  ]
  return tags.contains { label in clues.contains(where: { label.contains($0) }) }
}
func composer(_ app: AXUIElement, window: AXUIElement) -> AXUIElement? {
  if let f = element(app, "AXFocusedUIElement"), isComposer(f) { return f }
  let choices = nodes(window) { e, r in textRoles.contains(r) && isComposer(e) }
  return choices.count == 1 ? choices[0] : nil
}
func focused(_ app: AXUIElement, _ field: AXUIElement) -> Bool {
  guard let current = element(app, "AXFocusedUIElement") else { return false }
  return CFEqual(current, field)
}
func focus(_ app: AXUIElement, _ e: AXUIElement) throws {
  if focused(app, e) { return }
  AXUIElementSetAttributeValue(e, "AXFocused" as CFString, kCFBooleanTrue)
  guard waitFor(0.5, { focused(app, e) ? true : nil }) != nil else {
    throw InputError("Yazı alanına odaklanamadım.")
  }
}
func key(
  _ running: NSRunningApplication, _ code: CGKeyCode, _ flags: CGEventFlags = [],
  text: String? = nil
) throws {
  guard running.isActive else { throw InputError("Öndeki uygulama değişti. İşlemi durdurdum.") }
  for down in [true, false] {
    guard let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down) else {
      throw InputError("Klavye girdisi oluşturulamadı.")
    }
    event.flags = flags
    if let text {
      let chars = Array(text.utf16)
      event.keyboardSetUnicodeString(stringLength: chars.count, unicodeString: chars)
    }
    event.postToPid(running.processIdentifier)
  }
}
func insert(
  _ text: String, into field: AXUIElement, app: AXUIElement, running: NSRunningApplication
) throws {
  try focus(app, field)
  guard let old = attribute(field, "AXValue") as? String, !text.isEmpty,
    text.count <= 2000, !text.contains(where: { $0.isNewline || $0 == "\t" })
  else { throw InputError("Metin alanını doğrulayamadım.") }
  var range = CFRange()
  let rangeValue = attribute(field, "AXSelectedTextRange")
  let known =
    rangeValue.map {
      CFGetTypeID($0) == AXValueGetTypeID() && AXValueGetValue(($0 as! AXValue), .cfRange, &range)
    } ?? false
  let previous = old as NSString
  guard
    (known && range.location >= 0 && range.length >= 0
      && range.location + range.length <= previous.length) || old.isEmpty
  else {
    throw InputError("İmlecin yerini doğrulayamadım. Yazı alanına dokun.")
  }
  let expected = previous.replacingCharacters(
    in: known
      ? NSRange(location: range.location, length: range.length) : NSRange(location: 0, length: 0),
    with: text)
  // Use the application's normal editing path so Electron/WebView updates its draft state.
  var chunk = ""
  for c in text {
    if chunk.utf16.count + String(c).utf16.count > 20 {
      guard focused(app, field) else { throw InputError("Yazı alanı değişti.") }
      try key(running, 0, text: chunk)
      chunk = ""
    }
    chunk.append(c)
  }
  guard focused(app, field) else { throw InputError("Yazı alanı değişti.") }
  try key(running, 0, text: chunk)
  guard waitFor(0.9, { str(field, "AXValue") == expected ? true : nil }) != nil else {
    throw InputError("Yazma sonucu doğrulanamadı. Taslağı ekrandan kontrol et.")
  }
}

func conversationTitle(_ window: AXUIElement, matches name: String) -> Bool {
  // A selected chat title, never text in the sidebar or message history.
  let parts = str(window, "AXTitle").components(separatedBy: " | ").map(normalized)
  return parts.contains(normalized(name))
    && parts.contains(where: { ["chat", "sohbet", "chats"].contains($0) })
}
func teamsRecipient(_ who: String, app: AXUIElement, running: NSRunningApplication) throws {
  let name = normalized(who)
  guard !name.isEmpty else {
    throw InputError("Teams’te kime yazayım? Ad soyad veya e-posta söyle.")
  }
  // Even an exact current window title can belong to a namesake. Resolve via the people picker.
  try key(running, 45, .maskCommand)
  guard
    let picker = waitFor(
      2.0,
      { () -> AXUIElement? in
        guard let e = element(app, "AXFocusedUIElement"), editable(e) else { return nil }
        let hints = labels(e)
        return hints.contains(where: { hint in
          ["to", "to:", "kime", "kime:"].contains(hint)
            || [
              "name, email", "name, e-mail", "ad, e-posta", "enter name", "enter a name",
              "kisi ekle", "ad veya e-posta", "isim veya e-posta",
            ].contains(where: hint.contains)
        }) && !isComposer(e) ? e : nil
      })
  else {
    throw InputError(
      "Teams alıcı alanını açamadım. Yeni sohbet penceresini kontrol et.", code: "picker")
  }
  guard str(picker, "AXValue").isEmpty else {
    throw InputError("Teams alıcı alanı dolu. Yeni bir sohbet aç.")
  }
  try insert(who, into: picker, app: app, running: running)
  func options() -> [AXUIElement] {
    guard let current = element(app, "AXFocusedWindow") else { return [] }
    let lists = nodes(current) { _, r in ["AXListBox", "AXList"].contains(r) }
    return lists.flatMap { list in
      nodes(list) { e, r in
        guard
          ["AXOption", "AXRow", "AXCell", "AXRadioButton", "AXButton", "AXStaticText"].contains(r)
        else { return false }
        var actions: CFArray?
        AXUIElementCopyActionNames(e, &actions)
        let children = (attribute(e, "AXChildren") as? [AXUIElement] ?? []).prefix(10)
        let childNames = children.filter { str($0, "AXRole") == "AXStaticText" }.map {
          normalized(str($0, "AXValue"))
        }
        let names = (labels(e) + childNames).flatMap {
          $0.components(separatedBy: CharacterSet(charactersIn: ",;\n"))
        }.map(normalized)
        return names.contains(name) && ((actions as? [String]) ?? []).contains("AXPress")
      }
    }
  }
  guard
    let matches = waitFor(
      2.5,
      {
        let found = options()
        return found.isEmpty ? nil : found
      })
  else {
    throw InputError(
      "Teams’te tek bir alıcı doğrulanamadı. Ad soyad veya e-posta ile tekrar söyle.",
      code: "recipient")
  }
  var unique = [AXUIElement]()
  for e in matches where !unique.contains(where: { CFEqual($0, e) }) { unique.append(e) }
  guard unique.count == 1 else {
    throw InputError(
      "Aynı isimle birden fazla Teams kişisi var. Alıcının e-postasını söyle.", code: "recipient")
  }
  guard running.isActive, focused(app, picker),
    AXUIElementPerformAction(unique[0], "AXPress" as CFString) == .success
  else { throw InputError("Teams alıcısını seçemedim.") }
  guard
    waitFor(
      1.4,
      { () -> Bool? in
        guard let w = element(app, "AXFocusedWindow") else { return nil }
        if conversationTitle(w, matches: who) { return true }
        // New-chat recipient chips expose a remove action with the selected identity.
        let chips = nodes(w) { e, r in
          r == "AXButton"
            && labels(e).contains {
              ["remove " + name, name + " kişisini kaldır", name + " kisisini kaldir"].map(
                normalized
              ).contains($0)
            }
        }
        return chips.count == 1 ? true : nil
      }) != nil
  else { throw InputError("Seçilen Teams sohbetinin alıcısını doğrulayamadım.") }
}
struct DraftLine {
  let text: String
  let box: CGRect
}
struct DraftSurface {
  let window: CGWindowID
  let frame: CGRect
  let point: CGPoint
  let inputBand: CGRect
  let lines: [DraftLine]
  let emptyInput: Bool
}
func readLines(_ wid: CGWindowID) -> [DraftLine] {
  let file = FileManager.default.temporaryDirectory.appendingPathComponent(
    UUID().uuidString + ".jpg")
  defer { try? FileManager.default.removeItem(at: file) }
  let p = Process()
  p.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
  p.arguments = ["-x", "-o", "-l", String(wid), "-t", "jpg", file.path]
  guard (try? p.run()) != nil else { return [] }
  p.waitUntilExit()
  guard p.terminationStatus == 0 else { return [] }
  let req = VNRecognizeTextRequest()
  req.recognitionLevel = .accurate
  req.usesLanguageCorrection = false
  req.recognitionLanguages = ["en-US", "tr-TR"]
  guard (try? VNImageRequestHandler(url: file).perform([req])) != nil else { return [] }
  return (req.results ?? []).compactMap { item in
    guard let candidate = item.topCandidates(1).first, candidate.confidence > 0.45 else {
      return nil
    }
    let b = item.boundingBox
    return DraftLine(
      text: normalized(candidate.string),
      box: CGRect(x: b.minX, y: 1 - b.maxY, width: b.width, height: b.height))
  }
}
struct AppWindow {
  let id: CGWindowID
  let frame: CGRect
}
func activeWindow(_ target: NSRunningApplication) -> AppWindow? {
  guard target.isActive,
    let rows = CGWindowListCopyWindowInfo(
      [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID) as? [[String: Any]]
  else { return nil }
  for row in rows {
    if row[kCGWindowOwnerPID as String] as? Int32 == target.processIdentifier,
      row[kCGWindowLayer as String] as? Int == 0,
      let wid = row[kCGWindowNumber as String] as? CGWindowID,
      let b = row[kCGWindowBounds as String] as? [String: Any],
      let rect = CGRect(dictionaryRepresentation: b as CFDictionary), rect.width >= 380,
      rect.height >= 260
    {
      return AppWindow(id: wid, frame: rect)
    }
  }
  return nil
}
func clickLine(_ line: DraftLine, window: AppWindow, target: NSRunningApplication) throws {
  guard let active = activeWindow(target), active.id == window.id, active.frame == window.frame
  else {
    throw InputError("Hedef pencere değişti.")
  }
  let r = window.frame
  let point = CGPoint(x: r.minX + r.width * line.box.midX, y: r.minY + r.height * line.box.midY)
  var hit: AXUIElement?
  var pid: pid_t = 0
  guard
    AXUIElementCopyElementAtPosition(
      AXUIElementCreateSystemWide(), Float(point.x), Float(point.y), &hit) == .success,
    let hit, AXUIElementGetPid(hit, &pid) == .success, pid == target.processIdentifier
  else {
    throw InputError("Hedefin üzerinde başka bir pencere var.")
  }
  for type: CGEventType in [.leftMouseDown, .leftMouseUp] {
    CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left)?
      .post(tap: .cghidEventTap)
  }
  Thread.sleep(forTimeInterval: 0.06)
}
func teamsVisualDraft(_ who: String, text: String, submit: Bool, target: NSRunningApplication)
  throws -> String
{
  guard !who.isEmpty, who.count <= 90, !text.isEmpty, text.count <= 2000,
    !(who + text).contains(where: { $0.isNewline || $0 == "\t" }),
    var window = activeWindow(target)
  else { throw InputError("Teams penceresini ve komutu doğrulayamadım.") }
  let name = normalized(who)
  func findPicker(_ w: AppWindow) -> (DraftLine, Bool)? {
    let lines = readLines(w.id).filter { $0.box.midY < 0.5 }
    let existing = lines.filter { ["kime: " + name, "to: " + name].contains($0.text) }
    if existing.count == 1 { return (existing[0], true) }
    let empty = lines.filter { line in
      ["kime:", "to:", "enter name", "ad, sohbet", "ad, grup"].contains(where: line.text.contains)
        && ["e-posta", "name", "email", "e-mail", "etiket"].contains(where: line.text.contains)
    }
    return empty.count == 1 ? (empty[0], false) : nil
  }
  var found = findPicker(window)
  if found == nil {
    // Teams can keep the previous search in its new-chat tab. Open another
    // empty chat instead of overwriting someone else's recipient or draft.
    try key(target, 45, [.maskCommand, .maskShift])
    found = waitFor(
      2,
      {
        guard let fresh = activeWindow(target), let match = findPicker(fresh) else { return nil }
        window = fresh
        return match
      })
  }
  guard let (picker, alreadyEntered) = found else {
    throw InputError(
      "Teams’te boş alıcı alanı bulunamadı. İş e-postasını söyle.", code: "recipient")
  }
  if !alreadyEntered {
    try clickLine(picker, window: window, target: target)
    for c in who { try key(target, 0, text: String(c)) }
  }
  let queryVisible = waitFor(
    1.2,
    { () -> Bool? in
      let row = readLines(window.id).filter {
        abs($0.box.midY - picker.box.midY) * window.frame.height < 22
      }
      return row.contains(where: { $0.text.contains(name) }) ? true : nil
    })
  guard queryVisible != nil else {
    throw InputError(
      "Teams alıcı alanında aranan isim doğrulanamadı. İş e-postasını söyle.", code: "recipient")
  }
  func matched(_ lines: [DraftLine]) -> [DraftLine] {
    lines.filter { l in
      l.text == name && l.box.midY > picker.box.maxY + 0.006
        && l.box.midY < min(0.85, picker.box.maxY + 0.58) && l.box.minX >= picker.box.minX - 0.025
    }
  }
  // Wait for directory suggestions. Require the same single row in two captures.
  var previous: DraftLine?
  var choice: DraftLine?
  let end = Date().addingTimeInterval(3)
  repeat {
    let snapshot = readLines(window.id)
    let found = matched(snapshot)
    if found.count > 1 {
      throw InputError(
        "Aynı isimle birden fazla Teams kişisi var. Alıcının e-postasını söyle.", code: "recipient")
    }
    if let one = found.first, let old = previous, abs(one.box.midY - old.box.midY) < 0.01 {
      choice = one
      break
    }
    previous = found.first
    if snapshot.contains(where: {
      ["sonuc bulunamadi", "sonuc yok", "no results", "no matches"].contains(
        where: $0.text.contains)
    }) {
      break
    }
    Thread.sleep(forTimeInterval: 0.1)
  } while Date() < end
  guard let selected = choice else {
    throw InputError(
      "Teams aramasında alıcı doğrulanamadı. Tam adı veya iş e-postasını söyle.", code: "recipient")
  }
  try clickLine(selected, window: window, target: target)
  let placeholders = [
    "bir ileti yazin", "ileti yazin", "bir mesaj yazin", "mesaj yazin", "type a message",
    "enter a message",
  ]
  func hasRecipient(_ lines: [DraftLine]) -> Bool {
    lines.contains { l in
      let label = l.text.replacingOccurrences(
        of: #"^(kime|to)\s*:\s*"#, with: "", options: .regularExpression
      )
      .trimmingCharacters(in: CharacterSet(charactersIn: " ×✕"))
      return l.box.midY < 0.30 && l.box.minX >= picker.box.minX - 0.03 && label == name
    }
  }
  let empty: DraftLine? = waitFor(2) {
    let snapshot = readLines(window.id)
    guard hasRecipient(snapshot) else { return nil }
    let fields = snapshot.filter {
      $0.box.midY > 0.5 && $0.box.minX >= picker.box.minX - 0.04 && placeholders.contains($0.text)
    }
    return fields.count == 1 ? fields[0] : nil
  }
  guard let field = empty else {
    throw InputError("Teams’te seçilen alıcı ve boş yazı alanı birlikte doğrulanamadı.")
  }
  try clickLine(field, window: window, target: target)
  for c in text { try key(target, 0, text: String(c)) }
  let confirmed = waitFor(
    1.2,
    { () -> Bool? in
      let snapshot = readLines(window.id)
      let draft = snapshot.filter {
        abs($0.box.midY - field.box.midY) < 0.09 && $0.box.minX >= picker.box.minX - 0.04
      }.map(\.text).joined(separator: " ")
      return hasRecipient(snapshot) && draft.contains(normalized(text)) ? true : nil
    })
  guard confirmed != nil else {
    throw InputError("Teams taslağına yazma iletildi. Son metni doğrulayamadım.")
  }
  if submit {
    try key(target, 36)
    return "Teams’te doğrulanan taslağa gönderme tuşu iletildi."
  }
  return who + " için Teams taslağı yazıldı."
}

func draftSurface(_ target: NSRunningApplication) -> DraftSurface? {
  guard target.bundleIdentifier == "com.openai.codex", let window = activeWindow(target) else {
    return nil
  }
  let wid = window.id
  let rect = window.frame
  let lines = readLines(wid)
  // The access selector and the model selector share the toolbar below the editor.
  // Locate both on this frame; their position changes with the window and draft.
  let access = lines.filter { line in
    line.box.midY > 0.55
      && ["tam erisim", "full access", "default permissions", "varsayilan izin", "onay iste"]
        .contains(where: line.text.contains)
  }
  let models = lines.filter {
    $0.text.range(
      of: #"gpt\s*[-–]?\s*[0-9]|\bastra\b|\bsonnet\b|\bopus\b"#, options: .regularExpression) != nil
  }
  let pairs = access.flatMap { a in
    models.filter { $0.box.minX > a.box.maxX && abs($0.box.midY - a.box.midY) * rect.height < 11 }
      .map { (a, $0) }
  }
  let placeholders = [
    "codex ile calis", "work with codex", "ask for follow-up changes", "ask a follow-up",
    "bir takip sorusu sor", "bir takip mesaji yaz", "queue a follow-up", "takip mesaji ekle",
  ]
  let empty = lines.filter { l in
    l.box.midY > 0.50
      && placeholders.contains(where: {
        l.text.trimmingCharacters(in: .punctuationCharacters) == $0
      })
  }
  if empty.count == 1, let line = empty.first {
    let toolbar = (access + models).contains {
      let gap = ($0.box.midY - line.box.midY) * rect.height
      return gap > 10 && gap < 175
    }
    if toolbar {
      let point = CGPoint(
        x: rect.minX + line.box.midX * rect.width, y: rect.minY + line.box.midY * rect.height)
      let band = CGRect(
        x: max(0, line.box.minX - 0.025), y: max(0, line.box.minY - 0.08),
        width: min(1 - line.box.minX, 0.72), height: 0.13)
      return DraftSurface(
        window: wid, frame: rect, point: point, inputBand: band, lines: lines, emptyInput: true)
    }
  }
  guard pairs.count == 1, let (a, m) = pairs.first else { return nil }
  let x = min(a.box.midX + 0.01, m.box.minX - 0.02)
  let y = a.box.midY - max(40, a.box.height * rect.height * 3.2) / rect.height
  let band = CGRect(
    x: max(0, a.box.minX - 0.035), y: max(0, y - 0.12),
    width: min(0.96, m.box.maxX + 0.1) - max(0, a.box.minX - 0.035),
    height: a.box.minY - max(0, y - 0.12))
  return DraftSurface(
    window: wid, frame: rect,
    point: CGPoint(x: rect.minX + x * rect.width, y: rect.minY + y * rect.height), inputBand: band,
    lines: lines, emptyInput: false)
}
func pasteCodexDraft(
  _ text: String, surface: DraftSurface, app: AXUIElement, target: NSRunningApplication
) throws {
  guard target.isActive, !text.isEmpty, text.count <= 2000,
    !text.contains(where: { $0.isNewline || $0 == "\t" })
  else { throw InputError("Codex taslağına yazılamadı.") }
  let point = surface.point
  var hit: AXUIElement?
  var pid: pid_t = 0
  guard
    AXUIElementCopyElementAtPosition(
      AXUIElementCreateSystemWide(), Float(point.x), Float(point.y), &hit) == .success,
    let hit, AXUIElementGetPid(hit, &pid) == .success, pid == target.processIdentifier
  else { throw InputError("Yazı alanının üzerinde başka pencere var.") }
  if surface.emptyInput {
    // Only the center of the recognized empty-editor placeholder qualifies.
    for type: CGEventType in [.leftMouseDown, .leftMouseUp] {
      CGEvent(
        mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left)?
        .post(tap: .cghidEventTap)
    }
    Thread.sleep(forTimeInterval: 0.06)
    for c in text { try key(target, 0, text: String(c)) }
    try verifyDraft(text, surface: surface)
    return
  }
  let board = NSPasteboard.general
  let saved = (board.pasteboardItems ?? []).map { item -> NSPasteboardItem in
    let copy = NSPasteboardItem()
    for type in item.types {
      if let data = item.data(forType: type) { copy.setData(data, forType: type) }
    }
    return copy
  }
  board.clearContents()
  guard board.setString(text, forType: .string) else {
    throw InputError("Taslak panoya alınamadı.")
  }
  let count = board.changeCount
  defer {
    if board.changeCount == count {
      board.clearContents()
      if !saved.isEmpty { board.writeObjects(saved) }
    }
  }
  // A secondary click can open a menu but cannot activate the Send button.
  for type: CGEventType in [.rightMouseDown, .rightMouseUp] {
    CGEvent(
      mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .right)?
      .post(tap: .cghidEventTap)
  }
  var menuOpen = true
  defer { if menuOpen && target.isActive { try? key(target, 53) } }
  let paste: AXUIElement? = waitFor(0.9) {
    let menuRoot = element(app, "AXFocusedUIElement") ?? app
    for root in [menuRoot, app] {
      let menus = nodes(root) { _, r in r == "AXMenu" }
      for menu in menus {
        // Exclude the menu bar's Edit/Paste command: only the editor's popup qualifies.
        if let parent = element(menu, "AXParent"),
          ["AXMenuBarItem", "AXMenuBar"].contains(str(parent, "AXRole"))
        {
          continue
        }
        guard let items = attribute(menu, "AXChildren") as? [AXUIElement] else { continue }
        let names = items.map { normalized(str($0, "AXTitle")) }
        guard names.contains("cut") || names.contains("kes") else { continue }
        if let idx = names.firstIndex(where: { ["paste", "yapistir"].contains($0) }),
          (attribute(items[idx], "AXEnabled") as? Bool) == true
        {
          return items[idx]
        }
      }
    }
    return nil
  }
  guard let paste, target.isActive, board.changeCount == count,
    AXUIElementPerformAction(paste, "AXPress" as CFString) == .success
  else {
    throw InputError("Codex’in yazı alanındaki Yapıştır seçeneği doğrulanamadı.")
  }
  menuOpen = false
  try verifyDraft(text, surface: surface)
}
func verifyDraft(_ text: String, surface: DraftSurface) throws {
  let needle = normalized(text)
  func hits(_ lines: [DraftLine]) -> Int {
    let content = lines.filter {
      surface.inputBand.contains(CGPoint(x: $0.box.midX, y: $0.box.midY))
    }
    .sorted { $0.box.midY < $1.box.midY }.map(\.text).joined(separator: " ")
    return content.components(separatedBy: needle).count - 1
  }
  let before = hits(surface.lines)
  guard waitFor(1.4, { hits(readLines(surface.window)) > before ? true : nil }) != nil else {
    throw InputError("Yapıştırma iletildi. Taslağın metnini ekrandan doğrulayamadım.")
  }
}

func draftDigest(_ text: String, _ wid: CGWindowID) -> String {
  SHA256.hash(data: Data((String(wid) + "/" + normalized(text)).utf8)).map {
    String(format: "%02x", $0)
  }.joined()
}
func sendCodexDraft(_ receipt: String, _ target: NSRunningApplication) throws {
  guard let surface = draftSurface(target), !surface.emptyInput else {
    throw InputError("Codex taslağı ekranda doğrulanamadı.")
  }
  let matches = surface.lines.filter { l in
    surface.inputBand.contains(CGPoint(x: l.box.midX, y: l.box.midY))
      && draftDigest(l.text, surface.window) == receipt
  }
  guard matches.count == 1, let line = matches.first else {
    throw InputError("Son doğrulanan taslak değişti veya görüntüden okunamadı.")
  }
  let point = CGPoint(
    x: surface.frame.minX + line.box.midX * surface.frame.width,
    y: surface.frame.minY + line.box.midY * surface.frame.height)
  var hit: AXUIElement?
  var pid: pid_t = 0
  guard target.isActive,
    AXUIElementCopyElementAtPosition(
      AXUIElementCreateSystemWide(), Float(point.x), Float(point.y), &hit) == .success,
    let hit, AXUIElementGetPid(hit, &pid) == .success, pid == target.processIdentifier
  else { throw InputError("Codex taslağı önde değil.") }
  for type: CGEventType in [.leftMouseDown, .leftMouseUp] {
    CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left)?
      .post(tap: .cghidEventTap)
  }
  Thread.sleep(forTimeInterval: 0.06)
  try key(target, 36)
}
func switchSpace(_ q: [String: String]) throws -> [String: Any] {
  guard CGPreflightPostEventAccess(), let raw = UInt16(q["key"] ?? ""), raw < 128,
    let rawFlags = UInt64(q["flags"] ?? "")
  else { throw InputError("Masaüstü kısayolu iletilemedi.") }
  final class Change { var seen = false }
  // A short-lived LaunchAgent helper can miss NSWorkspace's first notification.
  // On-screen window IDs change across Spaces, even for two windows of one app.
  let regularPids = Set(
    workspace.runningApplications.filter { $0.activationPolicy == .regular }.map(
      \.processIdentifier))
  func visibleWindows() -> Set<CGWindowID> {
    let rows =
      CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
      as? [[String: Any]] ?? []
    return Set(
      rows.compactMap { r -> CGWindowID? in
        guard let pid = r[kCGWindowOwnerPID as String] as? Int32, regularPids.contains(pid),
          r[kCGWindowLayer as String] as? Int == 0,
          let b = r[kCGWindowBounds as String] as? [String: Any],
          let frame = CGRect(dictionaryRepresentation: b as CFDictionary),
          frame.width >= 200, frame.height >= 120,
          frame.intersects(CGDisplayBounds(CGMainDisplayID()))
        else { return nil }
        return r[kCGWindowNumber as String] as? CGWindowID
      })
  }
  let before = visibleWindows()
  let change = Change()
  let center = workspace.notificationCenter
  let observer = center.addObserver(
    forName: NSWorkspace.activeSpaceDidChangeNotification, object: nil, queue: .main
  ) { _ in change.seen = true }
  defer { center.removeObserver(observer) }
  let source = CGEventSource(stateID: .hidSystemState)
  let modifiers: [(CGEventFlags, CGKeyCode)] = [
    (.maskShift, 56), (.maskControl, 59), (.maskAlternate, 58), (.maskCommand, 55),
  ]
  var held: CGEventFlags = []
  func post(_ code: CGKeyCode, _ down: Bool, _ flags: CGEventFlags) {
    let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down)
    event?.flags = flags
    event?.post(tap: .cghidEventTap)
  }
  let flags = CGEventFlags(rawValue: rawFlags)
  for (mask, code) in modifiers where flags.contains(mask) {
    held.insert(mask)
    post(code, true, held)
  }
  var keyFlags = flags
  if [123, 124, 125, 126].contains(raw) {
    keyFlags.formUnion([.maskNumericPad, .maskSecondaryFn])
  }
  post(raw, true, keyFlags)
  Thread.sleep(forTimeInterval: 0.035)
  post(raw, false, keyFlags)
  for (mask, code) in modifiers.reversed() where held.contains(mask) {
    held.remove(mask)
    post(code, false, held)
  }
  let changed =
    waitFor(
      1.7,
      { () -> Bool? in
        if change.seen { return true }
        let after = visibleWindows()
        let left = !before.subtracting(after).isEmpty
        let joined = !after.subtracting(before).isEmpty
        return (left && joined) || (before.isEmpty && joined) || (after.isEmpty && left)
          ? true : nil
      }) != nil
  return ["changed": changed]
}

func execute(_ q: [String: String]) throws -> [String: Any] {
  if q["op"] == "space" { return try switchSpace(q) }
  let running = workspace.runningApplications.filter {
    $0.activationPolicy == .regular && !$0.isTerminated
  }
  let front = workspace.frontmostApplication?.bundleIdentifier ?? ""
  if q["op"] == "apps" {
    return [
      "apps": running.compactMap { a -> [String: String]? in
        guard let id = a.bundleIdentifier, let name = a.localizedName else { return nil }
        return ["id": id, "name": name]
      }, "front": front,
    ]
  }
  if q["op"] == "readiness" {
    var result: [String: Any] = ["accessibility": AXIsProcessTrusted(), "front": front]
    if AXIsProcessTrusted(), let target = workspace.frontmostApplication {
      let app = AXUIElementCreateApplication(target.processIdentifier)
      AXUIElementSetMessagingTimeout(app, 0.25)
      AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
      if let w = element(app, "AXFocusedWindow") {
        result["composer"] = composer(app, window: w) != nil
        if result["composer"] as? Bool == false && front == "com.openai.codex" {
          if let surface = draftSurface(target) {
            result["codexDraftAnchor"] = surface.emptyInput ? "placeholder" : "toolbar"
          } else {
            result["codexDraftAnchor"] = false
          }
        }
      }
    }
    return result
  }
  guard ["activate", "write", "send", "window-click"].contains(q["op"] ?? "") else {
    throw InputError("Girdi işlemi tanınmadı.")
  }
  let id = q["id"].flatMap { $0.isEmpty ? nil : $0 } ?? front
  guard let target = running.first(where: { $0.bundleIdentifier == id }) else {
    throw InputError("İstenen uygulama açık değil.")
  }
  if q["op"] == "window-click" {
    guard let wid = UInt32(q["window"] ?? ""), let x = Double(q["x"] ?? ""),
      let y = Double(q["y"] ?? ""),
      (0...1).contains(x), (0...1).contains(y), target.isActive,
      let windows = CGWindowListCopyWindowInfo(.optionIncludingWindow, wid) as? [[String: Any]],
      let w = windows.first, w[kCGWindowOwnerPID as String] as? Int32 == target.processIdentifier,
      let bounds = w[kCGWindowBounds as String] as? [String: Any],
      let rect = CGRect(dictionaryRepresentation: bounds as CFDictionary)
    else { throw InputError("Cursor penceresi değişti.") }
    let point = CGPoint(x: rect.minX + x * (rect.width - 1), y: rect.minY + y * (rect.height - 1))
    var hit: AXUIElement?
    var pid: pid_t = 0
    guard
      AXUIElementCopyElementAtPosition(
        AXUIElementCreateSystemWide(), Float(point.x), Float(point.y), &hit) == .success,
      let hit, AXUIElementGetPid(hit, &pid) == .success, pid == target.processIdentifier
    else {
      throw InputError("Tıklama noktası Cursor üzerinde doğrulanamadı.")
    }
    for type: CGEventType in [.leftMouseDown, .leftMouseUp] {
      CGEvent(
        mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: .left)?
        .post(tap: .cghidEventTap)
    }
    return ["reply": "Tıklama Cursor penceresine iletildi."]
  }
  if q["field"] == "current", q["op"] == "write", q["submit"] != "yes" {
    guard target.isActive, let text = q["text"], !text.isEmpty, text.count <= 2000,
      !text.contains(where: { $0.isNewline || $0 == "\t" })
    else {
      throw InputError("Odak değişti veya metin tek satıra sığmıyor.")
    }
    guard CGPreflightPostEventAccess() else {
      throw InputError("Mac’te Erişilebilirlik izni gerekiyor.")
    }
    for c in text { try key(target, 0, text: String(c)) }
    return ["reply": "Metin öndeki uygulamaya iletildi."]
  }
  if !target.isActive {
    target.activate(options: [])
    guard waitFor(1.3, { target.isActive ? true : nil }) != nil else {
      throw InputError("Uygulama öne alınamadı.")
    }
  }
  let name = target.localizedName ?? id
  if q["op"] == "activate" { return ["reply": name + " önde."] }
  // Teams' single-recipient deep link can prepare a draft even when its WebView
  // does not expose chat controls to Accessibility. It never submits a message.
  if id == "com.microsoft.teams2", q["op"] == "write", q["submit"] != "yes",
    let mail = q["recipient"],
    mail.range(
      of: #"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"#, options: .regularExpression) != nil,
    let body = q["text"], !body.isEmpty, body.count <= 2000
  {
    var link = URLComponents()
    link.scheme = "msteams"
    link.host = "teams.microsoft.com"
    link.path = "/l/chat/0/0"
    link.queryItems = [
      URLQueryItem(name: "users", value: mail), URLQueryItem(name: "message", value: body),
    ]
    link.percentEncodedQuery = link.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
    guard let url = link.url, workspace.open(url) else {
      throw InputError("Teams taslak bağlantısını açamadım.")
    }
    return ["reply": mail + " için taslağı açma isteği Teams’e iletildi."]
  }
  guard AXIsProcessTrusted() else {
    throw InputError("Yazı alanını okumak için Erişilebilirlik izni gerekiyor.")
  }
  let app = AXUIElementCreateApplication(target.processIdentifier)
  AXUIElementSetMessagingTimeout(app, 0.4)
  AXUIElementSetAttributeValue(app, "AXManualAccessibility" as CFString, kCFBooleanTrue)
  guard var window = element(app, "AXFocusedWindow") else {
    throw InputError("Uygulamanın etkin penceresi bulunamadı.")
  }
  if let project = q["project"], !project.isEmpty,
    !normalized(str(window, "AXTitle")).contains(normalized(project))
  {
    throw InputError("Öndeki Cursor penceresi bu oturuma ait değil.")
  }
  let op = q["op"] ?? ""
  let who = q["recipient"] ?? ""
  if id == "com.microsoft.teams2" && !who.isEmpty {
    do { try teamsRecipient(who, app: app, running: target) } catch let issue as InputError
      where issue.code == "picker"
    {
      return [
        "reply": try teamsVisualDraft(
          who, text: q["text"] ?? "", submit: q["submit"] == "yes", target: target)
      ]
    }
    guard let w = element(app, "AXFocusedWindow") else {
      throw InputError("Teams sohbeti bulunamadı.")
    }
    window = w
  }
  let field: AXUIElement
  if q["field"] == "composer" || op == "send" {
    let found =
      id == "com.openai.codex"
      ? composer(app, window: window) : waitFor(1.2, { composer(app, window: window) })
    guard let found else {
      if op == "send", id == "com.openai.codex", let receipt = q["receipt"], !receipt.isEmpty {
        try sendCodexDraft(receipt, target)
        return ["reply": "Gönderme tuşu Codex’e iletildi."]
      }
      if op == "write", id == "com.openai.codex", let surface = draftSurface(target) {
        let text = q["text"] ?? ""
        if q["submit"] == "yes" && !surface.emptyInput {
          throw InputError("Önce mevcut Codex taslağını kontrol et.")
        }
        try pasteCodexDraft(text, surface: surface, app: app, target: target)
        let receipt = draftDigest(text, surface.window)
        if q["submit"] == "yes" {
          try sendCodexDraft(receipt, target)
          return ["reply": "Taslak yazıldı ve gönderme tuşu iletildi."]
        }
        return ["reply": "Codex taslağına yazıldı.", "receipt": receipt]
      }
      throw InputError("Sohbetin yazı kutusunu ayırt edemedim. Kutuyu seçip “buraya … yaz” de.")
    }
    field = found
  } else {
    guard let f = element(app, "AXFocusedUIElement"), editable(f) else {
      throw InputError("Önce düzenlenebilir metin alanını seç.")
    }
    field = f
  }
  if q["submit"] == "yes", op == "write",
    !str(field, "AXValue").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  {
    throw InputError("Sohbet kutusunda zaten bir taslak var. Önce mevcut metni kontrol et.")
  }
  if op != "send" { try insert(q["text"] ?? "", into: field, app: app, running: target) }
  if op == "send" || q["submit"] == "yes" {
    try focus(app, field)
    guard isComposer(field),
      !str(field, "AXValue").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      focused(app, field)
    else { throw InputError("Gönderilecek taslak doğrulanamadı.") }
    try key(target, 36)
    return ["reply": "Gönderme tuşu iletildi."]
  }
  return ["reply": who.isEmpty ? "\(name) alanına yazıldı." : "\(who) için Teams taslağı yazıldı."]
}
do {
  let request = try JSONDecoder().decode(
    [String: String].self, from: FileHandle.standardInput.readDataToEndOfFile())
  let started = Date()
  let result: [String: Any]
  do { result = try execute(request) } catch {
    let issue = error as? InputError
    result = [
      "error": issue?.message ?? "Mac işlemi tamamlayamadı.", "code": issue?.code ?? "input",
    ]
  }
  // Keep only the latest result for diagnosing a reported action, without the dictated text.
  if ["write", "send"].contains(request["op"] ?? "") {
    let root = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
      .deletingLastPathComponent().deletingLastPathComponent()
    let status: [String: Any] = [
      "at": started.timeIntervalSince1970, "op": request["op"] ?? "",
      "app": request["id"] ?? "", "ok": result["error"] == nil,
      "error": result["error"] ?? "", "duration": Date().timeIntervalSince(started),
    ]
    if let bytes = try? JSONSerialization.data(withJSONObject: status) {
      try? bytes.write(
        to: root.appendingPathComponent("data/voice-input-status.json"), options: .atomic)
    }
  }
  FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: result))
} catch {
  FileHandle.standardOutput.write(Data(#"{"error":"Girdi isteği okunamadı."}"#.utf8))
}
