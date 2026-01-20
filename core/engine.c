#include "engine.h"
#include "mempool.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* AVX2 support for SIMD order matching */
#ifdef __AVX2__
#include <immintrin.h>
#define SIMD_WIDTH 4  /* Process 4 orders at a time with 256-bit registers */
#endif

/* Lazy compaction threshold - only compact when this many inactive orders accumulate */
#define COMPACTION_THRESHOLD 10

/* Alignment for SIMD-friendly data access (AVX2 = 32 bytes, AVX-512 = 64 bytes) */
#define CACHE_LINE_SIZE 64

/* SCALING CONVENTION:
 * - Quantities (order->qty, position) are scaled by 1,000,000 from Rust side
 * - When doing financial calculations (notional, PnL), must divide by 1,000,000.0
 * - Price ticks and tick_size remain unscaled
 */

/* Compiler hints for optimization */
#if defined(__GNUC__) || defined(__clang__)
    #define LIKELY(x)   __builtin_expect(!!(x), 1)
    #define UNLIKELY(x) __builtin_expect(!!(x), 0)
    #define RESTRICT    __restrict__
    #define ALWAYS_INLINE __attribute__((always_inline)) inline
    #define HOT_FUNCTION __attribute__((hot))
    #define ALIGNED(n) __attribute__((aligned(n)))
#else
    #define LIKELY(x)   (x)
    #define UNLIKELY(x) (x)
    #define RESTRICT
    #define ALWAYS_INLINE inline
    #define HOT_FUNCTION
    #define ALIGNED(n)
#endif

/*
 * Internal order tracking structure
 * Aligned to 64 bytes for cache line efficiency
 */
typedef struct ALIGNED(64) {
    order_t order;
    int active;      /* 1 if order is active, 0 if cancelled/filled */
    int _padding[3]; /* Pad to 64 bytes for cache line alignment */
} tracked_order_t;

/*
 * SIMD-friendly order data layout for vectorized matching
 * Stored in Structure-of-Arrays format for better SIMD utilization
 */
#ifdef __AVX2__
typedef struct ALIGNED(32) {
    int64_t* price_ticks;   /* Order limit prices */
    int64_t* sides;         /* Order sides (0 = buy, 1 = sell) */
    int64_t* types;         /* Order types (0 = limit, 1 = market) */
    int32_t* active;        /* Active flags */
    size_t capacity;        /* Allocated capacity */
} simd_order_data_t;

static int simd_order_data_init(simd_order_data_t* data, size_t capacity) {
    data->capacity = capacity;

    /* Allocate aligned memory for each array */
    data->price_ticks = (int64_t*)aligned_alloc(32, capacity * sizeof(int64_t));
    data->sides = (int64_t*)aligned_alloc(32, capacity * sizeof(int64_t));
    data->types = (int64_t*)aligned_alloc(32, capacity * sizeof(int64_t));
    data->active = (int32_t*)aligned_alloc(32, capacity * sizeof(int32_t));

    if (!data->price_ticks || !data->sides || !data->types || !data->active) {
        free(data->price_ticks);
        free(data->sides);
        free(data->types);
        free(data->active);
        return -1;
    }

    memset(data->price_ticks, 0, capacity * sizeof(int64_t));
    memset(data->sides, 0, capacity * sizeof(int64_t));
    memset(data->types, 0, capacity * sizeof(int64_t));
    memset(data->active, 0, capacity * sizeof(int32_t));

    return 0;
}

static void simd_order_data_destroy(simd_order_data_t* data) {
    free(data->price_ticks);
    free(data->sides);
    free(data->types);
    free(data->active);
    data->price_ticks = NULL;
    data->sides = NULL;
    data->types = NULL;
    data->active = NULL;
    data->capacity = 0;
}

