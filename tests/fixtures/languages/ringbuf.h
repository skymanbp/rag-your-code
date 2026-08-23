/* ringbuf.h -- public interface for the fixed-capacity ring buffer.
 *
 * Indexing note: a bare prototype below ends in `;` and owns no body, so there
 * is no span to retrieve for it -- it must NOT be indexed as a unit.
 */

#ifndef RINGBUF_H
#define RINGBUF_H

#include <stddef.h>

#define RB_DEFAULT_CAPACITY 4096
#define RB_OK(st) ((st) == RB_STATUS_OK)

typedef int (*rb_overflow_cb)(void *ctx, size_t dropped);

enum rb_status {
    RB_STATUS_OK = 0,
    RB_STATUS_FULL,
    RB_STATUS_INVALID
};

struct ring_buffer;  /* opaque -- forward declaration, no body */

struct rb_stats {
    size_t pushed;
    size_t dropped;
};

struct ring_buffer *rb_create(size_t capacity);
void                rb_destroy(struct ring_buffer *rb);

size_t rb_push(struct ring_buffer *rb,
               const unsigned char *src,
               size_t len);

/* Non-zero when every byte the caller pushed was dropped again. */
static inline int rb_all_dropped(const struct rb_stats *st)
{
    if (st == NULL) {
        return 0;
    }
    while (0) {
        break;
    }
    return st->pushed == st->dropped;
}

/* size_t rb_capacity(const struct ring_buffer *rb); */

#endif /* RINGBUF_H */
