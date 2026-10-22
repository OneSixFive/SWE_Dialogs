import SwiftUI
import UIKit

// Visual language: 1980s Swedish office electronics in a walnut/mustard/
// burnt-orange/olive palette. Reference mockups live in docs/design/.
// Learning text (tutor, learner, dialogue, quiz sentences) always sits on a
// plain paper surface; wood, brass and keycaps are only for the chrome.

enum Retro {
    static let walnutDeep = Color(red: 0.16, green: 0.09, blue: 0.05)
    static let walnut = Color(red: 0.27, green: 0.16, blue: 0.09)
    static let walnutLight = Color(red: 0.40, green: 0.25, blue: 0.14)
    static let groove = Color(red: 0.10, green: 0.06, blue: 0.03)

    static let brass = Color(red: 0.76, green: 0.62, blue: 0.36)
    static let brassDark = Color(red: 0.50, green: 0.38, blue: 0.19)

    static let mustard = Color(red: 0.85, green: 0.64, blue: 0.17)
    static let orange = Color(red: 0.80, green: 0.34, blue: 0.13)
    static let olive = Color(red: 0.42, green: 0.48, blue: 0.23)
    static let beige = Color(red: 0.86, green: 0.79, blue: 0.63)

    static let paper = Color(red: 0.95, green: 0.91, blue: 0.81)
    static let paperShade = Color(red: 0.86, green: 0.80, blue: 0.67)
    static let ink = Color(red: 0.18, green: 0.13, blue: 0.10)
    static let inkSoft = Color(red: 0.18, green: 0.13, blue: 0.10).opacity(0.55)
    static let inkOrange = Color(red: 0.70, green: 0.27, blue: 0.09)
    static let pencilRed = Color(red: 0.78, green: 0.16, blue: 0.12)

    static let crt = Color(red: 0.09, green: 0.06, blue: 0.03)
    static let amber = Color(red: 1.0, green: 0.71, blue: 0.28)

    static let labelOnDark = Color(red: 0.93, green: 0.86, blue: 0.70)
    static let labelOnDarkSoft = Color(red: 0.93, green: 0.86, blue: 0.70).opacity(0.6)

    static let uiInk = UIColor(red: 0.18, green: 0.13, blue: 0.10, alpha: 1)
    static let uiInkOrange = UIColor(red: 0.70, green: 0.27, blue: 0.09, alpha: 1)
    static let uiPencilRed = UIColor(red: 0.78, green: 0.16, blue: 0.12, alpha: 1)
}

/// Font tokens. Placeholders until the licensed Swedish families are chosen
/// (Tratex/Bosis for labels, Berling Nova for reading text).
enum RetroFont {
    static func label(_ size: CGFloat = 13, weight: UIFont.Weight = .bold) -> Font {
        Font(labelUIFont(size, weight: weight))
    }

    static func labelUIFont(_ size: CGFloat, weight: UIFont.Weight = .bold) -> UIFont {
        let name = weight >= .bold ? "Futura-Bold" : "Futura-Medium"
        return UIFont(name: name, size: size) ?? .systemFont(ofSize: size, weight: weight)
    }

    static func wordmark(_ size: CGFloat) -> Font {
        Font(UIFont(name: "Futura-CondensedExtraBold", size: size) ?? .systemFont(ofSize: size, weight: .black))
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

/// Vertical walnut veneer drawn procedurally so it stays crisp at any size.
struct WoodBackground: View {
    var base: Color = Retro.walnut

    var body: some View {
        Canvas { context, size in
            context.fill(Path(CGRect(origin: .zero, size: size)), with: .color(base))
            var generator = SeededGenerator(seed: 7)
            let lineCount = Int(size.width / 3)
            for index in 0..<lineCount {
                let x = CGFloat(index) * 3 + CGFloat.random(in: -1...1, using: &generator)
                let amplitude = CGFloat.random(in: 0.5...4, using: &generator)
                let wavelength = CGFloat.random(in: 140...420, using: &generator)
                let phase = CGFloat.random(in: 0...(2 * .pi), using: &generator)
                var path = Path()
                path.move(to: CGPoint(x: x, y: 0))
                var y: CGFloat = 0
                while y <= size.height {
                    path.addLine(to: CGPoint(x: x + amplitude * sin(y / wavelength * 2 * .pi + phase), y: y))
                    y += 12
                }
                let isDark = Bool.random(using: &generator)
                let opacity = Double.random(in: 0.04...0.16, using: &generator)
                context.stroke(
                    path,
                    with: .color(isDark ? Color.black.opacity(opacity) : Retro.walnutLight.opacity(opacity * 1.4)),
                    lineWidth: CGFloat.random(in: 0.6...2.2, using: &generator)
                )
            }
        }
        .overlay(
            LinearGradient(
                colors: [Color.black.opacity(0.18), Color.clear, Color.black.opacity(0.22)],
                startPoint: .top,
                endPoint: .bottom
            )
        )
        .drawingGroup()
    }
}

struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64

    init(seed: UInt64) {
        state = seed &+ 0x9E37_79B9_7F4A_7C15
    }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var value = state
        value = (value ^ (value >> 30)) &* 0xBF58_476D_1CE4_E5B9
        value = (value ^ (value >> 27)) &* 0x94D0_49BB_1331_11EB
        return value ^ (value >> 31)
    }
}

/// Recessed brass-trimmed wooden panel used for grouped controls.
struct RetroPanel: ViewModifier {
    var cornerRadius: CGFloat = 12
    var padding: CGFloat = 10

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(Retro.walnutDeep)
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(
                        LinearGradient(colors: [Retro.brass, Retro.brassDark], startPoint: .top, endPoint: .bottom),
                        lineWidth: 1.5
                    )
            )
            .shadow(color: .black.opacity(0.35), radius: 3, y: 2)
    }
}