static int simd_order_data_resize(simd_order_data_t* data, size_t new_capacity) {
    int64_t* new_prices = (int64_t*)aligned_alloc(32, new_capacity * sizeof(int64_t));
    int64_t* new_sides = (int64_t*)aligned_alloc(32, new_capacity * sizeof(int64_t));
    int64_t* new_types = (int64_t*)aligned_alloc(32, new_capacity * sizeof(int64_t));
    int32_t* new_active = (int32_t*)aligned_alloc(32, new_capacity * sizeof(int32_t));

    if (!new_prices || !new_sides || !new_types || !new_active) {
        free(new_prices);
        free(new_sides);
        free(new_types);
        free(new_active);
        return -1;
    }

    /* Copy existing data */
    size_t copy_count = (new_capacity < data->capacity) ? new_capacity : data->capacity;
    memcpy(new_prices, data->price_ticks, copy_count * sizeof(int64_t));
    memcpy(new_sides, data->sides, copy_count * sizeof(int64_t));
    memcpy(new_types, data->types, copy_count * sizeof(int64_t));
    memcpy(new_active, data->active, copy_count * sizeof(int32_t));

    /* Zero out new slots */
    if (new_capacity > data->capacity) {
        memset(new_prices + data->capacity, 0, (new_capacity - data->capacity) * sizeof(int64_t));
        memset(new_sides + data->capacity, 0, (new_capacity - data->capacity) * sizeof(int64_t));
        memset(new_types + data->capacity, 0, (new_capacity - data->capacity) * sizeof(int64_t));
        memset(new_active + data->capacity, 0, (new_capacity - data->capacity) * sizeof(int32_t));
    }

    /* Free old and assign new */
    free(data->price_ticks);
    free(data->sides);
    free(data->types);
    free(data->active);

    data->price_ticks = new_prices;
    data->sides = new_sides;
    data->types = new_types;
    data->active = new_active;
    data->capacity = new_capacity;

    return 0;
}
#endif /* __AVX2__ */

/*
 * Internal engine state - organized for cache efficiency
 */
struct engine_handle_s {
    /* Hot data - frequently accessed during tick processing (first cache line) */
    int64_t current_ts_ms;
    int64_t last_tick_price;
    int64_t position;         /* Positive = long, negative = short */
    double cash;
    double avg_entry_price;   /* Average entry price in ticks */
    double realized_pnl;
    int order_count;
    int inactive_order_count; /* Track inactive orders for lazy compaction */

    /* Configuration - less frequently modified (second cache line) */
    config_t config ALIGNED(CACHE_LINE_SIZE);

    /* Dynamic order storage using memory pool */
    mempool_t order_pool;
    tracked_order_t** orders; /* Array of pointers to orders in the pool */
    size_t max_orders;        /* Maximum capacity */

#ifdef __AVX2__
    /* SIMD-friendly order data for vectorized matching */
    simd_order_data_t simd_data;
    int simd_enabled;
#endif
};

/* Helper function to calculate unrealized PnL */
static ALWAYS_INLINE double calculate_unrealized_pnl(const engine_handle_t* RESTRICT h) {
    if (LIKELY(h->position == 0)) {
        return 0.0;
    }

    /* Position is scaled by 1,000,000 from Rust side - descale for calculations */
    double position_descaled = (double)h->position / 1000000.0;
    double position_value = position_descaled * (double)h->last_tick_price * h->config.tick_size;
    double entry_value = position_descaled * h->avg_entry_price * h->config.tick_size;

    return position_value - entry_value;
}

/* Helper function to apply fees */
static ALWAYS_INLINE double calculate_fee(const engine_handle_t* RESTRICT h, double notional, int is_maker) {
    double fee_bps = is_maker ? h->config.maker_fee_bps : h->config.taker_fee_bps;
    return notional * (fee_bps / 10000.0);
}

/* Helper function to get effective price after spread */
static ALWAYS_INLINE int64_t apply_spread(const engine_handle_t* RESTRICT h, int64_t price_tick, side_t side) {
    /* Spread widens the market: buyers pay more, sellers receive less */
    double spread_multiplier = h->config.spread_bps / 10000.0;
    double spread_ticks = (double)price_tick * spread_multiplier;

    if (side == SIDE_BUY) {
        /* Buying: pay more (round up) */
        return price_tick + (int64_t)ceil(spread_ticks);
    } else {
        /* Selling: receive less (round down) */
        return price_tick - (int64_t)ceil(spread_ticks);
    }
}

