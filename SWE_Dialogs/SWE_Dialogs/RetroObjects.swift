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

/// 1950s switchboard operator at her language machine. She works the board
/// while the tutor thinks (`OperatorWork` / `OperatorWork2`), and turns round
/// to the learner (`OperatorTalk`) to listen and to speak, flapping the
/// `OperatorMouth` patch while the tutor's voice plays.
struct OperatorSceneView: View {
    enum Pose: Equatable {
        case resting
        case working
        case listening
        case talking
    }

    let pose: Pose

    // Geometry of the artwork, in source pixels.
    static let source = CGSize(width: 932, height: 1456)
    /// Where the machine's coiled cord leaves the bottom of the artwork.
    static let cordExit = CGPoint(x: 415, y: 1456)
    private static let mouth = CGRect(x: 647, y: 197, width: 196, height: 154)

    private var isTurned: Bool {
        pose == .listening || pose == .talking
    }

    var body: some View {
        GeometryReader { proxy in
            let scale = proxy.size.width / Self.source.width
            ZStack(alignment: .topLeading) {
                // Contact shadows traced from the artwork's own feet, so the
                // cabinet, shoes and stool stand on the faceplate.
                Image("OperatorShadow").resizable()
                // Only the cross-fade is animated: an animation over the whole
                // scene would also slide its size when the screen relayouts,
                // pulling the artwork's cord away from the drawn one.
                workingFrame
                    .animation(.easeInOut(duration: 0.22)) { $0.opacity(isTurned ? 0 : 1) }
                talkingFrame(scale: scale)
                    .animation(.easeInOut(duration: 0.22)) { $0.opacity(isTurned ? 1 : 0) }
                // The talking frame sits two pixels higher on the machine.
                OscilloscopeGlass()
                    .frame(width: Self.scopeGlass.width * scale, height: Self.scopeGlass.height * scale)
                    .offset(x: Self.scopeGlass.minX * scale, y: (Self.scopeGlass.minY - (isTurned ? 2 : 0)) * scale)
            }
        }
        .aspectRatio(Self.source, contentMode: .fit)
        .accessibilityHidden(true)
    }

    /// The oscilloscope's glass inside its bezel, painted over by
    /// `OscilloscopeGlass`.
    private static let scopeGlass = CGRect(x: 152, y: 189, width: 116, height: 136)

    /// Two moments at the board, swapped in an uneven rhythm so the
    /// hands look busy rather than mechanical.
    private var workingFrame: some View {
        TimelineView(.animation(minimumInterval: 0.2, paused: pose != .working)) { context in
            let tick = Int(context.date.timeIntervalSinceReferenceDate / 0.2)
            let pattern = [false, false, true, true, true, false, true, false, false, true, true]
            let second = pose == .working && pattern[tick % pattern.count]
            // A clean swap: the second frame is transparent where her first
            // pose reached, so the two cannot be layered.
            Image(second ? "OperatorWork2" : "OperatorWork").resizable()
        }
    }

    private func talkingFrame(scale: CGFloat) -> some View {
        TimelineView(.animation(minimumInterval: 0.09, paused: pose != .talking)) { context in
            let open = pose == .talking && Self.isMouthOpen(at: context.date)
            Image("OperatorTalk").resizable()
                .overlay(alignment: .topLeading) {
                    Image("OperatorMouth").resizable()
                        .frame(width: Self.mouth.width * scale, height: Self.mouth.height * scale)
                        .offset(x: Self.mouth.minX * scale, y: Self.mouth.minY * scale)
                        .opacity(open ? 1 : 0)
                }
        }
    }

    /// Syllable-like flapping: mostly open, with short closes and a breath
    /// every couple of seconds.
    private static func isMouthOpen(at date: Date) -> Bool {
        let tick = Int(date.timeIntervalSinceReferenceDate / 0.11)
        if tick % 23 < 3 { return false }
        let hash = (UInt64(truncatingIfNeeded: tick) &* 2_654_435_761) >> 13
        return hash % 8 < 5
    }
}

