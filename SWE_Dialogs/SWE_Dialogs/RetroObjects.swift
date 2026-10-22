import SwiftUI

// Illustrated hardware objects: cassette, one-piece handset, VU meter.

/// Compact cassette with reels that turn while audio plays.
struct CassetteView: View {
    let isPlaying: Bool
    var label = "Svenska"

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(Retro.ink)
            VStack(spacing: 4) {
                ZStack {
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .fill(Retro.paper)
                    VStack(spacing: 2) {
                        Text(label)
                            .font(RetroFont.label(10))
                            .foregroundStyle(Retro.inkOrange)
                        HStack(spacing: 0) {
                            Rectangle().fill(Retro.orange).frame(height: 2)
                        }
                        Rectangle().fill(Retro.mustard).frame(height: 2)
                    }
                    .padding(.horizontal, 10)
                    .padding(.top, 3)
                    .frame(maxHeight: .infinity, alignment: .top)
                }
                .frame(height: 26)

                HStack(spacing: 0) {
                    CassetteReel(isTurning: isPlaying)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Retro.walnutDeep)
                        .frame(height: 12)
                        .overlay(Rectangle().fill(Retro.walnutLight).frame(width: 18, height: 8))
                        .padding(.horizontal, 6)
                    CassetteReel(isTurning: isPlaying)
                }
                .padding(.horizontal, 10)
            }
            .padding(6)
        }
        .frame(width: 132, height: 78)
        .accessibilityHidden(true)
    }
}

private struct CassetteReel: View {
    let isTurning: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: !isTurning)) { context in
            let angle = isTurning ? context.date.timeIntervalSinceReferenceDate * 140 : 0
            ZStack {
                Circle().fill(Retro.paper)
                ForEach(0..<6, id: \.self) { tooth in
                    Rectangle()
                        .fill(Retro.ink)
                        .frame(width: 2.5, height: 5)
                        .offset(y: -5)
                        .rotationEffect(.degrees(Double(tooth) * 60))
                }
                Circle().fill(Retro.ink).frame(width: 5, height: 5)
            }
            .frame(width: 22, height: 22)
            .rotationEffect(.degrees(angle.truncatingRemainder(dividingBy: 360)))
        }
    }
}

/// Silhouette of a one-piece 1950s–80s Swedish handset: round base, curved
/// neck, earpiece on top.
struct HandsetShape: Shape {
    func path(in rect: CGRect) -> Path {
        let w = rect.width
        let h = rect.height
        var path = Path()
        path.move(to: CGPoint(x: w * 0.10, y: h))
        path.addCurve(
            to: CGPoint(x: w * 0.30, y: h * 0.58),
            control1: CGPoint(x: w * 0.02, y: h * 0.78),
            control2: CGPoint(x: w * 0.30, y: h * 0.72)
        )
        path.addCurve(
            to: CGPoint(x: w * 0.26, y: h * 0.14),
            control1: CGPoint(x: w * 0.30, y: h * 0.42),
            control2: CGPoint(x: w * 0.18, y: h * 0.26)
        )
        path.addCurve(
            to: CGPoint(x: w * 0.74, y: h * 0.14),
            control1: CGPoint(x: w * 0.34, y: -h * 0.04),
            control2: CGPoint(x: w * 0.66, y: -h * 0.04)
        )
        path.addCurve(
            to: CGPoint(x: w * 0.70, y: h * 0.58),
            control1: CGPoint(x: w * 0.82, y: h * 0.26),
            control2: CGPoint(x: w * 0.70, y: h * 0.42)
        )
        path.addCurve(
            to: CGPoint(x: w * 0.90, y: h),
            control1: CGPoint(x: w * 0.70, y: h * 0.72),
            control2: CGPoint(x: w * 0.98, y: h * 0.78)
        )
        path.closeSubpath()
        return path
    }
}

struct HandsetView: View {
    var color: Color = Retro.orange
    var width: CGFloat = 130