/* Helper function to execute a fill */
static int execute_fill(engine_handle_t* RESTRICT h, order_t* RESTRICT order, int64_t fill_price_tick) {
    int64_t fill_qty = order->qty;
    double fill_price = (double)fill_price_tick * h->config.tick_size;
    /* Quantity is scaled by 1,000,000 from Rust side - descale for notional calculation */
    double notional = fill_price * ((double)fill_qty / 1000000.0);

    /* Calculate fee (assuming taker fee for simplicity) */
    double fee = calculate_fee(h, notional, 0);

    /* Update position and PnL */
    int64_t old_position = h->position;
    int64_t new_position = old_position;

    if (order->side == SIDE_BUY) {
        new_position += fill_qty;
        h->cash -= (notional + fee);
    } else {
        new_position -= fill_qty;
        h->cash += (notional - fee);
    }

    /* Update realized PnL and average entry price */
    if (old_position == 0) {
        /* Opening new position */
        h->avg_entry_price = (double)fill_price_tick;
    } else if ((old_position > 0 && order->side == SIDE_BUY) ||
               (old_position < 0 && order->side == SIDE_SELL)) {
        /* Adding to position - update average entry price */
        /* Positions are already scaled, so we work directly with them for weighted average */
        double old_value = (double)old_position * h->avg_entry_price;
        double new_value = (double)fill_qty * (double)fill_price_tick;
        h->avg_entry_price = (old_value + new_value) / (double)new_position;
    } else {
        /* Reducing or flipping position - realize PnL */
        int64_t qty_reducing = (llabs(old_position) >= fill_qty) ? fill_qty : llabs(old_position);

        /* qty_reducing is scaled by 1,000,000 - descale for PnL calculations */
        double qty_reducing_descaled = (double)qty_reducing / 1000000.0;
        double exit_value = qty_reducing_descaled * (double)fill_price_tick * h->config.tick_size;
        double entry_value = qty_reducing_descaled * h->avg_entry_price * h->config.tick_size;

        if (old_position > 0) {
            /* Closing long position */
            h->realized_pnl += (exit_value - entry_value);
        } else {
            /* Closing short position */
            h->realized_pnl += (entry_value - exit_value);
        }

        /* If flipping position, set new average entry price */
        if (new_position != 0 && ((old_position > 0 && new_position < 0) ||
                                   (old_position < 0 && new_position > 0))) {
            h->avg_entry_price = (double)fill_price_tick;
        } else if (new_position == 0) {
            h->avg_entry_price = 0.0;
        }
    }

    h->position = new_position;
    return 0;
}

/* Helper function to check if an order should be filled at given tick (scalar version) */
static ALWAYS_INLINE int should_fill_order(const order_t* RESTRICT order, const tick_event_t* RESTRICT tick) {
    if (UNLIKELY(order->type == ORDER_TYPE_MARKET)) {
        return 1;  /* Market orders always fill */
    }

    /* Limit orders fill if price crosses */
    if (order->side == SIDE_BUY) {
        /* Buy limit fills if tick price <= limit price */
        return tick->price_tick <= order->price_tick;
    } else {
        /* Sell limit fills if tick price >= limit price */
        return tick->price_tick >= order->price_tick;
    }
}

#ifdef __AVX2__
/*
 * SIMD order matching using AVX2 intrinsics
 * Checks 4 orders in parallel and returns a bitmask of orders that should fill
 *
 * For each order, fill condition is:
 *   - Market order: always fill (type == 1)
 *   - Buy limit: tick_price <= order_price (side == 0)
 *   - Sell limit: tick_price >= order_price (side == 1)
 */
