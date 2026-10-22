import SwiftUI

// Illustrated hardware objects: cassette, one-piece handset, VU meter.

/// Compact cassette (`CassetteBody` artwork) with a printed label and reel
/// hubs (`CassetteHub`) that turn while audio plays. Without a `width` it
/// fills the width it is offered. `isInserted` hides the lower edge in a deck
/// slot, leaving the label and reels.
struct CassetteView: View {
    let isPlaying: Bool
    var label = "Svenska"
    var width: CGFloat?
    var isInserted = false

    // Geometry of the artwork, in source pixels (675 x 415).
    static func aspectRatio(isInserted: Bool) -> CGFloat {
        source.width / (isInserted ? insertedHeight : source.height)
    }

    private static let source = CGSize(width: 675, height: 415)
    private static let insertedHeight: CGFloat = 292
    private static let labelRect = CGRect(x: 51, y: 47, width: 569, height: 82)
    private static let hubCentres = [CGPoint(x: 198.5, y: 203.5), CGPoint(x: 477, y: 204)]
    private static let hubDiameter: CGFloat = 100

    var body: some View {
        GeometryReader { proxy in
            let scale = proxy.size.width / Self.source.width
            ZStack(alignment: .topLeading) {
                Image("CassetteBody")
                    .resizable()
                    .frame(width: Self.source.width * scale, height: Self.source.height * scale)

                Text(label.uppercased())
                    .font(RetroFont.digits(Self.labelRect.height * scale * 0.34))
                    .tracking(1)
                    .foregroundStyle(Retro.ink.opacity(0.85))
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                    .frame(width: Self.labelRect.width * scale, height: Self.labelRect.height * scale)
                    .offset(x: Self.labelRect.minX * scale, y: Self.labelRect.minY * scale)

                ForEach(Self.hubCentres.indices, id: \.self) { index in
                    let centre = Self.hubCentres[index]
                    CassetteHub(isTurning: isPlaying, diameter: Self.hubDiameter * scale)
                        .offset(
                            x: (centre.x - Self.hubDiameter / 2) * scale,
                            y: (centre.y - Self.hubDiameter / 2) * scale
                        )
                }
            }
            .frame(width: proxy.size.width, height: proxy.size.height, alignment: .top)
            .clipped()
            .overlay(alignment: .bottom) {
                if isInserted {
                    // Lip of the deck slot the cassette slides into.
                    LinearGradient(colors: [Color.black.opacity(0.9), Color(white: 0.12)], startPoint: .top, endPoint: .bottom)
                        .frame(height: 8)
                        .overlay(alignment: .top) { Rectangle().fill(Color.white.opacity(0.12)).frame(height: 1) }
                        .shadow(color: .black.opacity(0.6), radius: 3, y: -2)
                }
            }
        }
        .aspectRatio(Self.aspectRatio(isInserted: isInserted), contentMode: .fit)
        .frame(width: width)
        .shadow(color: .black.opacity(0.45), radius: 3, y: 2)
        .accessibilityHidden(true)
    }
}

/// Narrow window onto the cassette's reels, as seen through the smoked lid
/// of a tape deck. Crops the `CassetteBody` artwork to the reel band.
struct CassetteReelWindow: View {
    let isPlaying: Bool
    var width: CGFloat = 112

    // Visible band of the 675 x 415 artwork, in source pixels.
    private static let band = CGRect(x: 118, y: 142, width: 440, height: 124)
    private static let source = CGSize(width: 675, height: 415)
    private static let hubCentres = [CGPoint(x: 198.5, y: 203.5), CGPoint(x: 477, y: 204)]
    private static let hubDiameter: CGFloat = 100

    var body: some View {
        let scale = width / Self.band.width
        ZStack(alignment: .topLeading) {
            Image("CassetteBody")
                .resizable()
                .frame(width: Self.source.width * scale, height: Self.source.height * scale)
            ForEach(Self.hubCentres.indices, id: \.self) { index in
                let centre = Self.hubCentres[index]
                CassetteHub(isTurning: isPlaying, diameter: Self.hubDiameter * scale)
                    .offset(
                        x: (centre.x - Self.hubDiameter / 2) * scale,
                        y: (centre.y - Self.hubDiameter / 2) * scale
                    )
            }
        }
        .offset(x: -Self.band.minX * scale, y: -Self.band.minY * scale)
        .frame(width: width, height: Self.band.height * scale, alignment: .topLeading)
        .clipped()
        // Smoked lid with a glint across the top.
        .overlay(
            LinearGradient(colors: [Color.white.opacity(0.1), Color.black.opacity(0.15), Color.black.opacity(0.3)], startPoint: .top, endPoint: .bottom)
        )
        .clipShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 4, style: .continuous).stroke(Color.black.opacity(0.8), lineWidth: 1.5))
        .overlay(RoundedRectangle(cornerRadius: 4, style: .continuous).stroke(Color.white.opacity(0.08), lineWidth: 1).padding(1.5))
        .accessibilityHidden(true)
    }
}

/// Inserted cassette on the left and a key on the right at the cassette's
/// full height, sharing the row with no dead space.
struct CassetteDeckLayout: Layout {
    /// Key width as a fraction of the cassette width.
    var keyRatio: CGFloat = 0.42
    var spacing: CGFloat = 10

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 360
        return CGSize(width: width, height: cassetteWidth(in: width) / CassetteView.aspectRatio(isInserted: true))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard subviews.count == 2 else { return }
        let cassette = cassetteWidth(in: bounds.width)
        let key = bounds.width - cassette - spacing
        subviews[0].place(at: bounds.origin, proposal: ProposedViewSize(width: cassette, height: bounds.height))
        subviews[1].place(
            at: CGPoint(x: bounds.maxX - key, y: bounds.minY),
            proposal: ProposedViewSize(width: key, height: bounds.height)
        )
    }

    private func cassetteWidth(in width: CGFloat) -> CGFloat {
        (width - spacing) / (1 + keyRatio)
    }
}

