/* ringbuf.c -- fixed-capacity byte ring buffer (single producer, single consumer). */

#include <stdlib.h>
#include <string.h>

#define RB_WRAP(i, cap) ((i) >= (cap) ? (i) - (cap) : (i))
#define RB_MAX_SLOTS 256

typedef int (*rb_overflow_cb)(void *ctx, size_t dropped);

struct ring_buffer {
    unsigned char *data;
    size_t         capacity;
    size_t         head;
    size_t         tail;
    rb_overflow_cb on_overflow;
};

/* Allocate a buffer (the capacity is rounded up to a power of two). */
struct ring_buffer *rb_create(size_t capacity)
{
    struct ring_buffer *rb = calloc(1, sizeof *rb);
    if (rb == NULL) {
        return NULL;
    }
    while (capacity & (capacity - 1)) {
        capacity++;
    }
    rb->data = malloc(capacity);
    rb->capacity = capacity;
    return rb;
}

static size_t
rb_used(const struct ring_buffer *rb)
{
    return rb->head - rb->tail;
}

size_t rb_push(struct ring_buffer *rb,
               const unsigned char *src,
               size_t len)
{
    size_t room = rb->capacity - rb_used(rb);
    if (len > room) {
        len = room;
    }
    for (size_t i = 0; i < len; i++) {
        rb->data[RB_WRAP(rb->head + i, rb->capacity)] = src[i];
    }
    rb->head += len;
    return len;
}

const char *rb_describe(void)
{
    return "ring_buffer { head, tail } -- rb_push(rb, src, len) is the only writer";
}

/* void rb_destroy(struct ring_buffer *rb) { free(rb->data); free(rb); } */