static ALWAYS_INLINE uint32_t check_orders_simd_avx2(
    const int64_t* RESTRICT prices,
    const int64_t* RESTRICT sides,
    const int64_t* RESTRICT types,
    const int32_t* RESTRICT active,
    int64_t tick_price,
    int count
) {
    uint32_t fill_mask = 0;

    /* Process 4 orders at a time using AVX2 (256-bit = 4x64-bit) */
    int i = 0;
    for (; i + SIMD_WIDTH <= count; i += SIMD_WIDTH) {
        /* Load 4 order prices */
        __m256i v_prices = _mm256_loadu_si256((const __m256i*)(prices + i));
        __m256i v_sides = _mm256_loadu_si256((const __m256i*)(sides + i));
        __m256i v_types = _mm256_loadu_si256((const __m256i*)(types + i));

        /* Load 4 active flags (32-bit, need to expand to 64-bit for comparison) */
        __m128i v_active_32 = _mm_loadu_si128((const __m128i*)(active + i));
        __m256i v_active = _mm256_cvtepi32_epi64(v_active_32);

        /* Broadcast tick price to all lanes */
        __m256i v_tick = _mm256_set1_epi64x(tick_price);

        /* Market orders always fill: type == 1 */
        __m256i v_one = _mm256_set1_epi64x(1);
        __m256i v_zero = _mm256_setzero_si256();
        __m256i is_market = _mm256_cmpeq_epi64(v_types, v_one);

        /* Buy limit fills if tick <= price (side == 0) */
        __m256i is_buy = _mm256_cmpeq_epi64(v_sides, v_zero);
        __m256i tick_le_price = _mm256_cmpgt_epi64(v_prices, v_tick); /* price > tick means tick <= price */
        __m256i tick_eq_price = _mm256_cmpeq_epi64(v_prices, v_tick);
        tick_le_price = _mm256_or_si256(tick_le_price, tick_eq_price);
        __m256i buy_fill = _mm256_and_si256(is_buy, tick_le_price);

        /* Sell limit fills if tick >= price (side == 1) */
        __m256i is_sell = _mm256_cmpeq_epi64(v_sides, v_one);
        __m256i tick_ge_price = _mm256_cmpgt_epi64(v_tick, v_prices); /* tick > price means tick >= price */
        tick_ge_price = _mm256_or_si256(tick_ge_price, tick_eq_price);
        __m256i sell_fill = _mm256_and_si256(is_sell, tick_ge_price);

        /* Combine: fill if (market OR buy_fill OR sell_fill) AND active */
        __m256i should_fill = _mm256_or_si256(is_market, _mm256_or_si256(buy_fill, sell_fill));
        __m256i is_active = _mm256_cmpgt_epi64(v_active, v_zero); /* active > 0 */
        __m256i final_fill = _mm256_and_si256(should_fill, is_active);

        /* Extract results: get the high bit of each 64-bit lane */
        /* _mm256_movemask_pd treats the input as doubles and extracts sign bits */
        int mask = _mm256_movemask_pd(_mm256_castsi256_pd(final_fill));
        fill_mask |= ((uint32_t)mask << i);
    }

    /* Handle remaining orders with scalar code */
    for (; i < count; i++) {
        if (!active[i]) continue;

        int should_fill_scalar = 0;
        if (types[i] == 1) {
            should_fill_scalar = 1; /* Market order */
        } else if (sides[i] == 0) {
            should_fill_scalar = (tick_price <= prices[i]); /* Buy limit */
        } else {
            should_fill_scalar = (tick_price >= prices[i]); /* Sell limit */
        }

        if (should_fill_scalar) {
            fill_mask |= (1u << i);
        }
    }

    return fill_mask;
}
#endif /* __AVX2__ */

/* Compact order list - only called when threshold is exceeded */
static void compact_orders(engine_handle_t* RESTRICT h) {
    int write_idx = 0;
    const int count = h->order_count;

    for (int read_idx = 0; read_idx < count; read_idx++) {
        if (h->orders[read_idx]->active) {
            if (write_idx != read_idx) {
                /* Swap pointers */
                tracked_order_t* temp = h->orders[write_idx];
                h->orders[write_idx] = h->orders[read_idx];
                h->orders[read_idx] = temp;

#ifdef __AVX2__
                if (h->simd_enabled) {
                    /* Update SIMD arrays */
                    h->simd_data.price_ticks[write_idx] = h->simd_data.price_ticks[read_idx];
                    h->simd_data.sides[write_idx] = h->simd_data.sides[read_idx];
                    h->simd_data.types[write_idx] = h->simd_data.types[read_idx];
                    h->simd_data.active[write_idx] = h->simd_data.active[read_idx];
                }
#endif
            }
            write_idx++;
        } else {
            /* Return inactive order to pool */
            mempool_free(&h->order_pool, h->orders[read_idx]);
        }
    }

    h->order_count = write_idx;
    h->inactive_order_count = 0;

#ifdef __AVX2__
    /* Zero out unused SIMD slots */
    if (h->simd_enabled) {
        for (int i = write_idx; i < count; i++) {
            h->simd_data.active[i] = 0;
        }
    }
#endif
}

/* Initialize order storage */
static int init_order_storage(engine_handle_t* h, size_t capacity) {
    /* Initialize memory pool */
    if (mempool_init(&h->order_pool, sizeof(tracked_order_t), capacity, 1) != 0) {
        return -1;
    }

    /* Allocate pointer array */
    h->orders = (tracked_order_t**)calloc(capacity, sizeof(tracked_order_t*));
    if (!h->orders) {
        mempool_destroy(&h->order_pool);
        return -1;
    }

    h->max_orders = capacity;

#ifdef __AVX2__
    /* Initialize SIMD data structures */
    if (simd_order_data_init(&h->simd_data, capacity) == 0) {
        h->simd_enabled = 1;
    } else {
        h->simd_enabled = 0;
    }
#endif

    return 0;
}

