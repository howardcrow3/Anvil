import Foundation
import Security

enum KeychainService {
    private static let service = "com.anvil.app"

    static func store(key: String, value: String) throws {
        guard let data = value.data(using: .utf8) else { return }

        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]

        SecItemDelete(query as CFDictionary)

        var addQuery = query
        addQuery[kSecValueData as String] = data

        let status = SecItemAdd(addQuery as CFDictionary, nil)
        guard status == errSecSuccess else {
            throw KeychainError.storeFailed(status)
        }
    }

    static func retrieve(key: String) throws -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)

        switch status {
        case errSecSuccess:
            guard let data = result as? Data else { return nil }
            return String(data: data, encoding: .utf8)
        case errSecItemNotFound:
            return nil
        default:
            throw KeychainError.retrieveFailed(status)
        }
    }

    static func delete(key: String) throws {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key
        ]

        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainError.deleteFailed(status)
        }
    }
}

enum KeychainError: LocalizedError {
    case storeFailed(OSStatus)
    case retrieveFailed(OSStatus)
    case deleteFailed(OSStatus)

    var errorDescription: String? {
        switch self {
        case .storeFailed(let status): "Keychain store failed: \(status)"
        case .retrieveFailed(let status): "Keychain retrieve failed: \(status)"
        case .deleteFailed(let status): "Keychain delete failed: \(status)"
        }
    }
}
