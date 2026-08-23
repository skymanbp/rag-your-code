package com.example.sync

import kotlinx.coroutines.delay

/** Immutable snapshot of a remote document (see flush(batchSize) for ordering). */
data class DocumentSnapshot(
    val id: String,
    val revision: Int,
    val payload: String
)

class SyncEngine(private val endpoint: String) {

    private val pending = mutableListOf<String>()

    fun enqueue(docId: String): Boolean {
        if (docId.isBlank()) {
            return false
        }
        for (existing in pending) {
            when (existing) {
                docId -> return false
                else -> continue
            }
        }
        return pending.add(docId)
    }

    suspend fun flush(batchSize: Int = 25): List<DocumentSnapshot> {
        val out = mutableListOf<DocumentSnapshot>()
        while (pending.isNotEmpty() && out.size < batchSize) {
            delay(10)
            out += DocumentSnapshot(pending.removeAt(0), 1, "{ fun ghost() = 0 }")
        }
        return out
    }

    // fun purge() = pending.clear()
}

fun String.toDocumentId(prefix: String = "doc"): String =
    "$prefix-${trim().lowercase().replace(" ", "-")}"
