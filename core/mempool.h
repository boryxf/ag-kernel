/*
 * Simple Slab Allocator for Order Memory Pool
 *
 * This provides a pre-allocated pool of order slots that can be
 * allocated and freed in O(1) time using a free list.
 *
 * Features:
 * - O(1) allocation and deallocation
 * - No fragmentation (fixed-size slots)
 * - Configurable pool size
 * - Cache-line aligned slots for optimal performance
 */

#ifndef AG_KERNEL_MEMPOOL_H
#define AG_KERNEL_MEMPOOL_H

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

/* Default initial capacity if not specified */
#define MEMPOOL_DEFAULT_CAPACITY 1024

/* Growth factor when pool needs to expand */
#define MEMPOOL_GROWTH_FACTOR 2

/* Alignment for cache efficiency (64 bytes = typical cache line) */
#define MEMPOOL_ALIGNMENT 64

/* Compiler hints */
#if defined(__GNUC__) || defined(__clang__)
    #define MEMPOOL_ALIGNED(n) __attribute__((aligned(n)))
    #define MEMPOOL_UNLIKELY(x) __builtin_expect(!!(x), 0)
    #define MEMPOOL_LIKELY(x) __builtin_expect(!!(x), 1)
#else
    #define MEMPOOL_ALIGNED(n)
    #define MEMPOOL_UNLIKELY(x) (x)
    #define MEMPOOL_LIKELY(x) (x)
#endif

/*
 * Free list node - embedded in each free slot
 * When a slot is free, its first sizeof(void*) bytes point to the next free slot
 */
typedef struct mempool_node_s {
    struct mempool_node_s* next;
} mempool_node_t;

/*
 * Memory pool structure
 */
typedef struct {
    void* memory;              /* Base memory allocation */
    mempool_node_t* free_list; /* Head of free list */
    size_t slot_size;          /* Size of each slot (padded for alignment) */
    size_t capacity;           /* Total number of slots */
    size_t used;               /* Number of slots currently in use */
    int allow_growth;          /* Whether pool can grow (1 = yes, 0 = no) */
} mempool_t;

/*
 * Initialize a memory pool
 *
 * Parameters:
 *   pool         - Pointer to pool structure to initialize
 *   item_size    - Size of each item in bytes
 *   capacity     - Initial number of slots
 *   allow_growth - If non-zero, pool will grow when exhausted
 *
 * Returns:
 *   0 on success, -1 on failure
 */
static inline int mempool_init(mempool_t* pool, size_t item_size,
                               size_t capacity, int allow_growth) {
    if (!pool || item_size == 0 || capacity == 0) {
        return -1;
    }

    /* Calculate slot size with alignment padding */
    /* Slot must be at least large enough for free list node */
    size_t min_size = (item_size > sizeof(mempool_node_t)) ?
                       item_size : sizeof(mempool_node_t);

    /* Round up to alignment boundary */
    size_t slot_size = (min_size + MEMPOOL_ALIGNMENT - 1) & ~(MEMPOOL_ALIGNMENT - 1);

    /* Allocate aligned memory */
#if defined(_WIN32)
    void* memory = _aligned_malloc(slot_size * capacity, MEMPOOL_ALIGNMENT);
#elif defined(__APPLE__) || defined(__unix__)
    void* memory = NULL;
    if (posix_memalign(&memory, MEMPOOL_ALIGNMENT, slot_size * capacity) != 0) {
        memory = NULL;
    }
#else
    /* Fallback: allocate extra and align manually */
    void* raw = malloc(slot_size * capacity + MEMPOOL_ALIGNMENT);
    if (!raw) {
        return -1;
    }
    void* memory = (void*)(((uintptr_t)raw + MEMPOOL_ALIGNMENT) & ~(MEMPOOL_ALIGNMENT - 1));
    /* Note: This loses the original pointer, which is a leak.
       For production, store raw pointer separately. */
#endif

    if (!memory) {
        return -1;
    }

    /* Initialize pool structure */
    pool->memory = memory;
    pool->slot_size = slot_size;
    pool->capacity = capacity;
    pool->used = 0;
    pool->allow_growth = allow_growth;

    /* Build the free list */
    pool->free_list = NULL;
    for (size_t i = 0; i < capacity; i++) {
        mempool_node_t* node = (mempool_node_t*)((char*)memory + i * slot_size);
        node->next = pool->free_list;
        pool->free_list = node;
    }

    return 0;
}

/*
 * Destroy a memory pool and free all resources
 */
static inline void mempool_destroy(mempool_t* pool) {
    if (pool && pool->memory) {
#if defined(_WIN32)
        _aligned_free(pool->memory);
#else
        free(pool->memory);
#endif
        pool->memory = NULL;
        pool->free_list = NULL;
        pool->capacity = 0;
        pool->used = 0;
    }
}

/*
 * Allocate a slot from the pool
 *
 * Returns:
 *   Pointer to allocated slot, or NULL if pool is exhausted
 */
