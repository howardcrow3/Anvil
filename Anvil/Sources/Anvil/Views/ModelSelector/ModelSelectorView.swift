import SwiftUI

struct ModelSelectorView: View {
    @Environment(ModelViewModel.self) private var modelVM
    @State private var showModelManager = false

    var body: some View {
        Menu {
            ForEach(modelVM.groupedModels, id: \.0) { group, models in
                Section(group) {
                    ForEach(models) { model in
                        Button {
                            modelVM.selectModel(model)
                        } label: {
                            HStack {
                                Text(model.name)
                                Spacer()
                                if model.id == modelVM.selectedModel?.id {
                                    Image(systemName: "checkmark")
                                }
                                statusIndicator(for: model)
                            }
                        }
                    }
                }
            }

            Divider()

            Button("Manage Models...") {
                showModelManager = true
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "cpu")
                    .font(.caption)
                Text(modelVM.selectedModel?.name ?? "Select Model")
                    .font(.caption)
                    .fontWeight(.medium)
                Image(systemName: "chevron.down")
                    .font(.caption2)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(.quaternary)
            .clipShape(RoundedRectangle(cornerRadius: 6))
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .sheet(isPresented: $showModelManager) {
            ModelManagerView()
                .frame(width: 500, height: 400)
        }
    }

    private func statusIndicator(for model: ModelInfo) -> some View {
        Circle()
            .fill(statusColor(for: model.status))
            .frame(width: 6, height: 6)
    }

    private func statusColor(for status: ModelStatus) -> Color {
        switch status {
        case .available: .green
        case .downloading: .orange
        case .loaded: .blue
        case .error: .red
        }
    }
}