/// Amber oscilloscope face with a trace that never stops wandering: the
/// machine is always on, whatever the lesson is doing.
struct OscilloscopeGlass: View {
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            Canvas { canvas, size in
                let glass = Path(ellipseIn: CGRect(origin: .zero, size: size))
                canvas.clip(to: glass)
                canvas.fill(glass, with: .radialGradient(
                    Gradient(colors: [
                        Color(red: 0.42, green: 0.25, blue: 0.07),
                        Color(red: 0.22, green: 0.12, blue: 0.03),
                        Color(red: 0.06, green: 0.04, blue: 0.02),
                    ]),
                    center: CGPoint(x: size.width * 0.5, y: size.height * 0.5),
                    startRadius: 0,
                    endRadius: max(size.width, size.height) * 0.62
                ))

                // Graticule.
                let grid = Color(red: 1, green: 0.62, blue: 0.2).opacity(0.28)
                for column in 1..<6 {
                    let x = size.width * CGFloat(column) / 6
                    canvas.stroke(Path { $0.move(to: CGPoint(x: x, y: 0)); $0.addLine(to: CGPoint(x: x, y: size.height)) }, with: .color(grid), lineWidth: 0.5)
                }
                for row in 1..<7 {
                    let y = size.height * CGFloat(row) / 7
                    canvas.stroke(Path { $0.move(to: CGPoint(x: 0, y: y)); $0.addLine(to: CGPoint(x: size.width, y: y)) }, with: .color(grid), lineWidth: 0.5)
                }

                // Trace: a few drifting sines under a slowly breathing
                // envelope.
                let mid = size.height * 0.48
                let envelope = 0.75 + 0.25 * sin(t * 0.7)
                var trace = Path()
                let steps = 80
                for step in 0...steps {
                    let u = Double(step) / Double(steps)
                    let wave = 0.55 * sin(u * 15 - t * 4.1)
                        + 0.3 * sin(u * 31 - t * 6.7 + 1.3)
                        + 0.15 * sin(u * 57 + t * 2.9)
                    let point = CGPoint(x: size.width * u, y: mid - size.height * 0.2 * envelope * wave)
                    if step == 0 { trace.move(to: point) } else { trace.addLine(to: point) }
                }
                let amber = Color(red: 1, green: 0.66, blue: 0.24)
                canvas.drawLayer { glow in
                    glow.addFilter(.blur(radius: size.width * 0.04))
                    glow.stroke(trace, with: .color(amber.opacity(0.9)), lineWidth: size.width * 0.05)
                }
                canvas.stroke(trace, with: .color(Color(red: 1, green: 0.88, blue: 0.62)), lineWidth: max(0.8, size.width * 0.014))

                // Curved glass: dark rim and a soft sheen at the top left.
                canvas.fill(glass, with: .radialGradient(
                    Gradient(colors: [.clear, .clear, .black.opacity(0.55)]),
                    center: CGPoint(x: size.width * 0.5, y: size.height * 0.5),
                    startRadius: 0,
                    endRadius: max(size.width, size.height) * 0.52
                ))
                canvas.fill(
                    Path(ellipseIn: CGRect(x: size.width * 0.16, y: size.height * 0.08, width: size.width * 0.4, height: size.height * 0.2)),
                    with: .color(.white.opacity(0.07))
                )
            }
        }
        .allowsHitTesting(false)
    }
}

/// The operator scene with the learner's talk key in the foreground, wired
/// into her machine by a coiled cord.
struct OperatorStage<Key: View>: View {
    let pose: OperatorSceneView.Pose
    @ViewBuilder let key: Key

    var body: some View {
        VStack(spacing: 0) {
            OperatorSceneView(pose: pose)
                .overlay {
                    GeometryReader { proxy in
                        let scale = proxy.size.width / OperatorSceneView.source.width
                        Color.clear
                            .frame(width: 1, height: 1)
                            .anchorPreference(key: CordEndsKey.self, value: .center) { ["scene": $0] }
                            .position(
                                x: OperatorSceneView.cordExit.x * scale,
                                y: OperatorSceneView.cordExit.y * scale - 2
                            )
                    }
                }
                .frame(maxHeight: .infinity)
                .padding(.bottom, 30)

            key
                .anchorPreference(key: CordEndsKey.self, value: .center) { ["key": $0] }
        }
        .backgroundPreferenceValue(CordEndsKey.self) { ends in
            GeometryReader { proxy in
                if let scene = ends["scene"], let key = ends["key"] {
                    CoiledCord(from: proxy[key], to: proxy[scene])
                }
            }
        }
    }
}

