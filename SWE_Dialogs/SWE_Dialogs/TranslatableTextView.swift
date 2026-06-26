import SwiftUI
import UIKit

struct TranslatableTextView: UIViewRepresentable {
    private let text: String?
    private let attributedText: NSAttributedString?
    private let isScrollEnabled: Bool
    private let showsVerticalScrollIndicator: Bool
    private let textColor: UIColor
    private let font: UIFont
    private let fillsAvailableWidth: Bool
    private let contentOffsetY: Binding<CGFloat>?
    private let onTranslateSelection: ((String) -> Void)?

    init(
        text: String,
        isScrollEnabled: Bool = false,
        showsVerticalScrollIndicator: Bool = false,
        textColor: UIColor = .label,
        font: UIFont = .preferredFont(forTextStyle: .body),
        fillsAvailableWidth: Bool = true,
        contentOffsetY: Binding<CGFloat>? = nil,
        onTranslateSelection: ((String) -> Void)? = nil
    ) {
        self.text = text
        self.attributedText = nil
        self.isScrollEnabled = isScrollEnabled
        self.showsVerticalScrollIndicator = showsVerticalScrollIndicator
        self.textColor = textColor
        self.font = font
        self.fillsAvailableWidth = fillsAvailableWidth
        self.contentOffsetY = contentOffsetY
        self.onTranslateSelection = onTranslateSelection
    }

    init(
        attributedText: NSAttributedString,
        isScrollEnabled: Bool = false,
        showsVerticalScrollIndicator: Bool = false,
        textColor: UIColor = .label,
        font: UIFont = .preferredFont(forTextStyle: .body),
        fillsAvailableWidth: Bool = true,
        contentOffsetY: Binding<CGFloat>? = nil,
        onTranslateSelection: ((String) -> Void)? = nil
    ) {
        self.text = nil
        self.attributedText = attributedText
        self.isScrollEnabled = isScrollEnabled
        self.showsVerticalScrollIndicator = showsVerticalScrollIndicator
        self.textColor = textColor
        self.font = font
        self.fillsAvailableWidth = fillsAvailableWidth
        self.contentOffsetY = contentOffsetY
        self.onTranslateSelection = onTranslateSelection
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(contentOffsetY: contentOffsetY, onTranslateSelection: onTranslateSelection)
    }

    func makeUIView(context: Context) -> ActionableTextView {
        let textView = ActionableTextView()
        textView.offsetCoordinator = context.coordinator
        textView.delegate = context.coordinator
        textView.isEditable = false
        textView.isSelectable = true
        textView.isScrollEnabled = isScrollEnabled
        textView.showsVerticalScrollIndicator = showsVerticalScrollIndicator
        textView.backgroundColor = .clear
        textView.textContainer.lineFragmentPadding = 0
        textView.textContainer.widthTracksTextView = true
        textView.adjustsFontForContentSizeCategory = true
        textView.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        applyStyle(to: textView)
        return textView
    }

    func updateUIView(_ uiView: ActionableTextView, context: Context) {
        context.coordinator.contentOffsetY = contentOffsetY
        context.coordinator.onTranslateSelection = onTranslateSelection
        uiView.delegate = context.coordinator
        uiView.isScrollEnabled = isScrollEnabled
        uiView.showsVerticalScrollIndicator = showsVerticalScrollIndicator

        if let attributedText {
            if uiView.attributedText?.isEqual(to: attributedText) != true {
                uiView.attributedText = attributedText
            }
        } else if let text, uiView.text != text {
            uiView.text = text
        }

        applyStyle(to: uiView)

        if let offsetY = contentOffsetY?.wrappedValue {
            uiView.restoreContentOffsetY(offsetY)
        }
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: ActionableTextView, context: Context) -> CGSize? {
        guard !isScrollEnabled else { return nil }
        let targetWidth = proposal.width
            ?? uiView.window?.windowScene?.screen.bounds.width
            ?? uiView.bounds.width
        let fittingSize = uiView.sizeThatFits(CGSize(width: targetWidth, height: .greatestFiniteMagnitude))
        let width = fillsAvailableWidth ? targetWidth : uiView.measuredTextWidth(maxWidth: targetWidth)
        return CGSize(width: width, height: fittingSize.height)
    }

    private func applyStyle(to textView: UITextView) {
        textView.textColor = textColor
        textView.font = font
        textView.textContainerInset = isScrollEnabled
            ? UIEdgeInsets(top: 0, left: 0, bottom: 16, right: 0)
            : .zero
        textView.scrollIndicatorInsets = isScrollEnabled
            ? UIEdgeInsets(top: 0, left: 0, bottom: 16, right: 0)
            : .zero
    }

    final class Coordinator: NSObject, UITextViewDelegate {
        var contentOffsetY: Binding<CGFloat>?
        var onTranslateSelection: ((String) -> Void)?
        var isApplyingOffset = false

