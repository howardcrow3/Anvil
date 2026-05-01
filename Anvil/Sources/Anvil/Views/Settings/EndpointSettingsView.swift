import SwiftUI

struct EndpointSettingsView: View {
    @Environment(SettingsViewModel.self) private var settingsVM
    @State private var showAddSheet = false
    @State private var editingEndpoint: Endpoint?

    var body: some View {
        VStack(spacing: 0) {
            List {
                if settingsVM.settings.endpoints.isEmpty {
                    Text("No custom endpoints configured.")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding()
                } else {
                    ForEach(settingsVM.settings.endpoints) { endpoint in
                        EndpointRow(endpoint: endpoint) {
                            editingEndpoint = endpoint
                        } onDelete: {
                            settingsVM.removeEndpoint(endpoint)
                        }
                    }
                }
            }
            .listStyle(.inset)

            Divider()

            HStack {
                Spacer()
                Button {
                    showAddSheet = true
                } label: {
                    Label("Add Endpoint", systemImage: "plus")
                }
                .padding()
            }
        }
        .sheet(isPresented: $showAddSheet) {
            EndpointEditorView { endpoint in
                settingsVM.addEndpoint(endpoint)
            }
        }
        .sheet(item: $editingEndpoint) { endpoint in
            EndpointEditorView(endpoint: endpoint) { updated in
                settingsVM.updateEndpoint(updated)
            }
        }
    }
}

struct EndpointRow: View {
    let endpoint: Endpoint
    let onEdit: () -> Void
    let onDelete: () -> Void

    var body: some View {
        HStack {
            Circle()
                .fill(endpoint.isReachable ? .green : .red)
                .frame(width: 8, height: 8)

            VStack(alignment: .leading, spacing: 2) {
                Text(endpoint.name)
                    .fontWeight(.medium)
                Text(endpoint.baseURL)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Button("Edit", action: onEdit)
                .buttonStyle(.plain)
                .foregroundStyle(.blue)

            Button("Delete", role: .destructive, action: onDelete)
                .buttonStyle(.plain)
                .foregroundStyle(.red)
        }
        .padding(.vertical, 4)
    }
}

struct EndpointEditorView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var baseURL = ""
    @State private var apiKey = ""
    @State private var defaultModel = ""

    let existingEndpoint: Endpoint?
    let onSave: (Endpoint) -> Void

    init(endpoint: Endpoint? = nil, onSave: @escaping (Endpoint) -> Void) {
        self.existingEndpoint = endpoint
        self.onSave = onSave
    }

    var body: some View {
        VStack(spacing: 16) {
            Text(existingEndpoint == nil ? "Add Endpoint" : "Edit Endpoint")
                .font(.headline)

            Form {
                TextField("Name", text: $name)
                TextField("Base URL", text: $baseURL)
                SecureField("API Key", text: $apiKey)
                TextField("Default Model", text: $defaultModel)
            }
            .formStyle(.grouped)

            HStack {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Save") {
                    let endpoint = Endpoint(
                        id: existingEndpoint?.id ?? UUID(),
                        name: name,
                        baseURL: baseURL,
                        apiKey: apiKey,
                        defaultModel: defaultModel
                    )
                    onSave(endpoint)
                    dismiss()
                }
                .disabled(name.isEmpty || baseURL.isEmpty)
            }
            .padding()
        }
        .frame(width: 400, height: 300)
        .onAppear {
            if let ep = existingEndpoint {
                name = ep.name
                baseURL = ep.baseURL
                apiKey = ep.apiKey
                defaultModel = ep.defaultModel
            }
        }
    }
}