/// Ends of the talk-key cord: the key's centre and the cord's exit from the
/// operator artwork.
private struct CordEndsKey: PreferenceKey {
    static var defaultValue: [String: Anchor<CGPoint>] = [:]

    static func reduce(value: inout [String: Anchor<CGPoint>], nextValue: () -> [String: Anchor<CGPoint>]) {
        value.merge(nextValue()) { $1 }
    }
}

/// Coiled telephone cord running from the foreground up into the scene,
/// thinning with distance.
struct CoiledCord: View {
    let from: CGPoint
    let to: CGPoint
    var nearWidth: CGFloat = 12
    var farWidth: CGFloat = 6

    var body: some View {
        Canvas { context, _ in
            // Rises from behind the key and carries on along the line of
            // the cord drawn in the artwork.
            let c1 = CGPoint(x: from.x - 70, y: from.y - 30)
            let c2 = CGPoint(x: to.x + 32, y: to.y + 130)
            let samples = 90
            var points: [CGPoint] = []
            for index in 0...samples {
                let t = CGFloat(index) / CGFloat(samples)
                points.append(CGPoint(
                    x: Self.bezier(t, from.x, c1.x, c2.x, to.x),
                    y: Self.bezier(t, from.y, c1.y, c2.y, to.y)
                ))
            }
            func width(at index: Int) -> CGFloat {
                nearWidth + (farWidth - nearWidth) * CGFloat(index) / CGFloat(samples)
            }
            // Soft shadow on the faceplate, then the rubber body.
            for index in 1..<points.count {
                var segment = Path()
                segment.move(to: points[index - 1])
                segment.addLine(to: points[index])
                let shadow = segment.applying(CGAffineTransform(translationX: 2, y: 4))
                context.stroke(shadow, with: .color(.black.opacity(0.28)), style: StrokeStyle(lineWidth: width(at: index) + 2, lineCap: .round))
            }
            for index in 1..<points.count {
                var segment = Path()
                segment.move(to: points[index - 1])
                segment.addLine(to: points[index])
                context.stroke(segment, with: .color(Color(white: 0.04)), style: StrokeStyle(lineWidth: width(at: index) * 0.7, lineCap: .round))
            }
            // Coil turns: overlapping glossy rubber loops, lit from the upper
            // left like the cord in the artwork, packed tighter as the cord
            // recedes.
            var travelled: CGFloat = 0
            var nextTurn: CGFloat = 0
            for index in 1..<points.count {
                let a = points[index - 1]
                let b = points[index]
                let length = hypot(b.x - a.x, b.y - a.y)
                travelled += length
                guard travelled >= nextTurn, length > 0 else { continue }
                let w = width(at: index)
                let angle = atan2(b.y - a.y, b.x - a.x)
                let loop = CGRect(x: -w * 0.32, y: -w / 2, width: w * 0.64, height: w)
                var turn = context
                turn.translateBy(x: b.x, y: b.y)
                turn.rotate(by: .radians(Double(angle)))
                turn.fill(Path(ellipseIn: loop), with: .color(Color(red: 0.07, green: 0.05, blue: 0.05)))
                turn.stroke(Path(ellipseIn: loop), with: .color(.black.opacity(0.7)), lineWidth: 0.6)
                // Highlight sits toward the upper left whatever the cord's
                // direction.
                turn.rotate(by: .radians(-Double(angle)))
                let glint = CGRect(x: -w * 0.24, y: -w * 0.34, width: w * 0.26, height: w * 0.3)
                turn.fill(Path(ellipseIn: glint), with: .color(Color(red: 0.75, green: 0.6, blue: 0.55).opacity(0.38)))
                nextTurn = travelled + w * 0.4
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }

    private static func bezier(_ t: CGFloat, _ p0: CGFloat, _ p1: CGFloat, _ p2: CGFloat, _ p3: CGFloat) -> CGFloat {
        let u = 1 - t
        let start = u * u * u * p0
        let middle = 3 * u * t * (u * p1 + t * p2)
        return start + middle + t * t * t * p3
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
