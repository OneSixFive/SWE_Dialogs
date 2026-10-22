import SwiftUI
import UIKit

// Visual language: one handmade 1980s Swedish learning device. Each screen
// is the faceplate of one module: graphite painted metal with a smoked
// walnut key ledge, near-black insets, bone and graphite keys, and a single muted rust
// accent used sparingly. Reference mockups live in docs/design/ (06-07).
// Learning text (tutor, learner, dialogue, quiz sentences) always sits on a
// plain paper surface; metal, wood and keycaps are only for the chrome.

enum Retro {
    static let faceplate = Color(red: 0.24, green: 0.235, blue: 0.22)
    static let inset = Color(red: 0.075, green: 0.07, blue: 0.065)

    static let walnutDeep = Color(red: 0.13, green: 0.075, blue: 0.045)
    static let walnut = Color(red: 0.24, green: 0.14, blue: 0.08)
    static let walnutLight = Color(red: 0.36, green: 0.23, blue: 0.13)

    static let brass = Color(red: 0.64, green: 0.53, blue: 0.34)
    static let brassDark = Color(red: 0.40, green: 0.32, blue: 0.19)

    /// The one accent: current lesson, play, active tab, talk.
    static let accent = Color(red: 0.55, green: 0.22, blue: 0.15)
    static let ochre = Color(red: 0.62, green: 0.50, blue: 0.29)
    static let olive = Color(red: 0.29, green: 0.30, blue: 0.21)
    static let bone = Color(red: 0.77, green: 0.73, blue: 0.64)
    static let graphiteKey = Color(red: 0.29, green: 0.285, blue: 0.27)

    static let paper = Color(red: 0.92, green: 0.89, blue: 0.82)
    static let paperShade = Color(red: 0.82, green: 0.78, blue: 0.69)
    static let ink = Color(red: 0.17, green: 0.14, blue: 0.12)
    static let inkSoft = Color(red: 0.17, green: 0.14, blue: 0.12).opacity(0.55)
    static let inkAccent = Color(red: 0.62, green: 0.23, blue: 0.13)
    static let pencilRed = Color(red: 0.72, green: 0.17, blue: 0.13)

    static let crt = Color(red: 0.06, green: 0.05, blue: 0.04)
    static let amber = Color(red: 1.0, green: 0.68, blue: 0.26)

    /// Silkscreen print on the faceplate and on dark keys.
    static let labelOnDark = Color(red: 0.80, green: 0.77, blue: 0.71)
    static let labelOnDarkSoft = Color(red: 0.80, green: 0.77, blue: 0.71).opacity(0.55)

    static let uiInk = UIColor(red: 0.17, green: 0.14, blue: 0.12, alpha: 1)
    static let uiInkAccent = UIColor(red: 0.62, green: 0.23, blue: 0.13, alpha: 1)
    static let uiPencilRed = UIColor(red: 0.72, green: 0.17, blue: 0.13, alpha: 1)
}

/// Font tokens. Placeholders until the licensed Swedish families are chosen
/// (Tratex/Bosis for labels, Berling Nova for reading text). Labels are a
/// typewriter face, like silkscreen print on studio equipment.
enum RetroFont {
    static func label(_ size: CGFloat = 13, weight: UIFont.Weight = .bold) -> Font {
        Font(labelUIFont(size, weight: weight))
    }

    static func labelUIFont(_ size: CGFloat, weight: UIFont.Weight = .bold) -> UIFont {
        let name = weight >= .bold ? "AmericanTypewriter-Semibold" : "AmericanTypewriter"
        return UIFont(name: name, size: size) ?? .systemFont(ofSize: size, weight: weight)
    }

    static func wordmark(_ size: CGFloat) -> Font {
        Font(UIFont(name: "AmericanTypewriter-Semibold", size: size) ?? .systemFont(ofSize: size, weight: .semibold))
    }

    /// Reading text for tutor/learner/dialogue. Scales with Dynamic Type.
    static func readingUIFont(_ style: UIFont.TextStyle = .body, weight: UIFont.Weight = .regular) -> UIFont {
        let base = UIFont.preferredFont(forTextStyle: style)
        let font = UIFont.monospacedSystemFont(ofSize: base.pointSize - 1, weight: weight)
        return UIFontMetrics(forTextStyle: style).scaledFont(for: font)
    }