private struct CassetteHub: View {
    let isTurning: Bool
    let diameter: CGFloat

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !isTurning)) { context in
            let angle = isTurning ? context.date.timeIntervalSinceReferenceDate * 140 : 0
            Image("CassetteHub")
                .resizable()
                .frame(width: diameter, height: diameter)
                .rotationEffect(.degrees(angle.truncatingRemainder(dividingBy: 360)))
        }
    }
}

/// Ivory Ericofon (`Ericofon` artwork, front view).
struct HandsetView: View {
    var height: CGFloat = 150

    var body: some View {
        Image("Ericofon")
            .resizable()
            .aspectRatio(contentMode: .fit)
            .frame(height: height)
            .shadow(color: .black.opacity(0.55), radius: 8, x: 2, y: 6)
            .accessibilityHidden(true)
    }
}

/// 1980s Swedish classroom computer (`SchoolComputer` artwork) with an amber
/// greeting and blinking cursor drawn on its CRT, resting on a contact shadow.
struct SchoolComputerView: View {
    var width: CGFloat = 300

    // Geometry of the artwork, in source pixels (1351 x 934).
    private static let source = CGSize(width: 1351, height: 934)
    private static let glass = CGRect(x: 280, y: 140, width: 580, height: 330)

    var body: some View {
        let scale = width / Self.source.width
        Image("SchoolComputer")
            .resizable()
            .frame(width: width, height: Self.source.height * scale)
            .overlay(alignment: .topLeading) {
                TimelineView(.periodic(from: .now, by: 0.6)) { context in
                    let cursorOn = Int(context.date.timeIntervalSinceReferenceDate / 0.6) % 2 == 0
                    VStack(alignment: .leading, spacing: 6) {
                        Text("> HEJ!")
                        Text("> VÄLKOMMEN" + (cursorOn ? "█" : " "))
                    }
                    .font(RetroFont.digits(54 * scale))
                    .foregroundStyle(Retro.amber)
                    .shadow(color: Retro.amber.opacity(0.75), radius: 4)
                    .frame(width: Self.glass.width * scale, height: Self.glass.height * scale, alignment: .leading)
                    .offset(x: Self.glass.minX * scale, y: Self.glass.minY * scale)
                }
            }
            .background(alignment: .bottom) {
                Ellipse()
                    .fill(Color.black.opacity(0.6))
                    .frame(width: width * 0.96, height: 26)
                    .blur(radius: 10)
                    .offset(y: 8)
            }
            .accessibilityHidden(true)
    }
}

/// Analog VU meter: `VUMeterFace` artwork with a coded needle that swings
/// while sound is active.
struct VUMeterView: View {
    let isActive: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 20, paused: !isActive)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            let wobble = isActive ? 0.45 + 0.25 * sin(t * 7.3) + 0.15 * sin(t * 17.1) : 0.02
            VUMeterFace(level: wobble)
        }
        .frame(maxWidth: 290)
        .accessibilityHidden(true)
    }
}

private struct VUMeterFace: View {
    let level: Double

    // Geometry of the artwork, in source pixels (617 x 354).
    private static let source = CGSize(width: 617, height: 354)
    private static let pivot = CGPoint(x: 303.3, y: 561.4)
    private static let needleLength: CGFloat = 478
    private static let sweep: ClosedRange<Double> = -31...33

    var body: some View {
        Image("VUMeterFace")
            .resizable()
            .aspectRatio(Self.source, contentMode: .fit)
            .overlay {
                GeometryReader { proxy in
                    let scale = proxy.size.width / Self.source.width
                    let pivot = CGPoint(x: Self.pivot.x * scale, y: Self.pivot.y * scale)
                    let fraction = min(max(level, 0), 1)
                    let angle = Angle.degrees(Self.sweep.lowerBound + (Self.sweep.upperBound - Self.sweep.lowerBound) * fraction)
                    Path { path in
                        path.move(to: pivot)
                        path.addLine(to: CGPoint(
                            x: pivot.x + Self.needleLength * scale * CGFloat(sin(angle.radians)),
                            y: pivot.y - Self.needleLength * scale * CGFloat(cos(angle.radians))
                        ))
                    }
                    .stroke(Retro.ink, style: StrokeStyle(lineWidth: 1.6, lineCap: .round))
                    .shadow(color: .black.opacity(0.35), radius: 1.5, x: 2, y: 2)
                }
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .padding(6)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Retro.crt.shadow(.inner(color: .black.opacity(0.8), radius: 4, y: 2)))
            )
            .shadow(color: .black.opacity(0.4), radius: 3, y: 2)
    }
}

/// Row of amber LED segments used as an audio progress strip.
struct SegmentProgressBar: View {
    let progress: Double
    var segments = 24
    var height: CGFloat = 12

    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<segments, id: \.self) { index in
                let lit = Double(index) < progress * Double(segments)
                RoundedRectangle(cornerRadius: 1)
                    .fill(lit ? Retro.amber : Retro.amber.opacity(0.14))
                    .shadow(color: lit ? Retro.amber.opacity(0.6) : .clear, radius: 2)
            }
        }
        .frame(height: height)
    }
}