/* Cleanup order storage */
static void destroy_order_storage(engine_handle_t* h) {
    if (h->orders) {
        free(h->orders);
        h->orders = NULL;
    }
    mempool_destroy(&h->order_pool);

#ifdef __AVX2__
    if (h->simd_enabled) {
        simd_order_data_destroy(&h->simd_data);
        h->simd_enabled = 0;
    }
#endif
}

engine_handle_t* engine_new(config_t* cfg) {
    if (!cfg) {
        return NULL;
    }

    engine_handle_t* h = (engine_handle_t*)calloc(1, sizeof(engine_handle_t));
    if (!h) {
        return NULL;
    }

    h->config = *cfg;
    h->cash = cfg->initial_cash;
    h->current_ts_ms = 0;
    h->position = 0;
    h->avg_entry_price = 0.0;
    h->realized_pnl = 0.0;
    h->order_count = 0;
    h->inactive_order_count = 0;
    h->last_tick_price = 0;

    /* Initialize dynamic order storage */
    if (init_order_storage(h, ENGINE_DEFAULT_MAX_ORDERS) != 0) {
        free(h);
        return NULL;
    }

    return h;
}

void engine_free(engine_handle_t* h) {
    if (h) {
        destroy_order_storage(h);
        free(h);
    }
}

void engine_reset(engine_handle_t* h) {
    if (!h) {
        return;
    }

    config_t cfg = h->config;  /* Save config */
    size_t max_orders = h->max_orders;

    /* Reset pool and order array */
    mempool_reset(&h->order_pool);
    memset(h->orders, 0, max_orders * sizeof(tracked_order_t*));

#ifdef __AVX2__
    if (h->simd_enabled) {
        memset(h->simd_data.price_ticks, 0, max_orders * sizeof(int64_t));
        memset(h->simd_data.sides, 0, max_orders * sizeof(int64_t));
        memset(h->simd_data.types, 0, max_orders * sizeof(int64_t));
        memset(h->simd_data.active, 0, max_orders * sizeof(int32_t));
    }
#endif

    /* Reset state */
    h->config = cfg;
    h->cash = cfg.initial_cash;
    h->current_ts_ms = 0;
    h->position = 0;
    h->avg_entry_price = 0.0;
    h->realized_pnl = 0.0;
    h->order_count = 0;
    h->inactive_order_count = 0;
    h->last_tick_price = 0;
}

/* Process a single tick - maintains backwards compatibility */
HOT_FUNCTION
int engine_step_tick(engine_handle_t* h, tick_event_t* tick) {
    if (UNLIKELY(!h || !tick)) {
        return -1;
    }

    h->current_ts_ms = tick->ts_ms;
    h->last_tick_price = tick->price_tick;

    const int count = h->order_count;
    if (count == 0) {
        return 0;
    }

#ifdef __AVX2__
    if (h->simd_enabled && count >= SIMD_WIDTH) {
        /* Use SIMD path for order matching */
        uint32_t fill_mask = check_orders_simd_avx2(
            h->simd_data.price_ticks,
            h->simd_data.sides,
            h->simd_data.types,
            h->simd_data.active,
            tick->price_tick,
            count
        );

        /* Process fills */
        while (fill_mask) {
            int i = __builtin_ctz(fill_mask); /* Find first set bit */
            fill_mask &= ~(1u << i);          /* Clear that bit */

            tracked_order_t* tracked = h->orders[i];
            if (!tracked->active) continue;

            /* Determine fill price */
            int64_t fill_price_tick;
            if (tracked->order.type == ORDER_TYPE_MARKET) {
                fill_price_tick = apply_spread(h, tick->price_tick, tracked->order.side);
            } else {
                fill_price_tick = apply_spread(h, tracked->order.price_tick, tracked->order.side);
            }

            /* Execute the fill */
            execute_fill(h, &tracked->order, fill_price_tick);

            /* Mark order as inactive */
            tracked->active = 0;
            h->simd_data.active[i] = 0;
            h->inactive_order_count++;
        }
    } else
#endif
    {
        /* Scalar fallback path */
        for (int i = 0; i < count; i++) {
            if (!h->orders[i]->active) {
                continue;
            }

            if (should_fill_order(&h->orders[i]->order, tick)) {
                /* Determine fill price */
                int64_t fill_price_tick;
                if (h->orders[i]->order.type == ORDER_TYPE_MARKET) {
                    fill_price_tick = apply_spread(h, tick->price_tick, h->orders[i]->order.side);
                } else {
                    fill_price_tick = apply_spread(h, h->orders[i]->order.price_tick, h->orders[i]->order.side);
                }

                /* Execute the fill */
                execute_fill(h, &h->orders[i]->order, fill_price_tick);

                /* Mark order as inactive */
                h->orders[i]->active = 0;
#ifdef __AVX2__
                if (h->simd_enabled) {
                    h->simd_data.active[i] = 0;
                }
#endif
                h->inactive_order_count++;
            }
        }
    }

    /* Lazy compaction - only when threshold exceeded */
    if (UNLIKELY(h->inactive_order_count >= COMPACTION_THRESHOLD)) {
        compact_orders(h);
    }

    return 0;
}