    static func reading(_ style: UIFont.TextStyle = .body, weight: UIFont.Weight = .regular) -> Font {
        Font(readingUIFont(style, weight: weight))
    }

    static func digits(_ size: CGFloat) -> Font {
        .system(size: size, weight: .semibold, design: .monospaced)
    }
}

// MARK: - Surfaces

/// Smoked walnut from the `WoodWalnut` texture (a seamless tile), for the
/// key ledge. `shade` darkens it further.
struct WoodBackground: View {
    var shade: Double = 0

    var body: some View {
        Image("WoodWalnut")
            .resizable(resizingMode: .tile)
            .saturation(0.8)
            .overlay(Color.black.opacity(0.3 + shade))
            .accessibilityHidden(true)
    }
}

/// Graphite painted-metal faceplate from the `Faceplate` texture (a seamless
/// tile), lit softly from the top left.
struct FaceplateBackground: View {
    var body: some View {
        Image("Faceplate")
            .resizable(resizingMode: .tile)
            .overlay(
                RadialGradient(
                    colors: [Color.white.opacity(0.05), Color.clear, Color.black.opacity(0.3)],
                    center: .topLeading,
                    startRadius: 40,
                    endRadius: 900
                )
            )
            .accessibilityHidden(true)
    }
}

extension View {
    /// Grouped controls sit in the same near-black inset as the cassette deck.
    func retroPanel(cornerRadius: CGFloat = 12, padding: CGFloat = 10) -> some View {
        modifier(RetroRecess(cornerRadius: cornerRadius, padding: padding))
    }

    /// Full-screen graphite faceplate behind a screen.
    func retroScreenBackground() -> some View {
        background(FaceplateBackground().ignoresSafeArea())
    }
}

/// Near-black inset cut into the faceplate, with steel screws in the corners.
/// Holds the cassette deck.
struct RetroRecess: ViewModifier {
    var cornerRadius: CGFloat = 14
    var padding: CGFloat = 14

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        content
            .padding(padding)
            .background(
                shape.fill(
                    Retro.inset
                        .shadow(.inner(color: .black.opacity(0.9), radius: 7, y: 4))
                )
            )
            .overlay {
                // Screws only where the margin leaves room for them.
                if padding >= 10 {
                    let corners: [Alignment] = [.topLeading, .topTrailing, .bottomLeading, .bottomTrailing]
                    ForEach(corners.indices, id: \.self) { index in
                        SteelScrew()
                            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: corners[index])
                            .padding(5)
                    }
                }
            }
            .overlay(shape.stroke(Color.black.opacity(0.7), lineWidth: 1))
            // Lower lip of the cut catching the light.
            .background(shape.stroke(Color.white.opacity(0.10), lineWidth: 1).offset(y: 1))
    }
}

struct SteelScrew: View {
    var body: some View {
        Circle()
            .fill(RadialGradient(colors: [Color(white: 0.55), Color(white: 0.22)], center: .topLeading, startRadius: 0, endRadius: 6))
            .frame(width: 6, height: 6)
            .overlay(Rectangle().fill(Color.black.opacity(0.6)).frame(width: 4.5, height: 1).rotationEffect(.degrees(-30)))
    }
}

extension View {
    func retroRecess(cornerRadius: CGFloat = 14, padding: CGFloat = 14) -> some View {
        modifier(RetroRecess(cornerRadius: cornerRadius, padding: padding))
    }
}

/// Plain paper for learning text: no frames or ornaments.
struct PaperSheet<Content: View>: View {
    /// The sheet grows to at least this height, text staying at the top.
    var minHeight: CGFloat = 0
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(.horizontal, 18)
            .padding(.vertical, 18)
            .frame(maxWidth: .infinity, minHeight: minHeight, alignment: .topLeading)
            .background(Retro.paper)
            .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
            .shadow(color: .black.opacity(0.4), radius: 5, x: 1, y: 3)
    }
}

