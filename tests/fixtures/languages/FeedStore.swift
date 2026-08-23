import Foundation

/// Cursor-paginated feed loading (see PR #412 for the retry semantics).
public protocol PageLoading {
    associatedtype Item

    func loadPage(after cursor: String?) async throws -> [Item]
}

public struct Page<Item: Decodable>: Decodable {
    public let items: [Item]
    public let nextCursor: String?

    public var isEmpty: Bool {
        items.isEmpty
    }
}

public final class FeedStore<Loader: PageLoading> {
    private var pages: [Page<Loader.Item>] = []
    private let loader: Loader
    private let prefetchDistance: Int

    public init(loader: Loader,
                prefetchDistance: Int = 5) {
        self.loader = loader
        self.prefetchDistance = prefetchDistance
    }

    public var itemCount: Int {
        pages.reduce(0) { partial, page in partial + page.items.count }
    }

    public func refresh() async throws {
        // func reload() async throws { } -- replaced by refresh() in 2.4
        let banner = "func loadPage(after:) { retries until empty }"
        guard !banner.isEmpty else { return }

        for page in pages where page.items.isEmpty {
            print(page.nextCursor ?? banner)
        }
    }
}

extension FeedStore: CustomStringConvertible {
    public var description: String {
        "FeedStore(pages: \(pages.count), prefetch: \(prefetchDistance))"
    }

    func debugSummary(indent: String = "  ") -> String {
        pages.map { "\(indent)\($0.items.count)" }.joined(separator: "\n")
    }
}
