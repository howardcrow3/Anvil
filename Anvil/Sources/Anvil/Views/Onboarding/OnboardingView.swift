import SwiftUI

enum OnboardingStep: Int, CaseIterable {
    case welcome
    case setupMode
    case modelDownload
    case completion
}

enum SetupMode: String {
    case localOnly
    case cloudOnly
    case both
}

@Observable
final class OnboardingState: @unchecked Sendable {
    var currentStep: OnboardingStep = .welcome
    var setupMode: SetupMode = .both
    var apiKey = ""
    var selectedModelId = ""
    var isDownloading = false
    var downloadProgress: Double = 0

    func advance() {
        switch currentStep {
        case .welcome:
            currentStep = .setupMode
        case .setupMode:
            if setupMode == .cloudOnly {
                currentStep = .completion
            } else {
                currentStep = .modelDownload
            }
        case .modelDownload:
            currentStep = .completion
        case .completion:
            break
        }
    }

    func back() {
        switch currentStep {
        case .welcome: break
        case .setupMode: currentStep = .welcome
        case .modelDownload: currentStep = .setupMode
        case .completion:
            currentStep = setupMode == .cloudOnly ? .setupMode : .modelDownload
        }
    }
}

struct OnboardingView: View {
    @State private var state = OnboardingState()
    let onComplete: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            // Step content
            Group {
                switch state.currentStep {
                case .welcome:
                    WelcomeStep()
                case .setupMode:
                    SetupModeStep()
                case .modelDownload:
                    ModelDownloadStep()
                case .completion:
                    CompletionStep(onComplete: onComplete)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .transition(.push(from: .trailing))
            .animation(.easeInOut(duration: 0.3), value: state.currentStep)

            Divider()

            // Navigation footer
            HStack {
                stepIndicator

                Spacer()

                if state.currentStep != .welcome {
                    Button("Back") {
                        state.back()
                    }
                }

                if state.currentStep != .completion {
                    Button("Continue") {
                        state.advance()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!canAdvance)
                }
            }
            .padding(16)
        }
        .frame(width: 560, height: 440)
        .environment(state)
    }

    private var stepIndicator: some View {
        HStack(spacing: 6) {
            ForEach(OnboardingStep.allCases, id: \.rawValue) { step in
                Circle()
                    .fill(step == state.currentStep ? Color.accentColor : Color.secondary.opacity(0.3))
                    .frame(width: 8, height: 8)
            }
        }
    }

    private var canAdvance: Bool {
        switch state.currentStep {
        case .welcome:
            return true
        case .setupMode:
            if state.setupMode == .cloudOnly || state.setupMode == .both {
                return !state.apiKey.isEmpty
            }
            return true
        case .modelDownload:
            return !state.isDownloading
        case .completion:
            return true
        }
    }
}
