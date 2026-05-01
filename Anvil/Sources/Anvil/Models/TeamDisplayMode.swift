import Foundation

enum TeamDisplayMode: String, CaseIterable, Sendable {
    case dashboard
    case tabbed
    case split
    case focus

    var label: String {
        switch self {
        case .dashboard: "Dashboard"
        case .tabbed: "Tabbed"
        case .split: "Split"
        case .focus: "Focus"
        }
    }

    var icon: String {
        switch self {
        case .dashboard: "square.grid.2x2"
        case .tabbed: "rectangle.topthird.inset.filled"
        case .split: "rectangle.split.2x1"
        case .focus: "rectangle.center.inset.filled"
        }
    }
}