/* Process a batch of ticks efficiently - single FFI call for N ticks */
HOT_FUNCTION
int engine_step_batch(engine_handle_t* RESTRICT h,
                      const tick_event_t* RESTRICT ticks,
                      int count) {
    if (UNLIKELY(!h || !ticks || count <= 0)) {
        return -1;
    }

    /* Process all ticks in the batch */
    for (int tick_idx = 0; tick_idx < count; tick_idx++) {
        const tick_event_t* RESTRICT tick = &ticks[tick_idx];

        h->current_ts_ms = tick->ts_ms;
        h->last_tick_price = tick->price_tick;

        const int order_count = h->order_count;
        if (order_count == 0) {
            continue;
        }

#ifdef __AVX2__
        if (h->simd_enabled && order_count >= SIMD_WIDTH) {
            /* Use SIMD path */
            uint32_t fill_mask = check_orders_simd_avx2(
                h->simd_data.price_ticks,
                h->simd_data.sides,
                h->simd_data.types,
                h->simd_data.active,
                tick->price_tick,
                order_count
            );

            while (fill_mask) {
                int i = __builtin_ctz(fill_mask);
                fill_mask &= ~(1u << i);

                tracked_order_t* tracked = h->orders[i];
                if (!tracked->active) continue;

                int64_t fill_price_tick;
                if (UNLIKELY(tracked->order.type == ORDER_TYPE_MARKET)) {
                    fill_price_tick = apply_spread(h, tick->price_tick, tracked->order.side);
                } else {
                    fill_price_tick = apply_spread(h, tracked->order.price_tick, tracked->order.side);
                }

                execute_fill(h, &tracked->order, fill_price_tick);
                tracked->active = 0;
                h->simd_data.active[i] = 0;
                h->inactive_order_count++;
            }
        } else
#endif
        {
            /* Scalar path */
            for (int i = 0; i < order_count; i++) {
                if (!h->orders[i]->active) {
                    continue;
                }

                if (should_fill_order(&h->orders[i]->order, tick)) {
                    int64_t fill_price_tick;
                    if (UNLIKELY(h->orders[i]->order.type == ORDER_TYPE_MARKET)) {
                        fill_price_tick = apply_spread(h, tick->price_tick, h->orders[i]->order.side);
                    } else {
                        fill_price_tick = apply_spread(h, h->orders[i]->order.price_tick, h->orders[i]->order.side);
                    }

                    execute_fill(h, &h->orders[i]->order, fill_price_tick);
                    h->orders[i]->active = 0;
#ifdef __AVX2__
                    if (h->simd_enabled) {
                        h->simd_data.active[i] = 0;
                    }
#endif
                    h->inactive_order_count++;
                }
            }
        }
    }

    /* Single compaction at end of batch if needed */
    if (UNLIKELY(h->inactive_order_count >= COMPACTION_THRESHOLD)) {
        compact_orders(h);
    }

    return 0;
}

