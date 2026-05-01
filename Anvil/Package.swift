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
    dependencies: [
        .package(url: "https://github.com/sparkle-project/Sparkle", from: "2.6.0"),
    ],
    targets: [
        .executableTarget(
            name: "Anvil",
            dependencies: [
                .product(name: "Sparkle", package: "Sparkle"),
            ],
            path: "Sources/Anvil"
        ),
        .testTarget(
            name: "AnvilTests",
            dependencies: ["Anvil"],
            path: "Tests/AnvilTests"
        )
    ]
)