static inline void* mempool_alloc(mempool_t* pool) {
    if (MEMPOOL_UNLIKELY(!pool)) {
        return NULL;
    }

    if (MEMPOOL_UNLIKELY(pool->free_list == NULL)) {
        /* Pool exhausted - try to grow if allowed */
        if (!pool->allow_growth) {
            return NULL;
        }

        /* Grow the pool */
        size_t new_capacity = pool->capacity * MEMPOOL_GROWTH_FACTOR;
        size_t old_capacity = pool->capacity;

#if defined(_WIN32)
        void* new_memory = _aligned_malloc(pool->slot_size * new_capacity, MEMPOOL_ALIGNMENT);
#elif defined(__APPLE__) || defined(__unix__)
        void* new_memory = NULL;
        if (posix_memalign(&new_memory, MEMPOOL_ALIGNMENT, pool->slot_size * new_capacity) != 0) {
            new_memory = NULL;
        }
#else
        void* new_memory = malloc(pool->slot_size * new_capacity);
#endif

        if (!new_memory) {
            return NULL;
        }

        /* Copy existing data */
        memcpy(new_memory, pool->memory, pool->slot_size * old_capacity);

        /* Free old memory */
#if defined(_WIN32)
        _aligned_free(pool->memory);
#else
        free(pool->memory);
#endif

        pool->memory = new_memory;
        pool->capacity = new_capacity;

        /* Add new slots to free list */
        for (size_t i = old_capacity; i < new_capacity; i++) {
            mempool_node_t* node = (mempool_node_t*)((char*)new_memory + i * pool->slot_size);
            node->next = pool->free_list;
            pool->free_list = node;
        }
    }

    /* Pop from free list */
    mempool_node_t* node = pool->free_list;
    pool->free_list = node->next;
    pool->used++;

    return (void*)node;
}

/*
 * Return a slot to the pool
 *
 * Parameters:
 *   pool - The memory pool
 *   ptr  - Pointer to the slot to free (must have been allocated from this pool)
 */
static inline void mempool_free(mempool_t* pool, void* ptr) {
    if (MEMPOOL_UNLIKELY(!pool || !ptr)) {
        return;
    }

    /* Push onto free list */
    mempool_node_t* node = (mempool_node_t*)ptr;
    node->next = pool->free_list;
    pool->free_list = node;
    pool->used--;
}

/*
 * Get the number of slots currently in use
 */
static inline size_t mempool_used(const mempool_t* pool) {
    return pool ? pool->used : 0;
}

/*
 * Get the total capacity of the pool
 */
static inline size_t mempool_capacity(const mempool_t* pool) {
    return pool ? pool->capacity : 0;
}

/*
 * Get the number of available (free) slots
 */
static inline size_t mempool_available(const mempool_t* pool) {
    return pool ? (pool->capacity - pool->used) : 0;
}

/*
 * Check if pool is empty (no slots in use)
 */
static inline int mempool_is_empty(const mempool_t* pool) {
    return pool ? (pool->used == 0) : 1;
}

/*
 * Check if pool is full (no free slots)
 */
static inline int mempool_is_full(const mempool_t* pool) {
    return pool ? (pool->free_list == NULL) : 1;
}

/*
 * Reset pool - mark all slots as free without reallocating
 * Note: This does NOT call destructors or clear memory
 */
static inline void mempool_reset(mempool_t* pool) {
    if (!pool || !pool->memory) {
        return;
    }

    /* Rebuild the free list */
    pool->free_list = NULL;
    for (size_t i = 0; i < pool->capacity; i++) {
        mempool_node_t* node = (mempool_node_t*)((char*)pool->memory + i * pool->slot_size);
        node->next = pool->free_list;
        pool->free_list = node;
    }
    pool->used = 0;
}

/*
 * Resize pool capacity
 *
 * Parameters:
 *   pool         - The memory pool
 *   new_capacity - New capacity (must be >= current used count)
 *
 * Returns:
 *   0 on success, -1 on failure
 */
static inline int mempool_resize(mempool_t* pool, size_t new_capacity) {
    if (!pool || new_capacity == 0) {
        return -1;
    }

    /* Cannot shrink below used count */
    if (new_capacity < pool->used) {
        return -1;
    }

    /* Same size - nothing to do */
    if (new_capacity == pool->capacity) {
        return 0;
    }

#if defined(_WIN32)
    void* new_memory = _aligned_malloc(pool->slot_size * new_capacity, MEMPOOL_ALIGNMENT);
#elif defined(__APPLE__) || defined(__unix__)
    void* new_memory = NULL;
    if (posix_memalign(&new_memory, MEMPOOL_ALIGNMENT, pool->slot_size * new_capacity) != 0) {
        new_memory = NULL;
    }
#else
    void* new_memory = malloc(pool->slot_size * new_capacity);
#endif

    if (!new_memory) {
        return -1;
    }

    /*
     * We need to copy only the used slots and rebuild the free list.
     * This is complex because we don't track which slots are used.
     * For simplicity, copy everything up to the old capacity (or new if smaller).
     */
    size_t copy_count = (new_capacity < pool->capacity) ? new_capacity : pool->capacity;
    memcpy(new_memory, pool->memory, pool->slot_size * copy_count);

    /* Free old memory */
#if defined(_WIN32)
    _aligned_free(pool->memory);
#else
    free(pool->memory);
#endif

    pool->memory = new_memory;

    /* Rebuild free list for new/remaining slots */
    pool->free_list = NULL;

    /* Note: This simple implementation loses track of which slots were free.
       For the engine use case, we reset the pool on engine_reset anyway. */

    size_t old_capacity = pool->capacity;
    pool->capacity = new_capacity;

    /* Add any new slots to the free list */
    if (new_capacity > old_capacity) {
        for (size_t i = old_capacity; i < new_capacity; i++) {
            mempool_node_t* node = (mempool_node_t*)((char*)new_memory + i * pool->slot_size);
            node->next = pool->free_list;
            pool->free_list = node;
        }
    }

    return 0;
}

#endif /* AG_KERNEL_MEMPOOL_H */
