import SwiftUI

struct ModelManagerView: View {
    @Environment(ModelViewModel.self) private var modelVM
    @Environment(\.dismiss) private var dismiss
    @State private var pullModelName = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Model Manager")
                    .font(.headline)
                Spacer()
                Button("Done") { dismiss() }
            }
            .padding()

            Divider()

            HStack {
                TextField("Model name (e.g. llama3.2)", text: $pullModelName)
                    .textFieldStyle(.roundedBorder)
                Button("Pull") {
                    Task { await modelVM.pullModel(name: pullModelName) }
                    pullModelName = ""
                }
                .disabled(pullModelName.isEmpty)
            }
            .padding()

            List {
                ForEach(modelVM.groupedModels, id: \.0) { group, models in
                    Section(group) {
                        ForEach(models) { model in
                            ModelRow(model: model)
                        }
                    }
                }
            }
            .listStyle(.inset)

            HStack {
                Button {
                    Task { await modelVM.refreshLocalModels() }
                } label: {
                    Label("Refresh", systemImage: "arrow.clockwise")
                }

                Spacer()

                if modelVM.isLoading {
                    ProgressView()
                        .scaleEffect(0.7)
                }
            }
            .padding()
        }
    }
}

struct ModelRow: View {
    let model: ModelInfo
    @Environment(ModelViewModel.self) private var modelVM

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(model.name)
                    .font(.body)
                HStack(spacing: 8) {
                    Text(model.size)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(model.status.rawValue)
                        .font(.caption)
                        .foregroundStyle(statusColor)
                }
            }

            Spacer()

            if model.provider == .local {
                Button(role: .destructive) {
                    Task { await modelVM.deleteModel(name: model.id) }
                } label: {
                    Image(systemName: "trash")
                        .font(.caption)
                }
                .buttonStyle(.plain)
                .foregroundStyle(.red)
            }
        }
        .padding(.vertical, 2)
    }

    private var statusColor: Color {
        switch model.status {
        case .available: .green
        case .downloading: .orange
        case .loaded: .blue
        case .error: .red
        }
    }
}
