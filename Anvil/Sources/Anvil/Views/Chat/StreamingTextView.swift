import SwiftUI

struct StreamingTextView: View {
    let text: String
    @State private var showCursor = true

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "cpu")
                .font(.title3)
                .frame(width: 28, height: 28)
                .foregroundStyle(.purple)

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Assistant")
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(.purple)
                    Spacer()
                }

                HStack(alignment: .firstTextBaseline, spacing: 0) {
                    Text(text)
                        .textSelection(.enabled)

                    if showCursor {
                        Text("|")
                            .foregroundStyle(.purple)
                            .animation(
                                .easeInOut(duration: 0.5).repeatForever(autoreverses: true),
                                value: showCursor
                            )
                    }
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(.purple.opacity(0.05))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .onAppear { showCursor = true }
    }
}