/// Steel roller of the printer slot the chat paper feeds out of. Laid over the
/// top of a paper scroll view, so the paper slides out from under it.
struct PaperRoller: View {
    var body: some View {
        ZStack {
            Capsule()
                .fill(
                    LinearGradient(
                        colors: [Color(white: 0.42), Color(white: 0.2), Color(white: 0.07)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .frame(height: 12)
                .padding(.horizontal, 10)
            HStack {
                rollerCap
                Spacer()
                rollerCap
            }
        }
        .frame(height: 16)
        .shadow(color: .black.opacity(0.6), radius: 3, y: 3)
        .accessibilityHidden(true)
    }

    private var rollerCap: some View {
        RoundedRectangle(cornerRadius: 3, style: .continuous)
            .fill(LinearGradient(colors: [Color(white: 0.5), Color(white: 0.15)], startPoint: .top, endPoint: .bottom))
            .frame(width: 10, height: 16)
            .overlay(RoundedRectangle(cornerRadius: 3, style: .continuous).stroke(Color.black.opacity(0.6), lineWidth: 1))
    }
}

extension View {
    /// Printer roller over the top edge of a paper chat.
    func paperRoller() -> some View {
        overlay(alignment: .top) {
            PaperRoller()
                .padding(.horizontal, 8)
                .offset(y: -6)
                .allowsHitTesting(false)
        }
    }
}

/// Small caption above a speaker's lines on paper ("LÄRAREN", "DU", "ANNA").
struct PaperCaption: View {
    let text: String
    var color: Color = Retro.inkSoft

    var body: some View {
        Text(text.uppercased())
            .font(RetroFont.label(10))
            .tracking(1.2)
            .foregroundStyle(color)
    }
}

/// Engraved label on the `BrassPlate` artwork. The plate is scaled as a
/// whole to the label height so the screw ends keep their shape.
struct BrassPlateLabel: View {
    let text: String
    var size: CGFloat = 15
    var height: CGFloat = 38

    private static let artworkHeight: CGFloat = 48

    var body: some View {
        Text(text)
            .font(RetroFont.label(size))
            .tracking(size > 12 ? 2 : 1.2)
            .foregroundStyle(Retro.walnutDeep.opacity(0.85))
            .shadow(color: .white.opacity(0.35), radius: 0, y: 1)
            .padding(.horizontal, height * 0.85)
            .frame(height: height)
            .background {
                GeometryReader { proxy in
                    let scale = proxy.size.height / Self.artworkHeight
                    Image("BrassPlate")
                        .resizable(capInsets: EdgeInsets(top: 0, leading: 24, bottom: 0, trailing: 24), resizingMode: .stretch)
                        .frame(width: proxy.size.width / scale, height: Self.artworkHeight)
                        .scaleEffect(scale, anchor: .topLeading)
                }
            }
            .shadow(color: .black.opacity(0.5), radius: 3, x: 1, y: 2)
    }
}

/// Brass screw head for panel corners.
struct BrassScrew: View {
    var body: some View {
        Circle()
            .fill(RadialGradient(colors: [Retro.brass, Retro.brassDark], center: .topLeading, startRadius: 0, endRadius: 6))
            .frame(width: 7, height: 7)
            .overlay(Rectangle().fill(Retro.walnutDeep.opacity(0.6)).frame(width: 5, height: 1).rotationEffect(.degrees(35)))
    }
}

// MARK: - Keys

enum RetroKeyTint {
    /// Rust: the one thing to press (current lesson, play, active tab).
    case accent
    case olive
    case bone
    case graphite
    case dark

    var face: Color {
        switch self {
        case .accent: return Retro.accent
        case .olive: return Retro.olive
        case .bone: return Retro.bone
        case .graphite: return Retro.graphiteKey
        case .dark: return Color(white: 0.13)
        }
    }

    var label: Color {
        switch self {
        case .bone: return Retro.ink
        case .accent: return Retro.paper
        case .olive, .graphite, .dark: return Retro.labelOnDark
        }
    }
}

/// Chunky calculator-style keycap. Pressed keys sink by their edge height.
struct RetroKeyStyle: ButtonStyle {
    var tint: RetroKeyTint = .bone
    var isLatched = false
    var cornerRadius: CGFloat = 10
    var edge: CGFloat = 4

    func makeBody(configuration: Configuration) -> some View {
        RetroKeyBody(
            tint: tint,
            isDown: configuration.isPressed || isLatched,
            cornerRadius: cornerRadius,
            edge: edge,
            label: configuration.label
        )
    }
}

private struct RetroKeyBody<Label: View>: View {
    let tint: RetroKeyTint
    let isDown: Bool
    let cornerRadius: CGFloat
    let edge: CGFloat
    let label: Label

    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        let sink = isDown ? edge - 1 : 0
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
        label
            .foregroundStyle(tint.label)
            .shadow(color: .black.opacity(tint == .bone ? 0 : 0.3), radius: 0, y: 1)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(
                // Matte cap: bevel light on the top-left rim, dish shadow on
                // the bottom-right, faint sheen falling across the face.
                shape
                    .fill(
                        tint.face
                            .shadow(.inner(color: .white.opacity(0.38), radius: 1.2, x: 1, y: 1.5))
                            .shadow(.inner(color: .black.opacity(0.28), radius: 4, x: -1.5, y: -2.5))
                    )
                    .overlay(
                        shape.fill(
                            LinearGradient(
                                colors: [.white.opacity(0.12), .clear, .black.opacity(0.06)],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                    )
            )
            .offset(y: sink)
            .background(
                // Side wall, darker toward the base.
                shape
                    .fill(
                        LinearGradient(
                            colors: [tint.face.mix(with: .black, by: 0.38), tint.face.mix(with: .black, by: 0.6)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .offset(y: edge)
            )
            .padding(.bottom, edge)
            .background(
                // Gap between the key and the panel it is set into.
                shape
                    .stroke(Color.black.opacity(0.55), lineWidth: 1.5)
                    .padding(.bottom, -0.5)
            )
            .shadow(color: .black.opacity(isDown ? 0.25 : 0.5), radius: isDown ? 1 : 4, x: isDown ? 0 : 1, y: isDown ? 1 : 4)
            .opacity(isEnabled ? 1 : 0.5)
            .saturation(isEnabled ? 1 : 0.5)
            .contentShape(Rectangle())
            // A mechanical key moves as one piece and snaps: no eased press
            // or release, so the cap and its printed glyph never drift apart.
            .transaction { $0.animation = nil }
    }
}

/// Keycap with an icon and/or an uppercase printed label.
struct RetroKeyLabel: View {
    var title: String?
    var systemImage: String?
    var subtitle: String?
    var titleSize: CGFloat = 13
    var imageSize: CGFloat?

    var body: some View {
        VStack(spacing: 3) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.system(size: imageSize ?? (title == nil ? 19 : 20), weight: .semibold))
            }
            if let title {
                Text(title.uppercased())
                    .font(RetroFont.label(titleSize))
                    .tracking(0.8)
                    .lineLimit(1)
                    .minimumScaleFactor(0.7)
            }
            if let subtitle {
                Text(subtitle.uppercased())
                    .font(RetroFont.label(8, weight: .medium))
                    .tracking(0.6)
                    .opacity(0.75)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.horizontal, 6)
    }
}

// MARK: - Readouts

/// Amber CRT/VFD readout.
struct AmberReadout: View {
    let text: String
    var size: CGFloat = 15

    var body: some View {
        Text(text)
            .font(RetroFont.digits(size))
            .foregroundStyle(Retro.amber)
            .shadow(color: Retro.amber.opacity(0.7), radius: 4)
            .lineLimit(1)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(
                RoundedRectangle(cornerRadius: 5, style: .continuous)
                    .fill(Retro.crt)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 5, style: .continuous)
                    .strokeBorder(Retro.brassDark, lineWidth: 1.5)
            )
    }
}

/// Digit windows behind smoked glass, e.g. the day number or quiz progress.
/// Highlighted digits glow amber; the rest stay dim. An optional `prefix`
/// ("DAG") is silkscreened on the panel beside the window.
struct CounterWheels: View {
    let digits: [String]
    var highlighted: Set<Int>?
    var size: CGFloat = 26
    var prefix: String?

    var body: some View {
        HStack(spacing: 8) {
            if let prefix {
                Text(prefix)
                    .font(RetroFont.label(size * 0.5))
                    .tracking(1)
                    .foregroundStyle(Retro.labelOnDarkSoft)
            }
            HStack(spacing: 2) {
                ForEach(Array(digits.enumerated()), id: \.offset) { index, digit in
                    let isLit = highlighted?.contains(index) ?? true
                    Text(digit)
                        .font(RetroFont.digits(size * 0.74))
                        .foregroundStyle(isLit ? Retro.amber : Retro.labelOnDark.opacity(0.22))
                        .shadow(color: isLit ? Retro.amber.opacity(0.6) : .clear, radius: 3)
                        .frame(width: size, height: size * 1.3)
                        .background(
                            LinearGradient(colors: [Color(white: 0.02), Color(white: 0.09), Color(white: 0.02)], startPoint: .top, endPoint: .bottom)
                        )
                        .clipShape(RoundedRectangle(cornerRadius: 2, style: .continuous))
                }
            }
            .padding(3)
            .background(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(Color.black.shadow(.inner(color: .black, radius: 2, y: 1)))
            )
            .overlay(RoundedRectangle(cornerRadius: 4, style: .continuous).stroke(Color.white.opacity(0.1), lineWidth: 1))
        }
    }
}

// MARK: - Tab bar

enum RetroTab: Hashable {
    case lessons
    case words
    case more

    var title: String {
        switch self {
        case .lessons: return "Lektioner"
        case .words: return "Ord"
        case .more: return "Mer"
        }
    }
}

private struct RetroTabSelectionKey: EnvironmentKey {
    static let defaultValue: Binding<RetroTab>? = nil
}

extension EnvironmentValues {
    var retroTabSelection: Binding<RetroTab>? {
        get { self[RetroTabSelectionKey.self] }
        set { self[RetroTabSelectionKey.self] = newValue }
    }
}

/// Physical push-key tab bar. Root screens attach it with `retroTabBar()` so
/// pushed screens do not show it.
struct RetroTabBar: View {
    @Binding var selection: RetroTab

    var body: some View {
        HStack(spacing: 10) {
            ForEach([RetroTab.lessons, .words, .more], id: \.self) { tab in
                Button {
                    selection = tab
                } label: {
                    RetroKeyLabel(title: tab.title, titleSize: 13)
                }
                .buttonStyle(RetroKeyStyle(tint: selection == tab ? .accent : .graphite, isLatched: selection == tab, cornerRadius: 6))
                .frame(height: 46)
                .accessibilityAddTraits(selection == tab ? .isSelected : [])
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 12)
        .padding(.bottom, 2)
    }
}

private struct RetroTabBarModifier: ViewModifier {
    @Environment(\.retroTabSelection) private var selection

    func body(content: Content) -> some View {
        content
            .toolbar(.hidden, for: .tabBar)
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if let selection {
                    RetroTabBar(selection: selection)
                        .retroBottomBacking()
                }
            }
    }
}

extension View {
    func retroTabBar() -> some View {
        modifier(RetroTabBarModifier())
    }

    /// Walnut key ledge behind bottom bars, with a lit top edge, so scrolled
    /// content never shows below it.
    func retroBottomBacking() -> some View {
        background(
            WoodBackground(shade: 0.15)
                .overlay(alignment: .top) {
                    VStack(spacing: 0) {
                        Rectangle().fill(Color.black.opacity(0.6)).frame(height: 1)
                        Rectangle().fill(Color.white.opacity(0.10)).frame(height: 1)
                    }
                }
                .shadow(color: .black.opacity(0.45), radius: 6, y: -2)
                .ignoresSafeArea(edges: .bottom)
        )
    }
}

// MARK: - Wordmark

struct SvenskaWordmark: View {
    var size: CGFloat = 30

    var body: some View {
        Text("Svenska")
            .font(RetroFont.wordmark(size))
            .foregroundStyle(Retro.labelOnDark)
            .shadow(color: .black.opacity(0.5), radius: 0, x: 0, y: 1)
    }
}

// MARK: - Pushed-screen header

/// Back key plus a printed title strip for pushed screens.
struct RetroScreenHeader: View {
    let title: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        HStack(spacing: 12) {
            Button {
                dismiss()
            } label: {
                RetroKeyLabel(systemImage: "arrow.left")
            }
            .buttonStyle(RetroKeyStyle(tint: .bone))
            .frame(width: 56, height: 50)
            .accessibilityLabel("Tillbaka")

            Text(title.uppercased())
                .font(RetroFont.label(15))
                .tracking(1.2)
                .foregroundStyle(Retro.labelOnDark)
                .lineLimit(1)
                .minimumScaleFactor(0.7)

            Spacer()
        }
    }
}
