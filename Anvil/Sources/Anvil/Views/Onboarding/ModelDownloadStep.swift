import SwiftUI

struct LocalModelInfo: Identifiable {
    let id: String
    let name: String
    let parameters: String
    let sizeGB: Double
    let minRAMGB: Int
    let description: String
    let recommendedFor: String
    var bundled: Bool = false
}

private let availableModels: [LocalModelInfo] = [
    LocalModelInfo(id: "gemma4:e2b", name: "Gemma 4 E2B", parameters: "2.3B", sizeGB: 7.2, minRAMGB: 4, description: "Bundled — ready to use, multimodal", recommendedFor: "All Macs", bundled: true),
    LocalModelInfo(id: "gemma4:e4b", name: "Gemma 4 E4B", parameters: "4B", sizeGB: 9.6, minRAMGB: 6, description: "Stronger multimodal (text + image + audio)", recommendedFor: "8GB+ Macs"),
    LocalModelInfo(id: "qwen3:8b", name: "Qwen 3 8B", parameters: "8B", sizeGB: 4.7, minRAMGB: 6, description: "Multilingual, good at coding", recommendedFor: "8GB+ Macs"),
    LocalModelInfo(id: "gemma4:27b", name: "Gemma 4 27B", parameters: "27B", sizeGB: 18.0, minRAMGB: 18, description: "High-quality multimodal reasoning", recommendedFor: "24GB+ Macs"),
    LocalModelInfo(id: "mistral-small:24b", name: "Mistral Small 3.2", parameters: "24B", sizeGB: 14.0, minRAMGB: 16, description: "Strong coding model", recommendedFor: "24GB+ Macs"),
    LocalModelInfo(id: "qwen3:32b", name: "Qwen 3 32B", parameters: "32B", sizeGB: 19.0, minRAMGB: 20, description: "Best local quality", recommendedFor: "32GB+ Macs"),
]

struct ModelDownloadStep: View {
    @Environment(OnboardingState.self) private var state
    @State private var systemRAM: Int = 8

    var body: some View {
        VStack(spacing: 16) {
            Text("Local Models")
                .font(.title2)
                .fontWeight(.bold)
                .padding(.top, 24)

            HStack(spacing: 4) {
                Image(systemName: "memorychip")
                Text("Detected \(systemRAM) GB RAM — Gemma 4 E2B is included and ready to use")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            ScrollView {
                VStack(spacing: 8) {
                    ForEach(availableModels) { model in
                        ModelCard(model: model, isSelected: state.selectedModelId == model.id, fits: model.minRAMGB <= systemRAM) {
                            state.selectedModelId = model.id
                        }
                    }
                }
                .padding(.horizontal, 24)
            }

            if state.isDownloading {
                VStack(spacing: 6) {
                    ProgressView(value: state.downloadProgress)
                        .tint(.accentColor)
                    Text("Downloading \(state.selectedModelId)... \(Int(state.downloadProgress * 100))%")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.horizontal, 24)
            }

            Spacer()
        }
        .task {
            systemRAM = Int(ProcessInfo.processInfo.physicalMemory / (1024 * 1024 * 1024))
            // Auto-select the bundled model if nothing is selected
            if state.selectedModelId.isEmpty {
                state.selectedModelId = "gemma4:e2b"
            }
        }
    }
}

private struct ModelCard: View {
    let model: LocalModelInfo
    let isSelected: Bool
    let fits: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    HStack {
                        Text(model.name)
                            .fontWeight(.medium)
                            .foregroundStyle(isSelected ? .white : .primary)
                        Text(model.parameters)
                            .font(.caption)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(isSelected ? Color.white.opacity(0.2) : Color.secondary.opacity(0.15))
                            .clipShape(Capsule())
                            .foregroundStyle(isSelected ? .white : .secondary)
                    }
                    Text(model.description)
                        .font(.caption)
                        .foregroundStyle(isSelected ? .white.opacity(0.8) : .secondary)
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 2) {
                    if model.bundled {
                        Text("Included")
                            .font(.caption2)
                            .fontWeight(.semibold)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(isSelected ? Color.white.opacity(0.25) : Color.green.opacity(0.15))
                            .foregroundStyle(isSelected ? .white : .green)
                            .clipShape(Capsule())
                    } else {
                        Text(String(format: "%.1f GB", model.sizeGB))
                            .font(.caption)
                            .fontWeight(.medium)
                            .foregroundStyle(isSelected ? .white : .primary)
                    }
                    if !fits {
                        Text("Low RAM")
                            .font(.caption2)
                            .foregroundStyle(.orange)
                    } else {
                        Text(model.recommendedFor)
                            .font(.caption2)
                            .foregroundStyle(isSelected ? Color.white.opacity(0.7) : Color.secondary)
                    }
                }

                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.white)
                }
            }
            .padding(10)
            .background(isSelected ? Color.accentColor : Color.secondary.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .opacity(fits ? 1.0 : 0.6)
        }
        .buttonStyle(.plain)
    }
}
