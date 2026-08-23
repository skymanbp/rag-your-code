"""Search fixture for retrieval evaluation."""


def rank_documents(query, documents):
    """Rank search results by relevance to a text query."""
    return sorted(documents, key=lambda document: relevance(query, document), reverse=True)


def build_search_index(documents):
    """Build an inverted index for fast keyword lookup."""
    return {term: [document for document in documents if term in document] for term in all_terms(documents)}