extension View {
    func retroPanel(cornerRadius: CGFloat = 12, padding: CGFloat = 10) -> some View {
        modifier(RetroPanel(cornerRadius: cornerRadius, padding: padding))
    }

    /// Full-screen walnut backdrop plus the app's dark system appearance.
    func retroScreenBackground() -> some View {
        background(WoodBackground().ignoresSafeArea())
    }
}

/// Plain paper for learning text. Decoration stays on the edges only.
struct PaperSheet<Content: View>: View {
    var showsFeedHoles = true
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(.horizontal, showsFeedHoles ? 30 : 18)
            .padding(.vertical, 18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                ZStack {
                    Retro.paper
                    if showsFeedHoles {
                        HStack {
                            FeedHoleStrip()
                            Spacer()
                            FeedHoleStrip()
                        }
                        .padding(.horizontal, 7)
                    }
                }
            )
            .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
            .shadow(color: .black.opacity(0.35), radius: 4, y: 2)
    }
}

private struct FeedHoleStrip: View {
    var body: some View {
        GeometryReader { proxy in
            let count = max(1, Int(proxy.size.height / 22))
            VStack(spacing: 0) {
                ForEach(0..<count, id: \.self) { _ in
                    Circle()
                        .fill(Retro.paperShade)
                        .frame(width: 7, height: 7)
                        .frame(maxHeight: .infinity)
                }
            }
        }
        .frame(width: 8)
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
    case orange
    case mustard
    case olive
    case beige
    case dark

    var face: Color {
        switch self {
        case .orange: return Retro.orange
        case .mustard: return Retro.mustard
        case .olive: return Retro.olive
        case .beige: return Retro.beige
        case .dark: return Retro.walnutDeep
        }
    }

    var label: Color {
        switch self {
        case .beige, .mustard: return Retro.ink
        case .orange, .olive, .dark: return Retro.paper
        }
    }
}

/// Chunky calculator-style keycap. Pressed keys sink by their edge height.
struct RetroKeyStyle: ButtonStyle {
    var tint: RetroKeyTint = .beige
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
        label
            .foregroundStyle(tint.label)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [tint.face.mix(with: .white, by: 0.14), tint.face],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                            .strokeBorder(Color.white.opacity(0.22), lineWidth: 1)
                            .blendMode(.overlay)
                    )
            )
            .offset(y: sink)
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(tint.face.mix(with: .black, by: 0.45))
                    .offset(y: edge)
            )
            .padding(.bottom, edge)
            .shadow(color: .black.opacity(isDown ? 0.2 : 0.4), radius: isDown ? 1 : 3, y: isDown ? 1 : 3)
            .opacity(isEnabled ? 1 : 0.5)
            .saturation(isEnabled ? 1 : 0.5)
            .contentShape(Rectangle())
    }
}

/// Keycap with an icon and/or an uppercase printed label.
struct RetroKeyLabel: View {
    var title: String?
    var systemImage: String?
    var subtitle: String?
    var titleSize: CGFloat = 13

    var body: some View {
        VStack(spacing: 3) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(.system(size: title == nil ? 19 : 20, weight: .semibold))
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

/// Mechanical counter windows, e.g. lesson number or quiz progress.
struct CounterWheels: View {
    let digits: [String]
    var highlighted: Set<Int> = []
    var size: CGFloat = 26

    var body: some View {
        HStack(spacing: 4) {
            ForEach(Array(digits.enumerated()), id: \.offset) { index, digit in
                Text(digit)
                    .font(RetroFont.digits(size * 0.72))
                    .foregroundStyle(highlighted.contains(index) ? Retro.paper : Retro.ink)
                    .frame(width: size, height: size * 1.3)
                    .background(
                        LinearGradient(
                            colors: highlighted.contains(index)
                                ? [Retro.orange.mix(with: .black, by: 0.3), Retro.orange, Retro.orange.mix(with: .black, by: 0.3)]
                                : [Retro.paperShade.mix(with: .black, by: 0.25), Retro.paper, Retro.paperShade.mix(with: .black, by: 0.25)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
            }
        }
        .padding(5)
        .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(Retro.walnutDeep))
        .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(Retro.brass, lineWidth: 1.5))
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

    var systemImage: String {
        switch self {
        case .lessons: return "book.closed.fill"
        case .words: return "rectangle.stack.fill"
        case .more: return "ellipsis"
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
                    RetroKeyLabel(title: tab.title, systemImage: tab.systemImage, titleSize: 10)
                }
                .buttonStyle(RetroKeyStyle(tint: selection == tab ? .orange : .beige, isLatched: selection == tab))
                .frame(height: 58)
                .accessibilityAddTraits(selection == tab ? .isSelected : [])
            }
        }
        .retroPanel(cornerRadius: 14, padding: 8)
        .padding(.horizontal, 14)
        .padding(.bottom, 4)
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

    /// Wood behind a bottom strip so scrolled content never shows below it.
    func retroBottomBacking() -> some View {
        background(WoodBackground().ignoresSafeArea(edges: .bottom))
    }
}

// MARK: - Wordmark

struct SvenskaWordmark: View {
    var size: CGFloat = 30

    var body: some View {
        Text("Svenska")
            .font(RetroFont.wordmark(size))
            .foregroundStyle(
                LinearGradient(colors: [Retro.mustard.mix(with: .white, by: 0.2), Retro.mustard], startPoint: .top, endPoint: .bottom)
            )
            .shadow(color: .black.opacity(0.5), radius: 0, x: 0, y: 1.5)
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
            .buttonStyle(RetroKeyStyle(tint: .beige))
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