int engine_place_order(engine_handle_t* h, order_t* order) {
    if (UNLIKELY(!h || !order)) {
        return -1;
    }

    if (UNLIKELY((size_t)h->order_count >= h->max_orders)) {
        /* Try to grow the pool if allowed */
        if (!h->order_pool.allow_growth) {
            return -2;  /* Order book full */
        }

        size_t new_capacity = h->max_orders * 2;

        /* Resize pointer array */
        tracked_order_t** new_orders = (tracked_order_t**)realloc(
            h->orders, new_capacity * sizeof(tracked_order_t*)
        );
        if (!new_orders) {
            return -2;
        }
        h->orders = new_orders;

        /* Zero new slots */
        memset(h->orders + h->max_orders, 0,
               (new_capacity - h->max_orders) * sizeof(tracked_order_t*));

#ifdef __AVX2__
        if (h->simd_enabled) {
            if (simd_order_data_resize(&h->simd_data, new_capacity) != 0) {
                /* SIMD resize failed, disable SIMD */
                h->simd_enabled = 0;
            }
        }
#endif

        h->max_orders = new_capacity;
    }

    /* Allocate from pool */
    tracked_order_t* tracked = (tracked_order_t*)mempool_alloc(&h->order_pool);
    if (!tracked) {
        return -2;  /* Pool exhausted */
    }

    /* Initialize order */
    tracked->order = *order;
    tracked->active = 1;

    /* Add to tracking array */
    int idx = h->order_count;
    h->orders[idx] = tracked;

#ifdef __AVX2__
    if (h->simd_enabled) {
        h->simd_data.price_ticks[idx] = order->price_tick;
        h->simd_data.sides[idx] = (int64_t)order->side;
        h->simd_data.types[idx] = (int64_t)order->type;
        h->simd_data.active[idx] = 1;
    }
#endif

    h->order_count++;
    return 0;
}

int engine_cancel_order(engine_handle_t* h, uint64_t order_id) {
    if (UNLIKELY(!h)) {
        return -1;
    }

    /* Find and cancel the order */
    const int count = h->order_count;
    for (int i = 0; i < count; i++) {
        if (h->orders[i]->active && h->orders[i]->order.order_id == order_id) {
            h->orders[i]->active = 0;
#ifdef __AVX2__
            if (h->simd_enabled) {
                h->simd_data.active[i] = 0;
            }
#endif
            h->inactive_order_count++;
            return 0;
        }
    }

    return -1;  /* Order not found */
}

snapshot_t engine_get_snapshot(engine_handle_t* h) {
    snapshot_t snap;
    memset(&snap, 0, sizeof(snapshot_t));

    if (UNLIKELY(!h)) {
        return snap;
    }

    snap.ts_ms = h->current_ts_ms;
    snap.cash = h->cash;
    snap.position = h->position;
    snap.avg_entry_price = h->avg_entry_price;
    snap.realized_pnl = h->realized_pnl;
    snap.unrealized_pnl = calculate_unrealized_pnl(h);
    snap.equity = snap.cash + snap.unrealized_pnl;

    return snap;
}

int engine_set_max_orders(engine_handle_t* h, size_t count) {
    if (!h) {
        return -1;
    }

    if (count == 0) {
        count = ENGINE_DEFAULT_MAX_ORDERS;
    }

    /* Cannot shrink below current order count */
    if (count < (size_t)h->order_count) {
        return -1;
    }

    /* Already at requested size */
    if (count == h->max_orders) {
        return 0;
    }

    /* Resize pointer array */
    tracked_order_t** new_orders = (tracked_order_t**)realloc(
        h->orders, count * sizeof(tracked_order_t*)
    );
    if (!new_orders) {
        return -2;
    }
    h->orders = new_orders;

    if (count > h->max_orders) {
        /* Zero new slots */
        memset(h->orders + h->max_orders, 0,
               (count - h->max_orders) * sizeof(tracked_order_t*));
    }

    /* Resize memory pool */
    if (mempool_resize(&h->order_pool, count) != 0) {
        return -2;
    }

#ifdef __AVX2__
    if (h->simd_enabled) {
        if (simd_order_data_resize(&h->simd_data, count) != 0) {
            /* SIMD resize failed, disable SIMD */
            h->simd_enabled = 0;
        }
    }
#endif

    h->max_orders = count;
    return 0;
}

size_t engine_get_max_orders(engine_handle_t* h) {
    return h ? h->max_orders : 0;
}

size_t engine_get_active_order_count(engine_handle_t* h) {
    if (!h) return 0;

    size_t active = 0;
    for (int i = 0; i < h->order_count; i++) {
        if (h->orders[i]->active) {
            active++;
        }
    }
    return active;
}