    var body: some View {
        ZStack {
            HandsetShape()
                .fill(
                    LinearGradient(
                        colors: [color.mix(with: .white, by: 0.25), color, color.mix(with: .black, by: 0.35)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
            HandsetShape()
                .stroke(Color.white.opacity(0.18), lineWidth: 1)
            // Speaker grille on the earpiece.
            VStack(spacing: 4) {
                ForEach(0..<3, id: \.self) { row in
                    HStack(spacing: 4) {
                        ForEach(0..<(row == 1 ? 4 : 3), id: \.self) { _ in
                            Circle().fill(Color.black.opacity(0.45)).frame(width: 4, height: 4)
                        }
                    }
                }
            }
            .frame(maxHeight: .infinity, alignment: .top)
            .padding(.top, width * 0.12)
        }
        .frame(width: width, height: width * 1.25)
        .shadow(color: .black.opacity(0.45), radius: 8, y: 6)
        .accessibilityHidden(true)
    }
}

/// Analog VU meter. `level` is 0...1; the needle eases toward it.
struct VUMeterView: View {
    let isActive: Bool

    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 20, paused: !isActive)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            let wobble = isActive ? 0.45 + 0.25 * sin(t * 7.3) + 0.15 * sin(t * 17.1) : 0.02
            VUMeterFace(level: wobble)
        }
        .frame(maxWidth: 290)
        .frame(height: 120)
        .accessibilityHidden(true)
    }
}

private struct VUMeterFace: View {
    let level: Double

    var body: some View {
        GeometryReader { proxy in
            let size = proxy.size
            let radius = min(size.height * 0.95, size.width * 0.48)
            let pivot = CGPoint(x: size.width / 2, y: size.height * 0.08 + radius)
            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(
                        LinearGradient(colors: [Retro.paper, Retro.mustard.mix(with: Retro.paper, by: 0.6)], startPoint: .top, endPoint: .bottom)
                    )
                Canvas { context, _ in
                    for index in 0...10 {
                        let fraction = Double(index) / 10
                        let angle = Angle.degrees(-50 + 100 * fraction)
                        let outer = point(pivot, radius, angle)
                        let inner = point(pivot, radius - (index % 5 == 0 ? 14 : 8), angle)
                        var tick = Path()
                        tick.move(to: inner)
                        tick.addLine(to: outer)
                        context.stroke(tick, with: .color(fraction > 0.75 ? Retro.pencilRed : Retro.ink), lineWidth: 1.5)
                    }
                    var needle = Path()
                    needle.move(to: pivot)
                    needle.addLine(to: point(pivot, radius + 4, .degrees(-50 + 100 * min(max(level, 0), 1))))
                    context.stroke(needle, with: .color(Retro.ink), lineWidth: 2)
                }
                Text("VU")
                    .font(RetroFont.label(12))
                    .foregroundStyle(Retro.ink)
                    .position(x: size.width / 2, y: size.height * 0.72)
            }
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .padding(6)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Retro.walnutDeep))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(Retro.brass, lineWidth: 2))
    }

    private func point(_ pivot: CGPoint, _ radius: CGFloat, _ angle: Angle) -> CGPoint {
        CGPoint(
            x: pivot.x + radius * CGFloat(sin(angle.radians)),
            y: pivot.y - radius * CGFloat(cos(angle.radians))
        )
    }
}

/// Row of amber LED segments used as an audio progress strip.
struct SegmentProgressBar: View {
    let progress: Double
    var segments = 24

    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<segments, id: \.self) { index in
                let lit = Double(index) < progress * Double(segments)
                RoundedRectangle(cornerRadius: 1)
                    .fill(lit ? Retro.amber : Retro.amber.opacity(0.14))
                    .shadow(color: lit ? Retro.amber.opacity(0.6) : .clear, radius: 2)
            }
        }
        .frame(height: 12)
    }
}