        init(contentOffsetY: Binding<CGFloat>?, onTranslateSelection: ((String) -> Void)?) {
            self.contentOffsetY = contentOffsetY
            self.onTranslateSelection = onTranslateSelection
        }

        func scrollViewDidScroll(_ scrollView: UIScrollView) {
            guard !isApplyingOffset,
                  (scrollView as? ActionableTextView)?.isRestoringContentOffset != true else {
                return
            }
            guard let contentOffsetY else { return }
            let clampedOffsetY = scrollView.translatableClampedContentOffsetY(scrollView.contentOffset.y)
            guard abs(contentOffsetY.wrappedValue - clampedOffsetY) > 0.5 else { return }
            contentOffsetY.wrappedValue = clampedOffsetY
        }

        func textView(
            _ textView: UITextView,
            editMenuForTextInRanges ranges: [NSValue],
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            translateMenu(for: textView, ranges: ranges)
        }

        func textView(
            _ textView: UITextView,
            editMenuForTextIn range: NSRange,
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            translateMenu(for: textView, ranges: [NSValue(range: range)])
        }

        private func translateMenu(for textView: UITextView, ranges: [NSValue]) -> UIMenu? {
            guard let onTranslateSelection,
                  let selection = selectedText(in: ranges, from: textView),
                  !selection.isEmpty else {
                return nil
            }

            let action = UIAction(title: "Translate", image: UIImage(systemName: "translate")) { [weak textView] _ in
                textView?.selectedRange = NSRange(location: 0, length: 0)
                onTranslateSelection(selection)
            }
            return UIMenu(children: [action])
        }

        private func selectedText(in ranges: [NSValue], from textView: UITextView) -> String? {
            let source = (textView.attributedText?.string ?? textView.text ?? "") as NSString
            let selections = ranges.compactMap { value -> String? in
                let range = value.rangeValue
                guard range.location != NSNotFound,
                      range.length > 0,
                      range.location >= 0,
                      NSMaxRange(range) <= source.length else {
                    return nil
                }
                return source.substring(with: range)
            }

            let selection = selections
                .joined(separator: "\n")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return selection.isEmpty ? nil : selection
        }
    }

    final class ActionableTextView: UITextView {
        weak var offsetCoordinator: Coordinator?
        private(set) var isRestoringContentOffset = false
        private var pendingContentOffsetY: CGFloat?

        func measuredTextWidth(maxWidth: CGFloat) -> CGFloat {
            let content: NSAttributedString
            if let attributedText, attributedText.length > 0 {
                content = attributedText
            } else {
                content = NSAttributedString(
                    string: text ?? "",
                    attributes: [
                        .font: font ?? UIFont.preferredFont(forTextStyle: .body)
                    ]
                )
            }
            let boundingRect = content.boundingRect(
                with: CGSize(width: maxWidth, height: .greatestFiniteMagnitude),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                context: nil
            )
            return min(maxWidth, max(1, ceil(boundingRect.width)))
        }

        func restoreContentOffsetY(_ offsetY: CGFloat) {
            guard isScrollEnabled else { return }
            guard !isTracking, !isDragging, !isDecelerating else { return }
            let clampedOffsetY = translatableClampedContentOffsetY(offsetY)
            guard bounds.height <= 0 || contentSize.height <= 0 || abs(contentOffset.y - clampedOffsetY) > 0.5 else {
                pendingContentOffsetY = nil
                isRestoringContentOffset = false
                return
            }

            pendingContentOffsetY = offsetY
            isRestoringContentOffset = true
            setNeedsLayout()
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            applyPendingContentOffsetIfNeeded()
        }

        private func applyPendingContentOffsetIfNeeded() {
            guard let pendingContentOffsetY else { return }
            let clampedOffsetY = translatableClampedContentOffsetY(pendingContentOffsetY)

            guard abs(contentOffset.y - clampedOffsetY) > 0.5 else {
                self.pendingContentOffsetY = nil
                isRestoringContentOffset = false
                return
            }

            offsetCoordinator?.isApplyingOffset = true
            setContentOffset(CGPoint(x: 0, y: clampedOffsetY), animated: false)
            offsetCoordinator?.isApplyingOffset = false
            self.pendingContentOffsetY = nil
            isRestoringContentOffset = false
        }
    }
}

private extension UIScrollView {
    func translatableClampedContentOffsetY(_ offsetY: CGFloat) -> CGFloat {
        let maxOffsetY = max(0, contentSize.height - bounds.height + adjustedContentInset.bottom)
        return min(max(0, offsetY), maxOffsetY)
    }
}

func translationRequestMessage(for selection: String) -> String {
    "Please translate \(selection.trimmingCharacters(in: .whitespacesAndNewlines))."
}
