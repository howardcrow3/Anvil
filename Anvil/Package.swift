// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "Anvil",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "Anvil", targets: ["Anvil"])
    ],
    targets: [
        .executableTarget(
            name: "Anvil",
            path: "Sources/Anvil"
        ),
        .testTarget(
            name: "AnvilTests",
            dependencies: ["Anvil"],
            path: "Tests/AnvilTests"
        )
    ]
)
