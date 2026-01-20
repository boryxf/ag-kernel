/*
 * Fixed-Point Trading Engine Implementation
 *
 * This is an alternative implementation of the trading engine using
 * fixed-point arithmetic instead of double-precision floating-point.
 *
 * Benefits:
 * - Deterministic results across different architectures
 * - Potentially faster on architectures without FPU
 * - Exact representation of decimal values (no floating-point errors)
 *
 * Limitations:
 * - Range limited to ~92 billion with 8 decimal places
 * - Requires 128-bit intermediate calculations for multiplication
 *
 * Usage: This is OPTIONAL. The double-precision engine (engine.c) remains
 * the default and continues to work unchanged.
 */

#include "engine.h"
#include "fixed_point.h"
#include "mempool.h"
#include <stdlib.h>
#include <string.h>

/* Lazy compaction threshold */
#define COMPACTION_THRESHOLD 10

/*
 * SCALING CONVENTION (same as double-precision engine):
 * - Quantities (order->qty, position) are scaled by 1,000,000 from Rust side
 * - When doing financial calculations (notional, PnL), must divide by 1,000,000
 * - Price ticks and tick_size remain as specified
 *
 * In fixed-point, we represent the quantity scale as a fixed-point divisor:
 * QTY_SCALE_FIXED = 1,000,000 represented in fixed-point = 1,000,000 * FIXED_SCALE
 */
#define QTY_SCALE 1000000LL
#define QTY_SCALE_FIXED (QTY_SCALE * FIXED_SCALE)

/* Compiler hints */
#if defined(__GNUC__) || defined(__clang__)
    #define LIKELY(x)   __builtin_expect(!!(x), 1)
    #define UNLIKELY(x) __builtin_expect(!!(x), 0)
    #define RESTRICT    __restrict__
#else
    #define LIKELY(x)   (x)
    #define UNLIKELY(x) (x)
    #define RESTRICT
#endif

/* Internal order tracking (same structure as double engine) */
typedef struct {
    order_t order;
    int active;  /* 1 if order is active, 0 if cancelled */
} tracked_order_fixed_t;

/* Internal engine state - fixed-point version */
struct engine_fixed_handle_s {
    config_t config;              /* Original config (kept as double for API compat) */

    /* Converted config values for fixed-point calculations */
    fixed64_t tick_size_fixed;    /* tick_size as fixed-point */
    fixed64_t maker_fee_bps;      /* maker fee in bps (integer, not fixed) */
    fixed64_t taker_fee_bps;      /* taker fee in bps (integer, not fixed) */
    fixed64_t spread_bps;         /* spread in bps (integer, not fixed) */

    /* Current state */
    int64_t current_ts_ms;
    fixed64_t cash;               /* Cash balance in fixed-point */
    int64_t position;             /* Position (scaled by 1,000,000 from Rust) */
    fixed64_t avg_entry_price;    /* Average entry price in ticks (fixed-point) */
    fixed64_t realized_pnl;       /* Realized PnL in fixed-point */

    /* Dynamic order storage using memory pool */
    mempool_t order_pool;
    tracked_order_fixed_t** orders; /* Array of pointers to orders in the pool */
    size_t max_orders;              /* Maximum capacity */
    int order_count;
    int inactive_order_count;       /* Track inactive orders for lazy compaction */

    /* Last tick price for unrealized PnL calculation */
    int64_t last_tick_price;
};

/* ---------------------------------------------------------------------
 * Helper functions
 * --------------------------------------------------------------------- */

/*
 * Calculate unrealized PnL
 *
 * unrealized_pnl = (last_price - avg_entry) * position * tick_size
 * where position is scaled by 1,000,000
 */
static fixed64_t calculate_unrealized_pnl_fixed(engine_fixed_handle_t* h) {
    if (h->position == 0) {
        return FIXED_ZERO;
    }

    /* Convert last_tick_price to fixed-point */
    fixed64_t last_price_fixed = INT_TO_FIXED(h->last_tick_price);

    /* Price difference in ticks (fixed-point) */
    fixed64_t price_diff = fixed_sub(last_price_fixed, h->avg_entry_price);

    /* Position value = price_diff * position / QTY_SCALE * tick_size */
    /* Reorder to avoid overflow: price_diff * tick_size * position / QTY_SCALE */

    /* Step 1: price_diff * tick_size (both fixed, use fixed_mul) */
    fixed64_t price_value = fixed_mul(price_diff, h->tick_size_fixed);

    /* Step 2: multiply by position (integer) */
    fixed64_t position_value = fixed_mul_int(price_value, h->position);

    /* Step 3: divide by quantity scale */
    fixed64_t unrealized = fixed_div_int(position_value, QTY_SCALE);

    return unrealized;
}

/*
 * Calculate fee on a notional amount
 *
 * fee = notional * fee_bps / 10000
 */
static fixed64_t calculate_fee_fixed(engine_fixed_handle_t* h, fixed64_t notional, int is_maker) {
    int64_t fee_bps = is_maker ? (int64_t)h->maker_fee_bps : (int64_t)h->taker_fee_bps;
    return fixed_apply_bps(notional, fee_bps);
}

/*
 * Apply spread to price
 *
 * Spread widens the market: buyers pay more, sellers receive less
 * spread_adjustment = price * spread_bps / 10000
 */
static int64_t apply_spread_fixed(engine_fixed_handle_t* h, int64_t price_tick, side_t side) {
    if (h->spread_bps == 0) {
        return price_tick;
    }

    /* Calculate spread in ticks: price_tick * spread_bps / 10000 */
    /* Use 128-bit to avoid overflow */
    __int128 spread_calc = (__int128)price_tick * (int64_t)h->spread_bps;
    int64_t spread_ticks = (int64_t)((spread_calc + 9999) / 10000);  /* Ceiling */

    if (side == SIDE_BUY) {
        /* Buying: pay more */
        return price_tick + spread_ticks;
    } else {
        /* Selling: receive less */
        return price_tick - spread_ticks;
    }
}

/*
 * Execute a fill
 *
 * Updates cash, position, average entry price, and realized PnL
 */
static int execute_fill_fixed(engine_fixed_handle_t* h, order_t* order, int64_t fill_price_tick) {
    int64_t fill_qty = order->qty;

    /* Calculate fill price in currency units (fixed-point) */
    /* fill_price = fill_price_tick * tick_size */
    fixed64_t fill_price_fixed = tick_to_fixed(fill_price_tick, h->tick_size_fixed);

    /* Calculate notional value (fixed-point) */
    /* notional = fill_price * fill_qty / QTY_SCALE */
    fixed64_t notional = fixed_mul_int(fill_price_fixed, fill_qty);
    notional = fixed_div_int(notional, QTY_SCALE);

    /* Calculate fee (assuming taker fee for simplicity) */
    fixed64_t fee = calculate_fee_fixed(h, notional, 0);

    /* Track old position for PnL calculation */
    int64_t old_position = h->position;
    int64_t new_position = old_position;

    /* Update position and cash based on trade direction */
    if (order->side == SIDE_BUY) {
        new_position += fill_qty;
        h->cash = fixed_sub(h->cash, fixed_add(notional, fee));
    } else {
        new_position -= fill_qty;
        h->cash = fixed_add(h->cash, fixed_sub(notional, fee));
    }

    /* Update realized PnL and average entry price */
    if (old_position == 0) {
        /* Opening new position */
        h->avg_entry_price = INT_TO_FIXED(fill_price_tick);
    } else if ((old_position > 0 && order->side == SIDE_BUY) ||
               (old_position < 0 && order->side == SIDE_SELL)) {
        /* Adding to position - update average entry price */
        /* avg = (old_pos * old_avg + fill_qty * fill_price) / new_pos */
        fixed64_t old_value = fixed_mul_int(h->avg_entry_price, old_position);
        fixed64_t new_value = fixed_mul_int(INT_TO_FIXED(fill_price_tick), fill_qty);
        fixed64_t total_value = fixed_add(old_value, new_value);
        h->avg_entry_price = fixed_div_int(total_value, new_position);
    } else {
        /* Reducing or flipping position - realize PnL */
        int64_t abs_old = (old_position >= 0) ? old_position : -old_position;
        int64_t qty_reducing = (abs_old >= fill_qty) ? fill_qty : abs_old;

        /* Calculate entry and exit values for the reducing portion */
        /* exit_value = qty_reducing * fill_price_tick * tick_size / QTY_SCALE */
        fixed64_t exit_value = tick_to_fixed(fill_price_tick, h->tick_size_fixed);
        exit_value = fixed_mul_int(exit_value, qty_reducing);
        exit_value = fixed_div_int(exit_value, QTY_SCALE);

        /* entry_value = qty_reducing * avg_entry_price * tick_size / QTY_SCALE */
        fixed64_t entry_value = fixed_mul(h->avg_entry_price, h->tick_size_fixed);
        entry_value = fixed_mul_int(entry_value, qty_reducing);
        entry_value = fixed_div_int(entry_value, QTY_SCALE);

        if (old_position > 0) {
            /* Closing long position: profit = exit - entry */
            h->realized_pnl = fixed_add(h->realized_pnl, fixed_sub(exit_value, entry_value));
        } else {
            /* Closing short position: profit = entry - exit */
            h->realized_pnl = fixed_add(h->realized_pnl, fixed_sub(entry_value, exit_value));
        }

        /* If flipping position, set new average entry price */
        if (new_position != 0 && ((old_position > 0 && new_position < 0) ||
                                   (old_position < 0 && new_position > 0))) {
            h->avg_entry_price = INT_TO_FIXED(fill_price_tick);
        } else if (new_position == 0) {
            h->avg_entry_price = FIXED_ZERO;
        }
    }

    h->position = new_position;
    return 0;
}

/*
 * Check if an order should be filled at given tick
 */
static int should_fill_order_fixed(order_t* order, tick_event_t* tick) {
    if (order->type == ORDER_TYPE_MARKET) {
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

/*
 * Compact order list - remove inactive orders
 */
static void compact_orders_fixed(engine_fixed_handle_t* RESTRICT h) {
    int write_idx = 0;
    const int count = h->order_count;

    for (int read_idx = 0; read_idx < count; read_idx++) {
        if (h->orders[read_idx]->active) {
            if (write_idx != read_idx) {
                /* Swap pointers */
                tracked_order_fixed_t* temp = h->orders[write_idx];
                h->orders[write_idx] = h->orders[read_idx];
                h->orders[read_idx] = temp;
            }
            write_idx++;
        } else {
            /* Return inactive order to pool */
            mempool_free(&h->order_pool, h->orders[read_idx]);
        }
    }

    h->order_count = write_idx;
    h->inactive_order_count = 0;
}

/*
 * Initialize order storage
 */
static int init_order_storage_fixed(engine_fixed_handle_t* h, size_t capacity) {
    /* Initialize memory pool */
    if (mempool_init(&h->order_pool, sizeof(tracked_order_fixed_t), capacity, 1) != 0) {
        return -1;
    }

    /* Allocate pointer array */
    h->orders = (tracked_order_fixed_t**)calloc(capacity, sizeof(tracked_order_fixed_t*));
    if (!h->orders) {
        mempool_destroy(&h->order_pool);
        return -1;
    }

    h->max_orders = capacity;
    return 0;
}

/*
 * Cleanup order storage
 */
static void destroy_order_storage_fixed(engine_fixed_handle_t* h) {
    if (h->orders) {
        free(h->orders);
        h->orders = NULL;
    }
    mempool_destroy(&h->order_pool);
}

/* ---------------------------------------------------------------------
 * Public API - Fixed-point engine
 * --------------------------------------------------------------------- */

engine_fixed_handle_t* engine_fixed_new(config_t* cfg) {
    if (!cfg) {
        return NULL;
    }

    engine_fixed_handle_t* h = (engine_fixed_handle_t*)calloc(1, sizeof(engine_fixed_handle_t));
    if (!h) {
        return NULL;
    }

    /* Store original config for API compatibility */
    h->config = *cfg;

    /* Convert config to fixed-point */
    h->tick_size_fixed = DOUBLE_TO_FIXED(cfg->tick_size);
    h->maker_fee_bps = (fixed64_t)(cfg->maker_fee_bps);  /* Store as integer bps */
    h->taker_fee_bps = (fixed64_t)(cfg->taker_fee_bps);
    h->spread_bps = (fixed64_t)(cfg->spread_bps);

    /* Initialize state */
    h->cash = DOUBLE_TO_FIXED(cfg->initial_cash);
    h->current_ts_ms = 0;
    h->position = 0;
    h->avg_entry_price = FIXED_ZERO;
    h->realized_pnl = FIXED_ZERO;
    h->order_count = 0;
    h->inactive_order_count = 0;
    h->last_tick_price = 0;

    /* Initialize dynamic order storage */
    if (init_order_storage_fixed(h, ENGINE_DEFAULT_MAX_ORDERS) != 0) {
        free(h);
        return NULL;
    }

    return h;
}

void engine_fixed_free(engine_fixed_handle_t* h) {
    if (h) {
        destroy_order_storage_fixed(h);
        free(h);
    }
}

void engine_fixed_reset(engine_fixed_handle_t* h) {
    if (!h) {
        return;
    }

    config_t cfg = h->config;  /* Save config */
    size_t max_orders = h->max_orders;

    /* Reset pool and order array */
    mempool_reset(&h->order_pool);
    memset(h->orders, 0, max_orders * sizeof(tracked_order_fixed_t*));

    /* Re-initialize state */
    h->cash = DOUBLE_TO_FIXED(cfg.initial_cash);
    h->current_ts_ms = 0;
    h->position = 0;
    h->avg_entry_price = FIXED_ZERO;
    h->realized_pnl = FIXED_ZERO;
    h->order_count = 0;
    h->inactive_order_count = 0;
    h->last_tick_price = 0;
}

int engine_fixed_step_tick(engine_fixed_handle_t* h, tick_event_t* tick) {
    if (UNLIKELY(!h || !tick)) {
        return -1;
    }

    h->current_ts_ms = tick->ts_ms;
    h->last_tick_price = tick->price_tick;

    /* Check all open orders for fills */
    for (int i = 0; i < h->order_count; i++) {
        if (!h->orders[i]->active) {
            continue;
        }

        if (should_fill_order_fixed(&h->orders[i]->order, tick)) {
            /* Determine fill price */
            int64_t fill_price_tick;
            if (h->orders[i]->order.type == ORDER_TYPE_MARKET) {
                /* Market orders fill at tick price with spread */
                fill_price_tick = apply_spread_fixed(h, tick->price_tick, h->orders[i]->order.side);
            } else {
                /* Limit orders fill at limit price with spread */
                fill_price_tick = apply_spread_fixed(h, h->orders[i]->order.price_tick, h->orders[i]->order.side);
            }

            /* Execute the fill */
            execute_fill_fixed(h, &h->orders[i]->order, fill_price_tick);

            /* Mark order as inactive */
            h->orders[i]->active = 0;
            h->inactive_order_count++;
        }
    }

    /* Lazy compaction */
    if (UNLIKELY(h->inactive_order_count >= COMPACTION_THRESHOLD)) {
        compact_orders_fixed(h);
    }

    return 0;
}

int engine_fixed_step_batch(engine_fixed_handle_t* h, tick_event_t* ticks, int count) {
    if (UNLIKELY(!h || !ticks || count <= 0)) {
        return -1;
    }

    for (int i = 0; i < count; i++) {
        int result = engine_fixed_step_tick(h, &ticks[i]);
        if (result != 0) {
            return result;
        }
    }

    return 0;
}

int engine_fixed_place_order(engine_fixed_handle_t* h, order_t* order) {
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
        tracked_order_fixed_t** new_orders = (tracked_order_fixed_t**)realloc(
            h->orders, new_capacity * sizeof(tracked_order_fixed_t*)
        );
        if (!new_orders) {
            return -2;
        }
        h->orders = new_orders;

        /* Zero new slots */
        memset(h->orders + h->max_orders, 0,
               (new_capacity - h->max_orders) * sizeof(tracked_order_fixed_t*));

        h->max_orders = new_capacity;
    }

    /* Allocate from pool */
    tracked_order_fixed_t* tracked = (tracked_order_fixed_t*)mempool_alloc(&h->order_pool);
    if (!tracked) {
        return -2;  /* Pool exhausted */
    }

    /* Add order to tracking */
    tracked->order = *order;
    tracked->active = 1;

    h->orders[h->order_count] = tracked;
    h->order_count++;

    return 0;
}

int engine_fixed_cancel_order(engine_fixed_handle_t* h, uint64_t order_id) {
    if (UNLIKELY(!h)) {
        return -1;
    }

    /* Find and cancel the order */
    for (int i = 0; i < h->order_count; i++) {
        if (h->orders[i]->active && h->orders[i]->order.order_id == order_id) {
            h->orders[i]->active = 0;
            h->inactive_order_count++;
            return 0;
        }
    }

    return -1;  /* Order not found */
}

snapshot_t engine_fixed_get_snapshot(engine_fixed_handle_t* h) {
    snapshot_t snap;
    memset(&snap, 0, sizeof(snapshot_t));

    if (UNLIKELY(!h)) {
        return snap;
    }

    /* Convert fixed-point values back to double for API compatibility */
    snap.ts_ms = h->current_ts_ms;
    snap.cash = FIXED_TO_DOUBLE(h->cash);
    snap.position = h->position;
    snap.avg_entry_price = FIXED_TO_DOUBLE(h->avg_entry_price);
    snap.realized_pnl = FIXED_TO_DOUBLE(h->realized_pnl);

    fixed64_t unrealized = calculate_unrealized_pnl_fixed(h);
    snap.unrealized_pnl = FIXED_TO_DOUBLE(unrealized);
    snap.equity = snap.cash + snap.unrealized_pnl;

    return snap;
}

int engine_fixed_set_max_orders(engine_fixed_handle_t* h, size_t count) {
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
    tracked_order_fixed_t** new_orders = (tracked_order_fixed_t**)realloc(
        h->orders, count * sizeof(tracked_order_fixed_t*)
    );
    if (!new_orders) {
        return -2;
    }
    h->orders = new_orders;

    if (count > h->max_orders) {
        /* Zero new slots */
        memset(h->orders + h->max_orders, 0,
               (count - h->max_orders) * sizeof(tracked_order_fixed_t*));
    }

    /* Resize memory pool */
    if (mempool_resize(&h->order_pool, count) != 0) {
        return -2;
    }

    h->max_orders = count;
    return 0;
}

size_t engine_fixed_get_max_orders(engine_fixed_handle_t* h) {
    return h ? h->max_orders : 0;
}

size_t engine_fixed_get_active_order_count(engine_fixed_handle_t* h) {
    if (!h) return 0;

    size_t active = 0;
    for (int i = 0; i < h->order_count; i++) {
        if (h->orders[i]->active) {
            active++;
        }
    }
    return active;
}

/* ---------------------------------------------------------------------
 * Benchmark comparison (compile with -DFIXED_POINT_BENCHMARK)
 * --------------------------------------------------------------------- */

#ifdef FIXED_POINT_BENCHMARK

#include <stdio.h>
#include <time.h>

/*
 * Simple benchmark to compare double vs fixed-point performance
 *
 * Compile with: gcc -O3 -DFIXED_POINT_BENCHMARK engine.c engine_fixed.c -o benchmark
 */

#define BENCHMARK_ITERATIONS 1000000

static double get_time_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1000000.0;
}

void benchmark_fixed_point(void) {
    printf("Fixed-Point Arithmetic Benchmark\n");
    printf("================================\n\n");

    /* Benchmark multiplication */
    {
        double start, end;
        volatile double d_result = 0.0;
        volatile fixed64_t f_result = 0;

        /* Double multiplication */
        start = get_time_ms();
        for (int i = 0; i < BENCHMARK_ITERATIONS; i++) {
            double a = 12345.67890123;
            double b = 98765.43210987;
            d_result = a * b;
        }
        end = get_time_ms();
        printf("Double multiplication:     %.3f ms (%d iterations)\n",
               end - start, BENCHMARK_ITERATIONS);

        /* Fixed multiplication */
        start = get_time_ms();
        for (int i = 0; i < BENCHMARK_ITERATIONS; i++) {
            fixed64_t a = DOUBLE_TO_FIXED(12345.67890123);
            fixed64_t b = DOUBLE_TO_FIXED(98765.43210987);
            f_result = fixed_mul(a, b);
        }
        end = get_time_ms();
        printf("Fixed multiplication:      %.3f ms (%d iterations)\n",
               end - start, BENCHMARK_ITERATIONS);

        /* Verify accuracy */
        double expected = 12345.67890123 * 98765.43210987;
        fixed64_t f_expected = fixed_mul(DOUBLE_TO_FIXED(12345.67890123),
                                         DOUBLE_TO_FIXED(98765.43210987));
        printf("Double result: %.8f\n", expected);
        printf("Fixed result:  %.8f\n", FIXED_TO_DOUBLE(f_expected));
        printf("\n");
    }

    /* Benchmark division */
    {
        double start, end;
        volatile double d_result = 0.0;
        volatile fixed64_t f_result = 0;

        /* Double division */
        start = get_time_ms();
        for (int i = 0; i < BENCHMARK_ITERATIONS; i++) {
            double a = 98765.43210987;
            double b = 12345.67890123;
            d_result = a / b;
        }
        end = get_time_ms();
        printf("Double division:           %.3f ms (%d iterations)\n",
               end - start, BENCHMARK_ITERATIONS);

        /* Fixed division */
        start = get_time_ms();
        for (int i = 0; i < BENCHMARK_ITERATIONS; i++) {
            fixed64_t a = DOUBLE_TO_FIXED(98765.43210987);
            fixed64_t b = DOUBLE_TO_FIXED(12345.67890123);
            f_result = fixed_div(a, b);
        }
        end = get_time_ms();
        printf("Fixed division:            %.3f ms (%d iterations)\n",
               end - start, BENCHMARK_ITERATIONS);

        printf("\n");
    }

    /* Benchmark engine operations */
    {
        printf("Engine Operation Benchmark\n");
        printf("--------------------------\n");

        config_t cfg = {
            .maker_fee_bps = 1.0,
            .taker_fee_bps = 2.0,
            .spread_bps = 5.0,
            .initial_cash = 100000.0,
            .tick_size = 0.01
        };

        /* Double engine */
        engine_handle_t* h_double = engine_new(&cfg);
        double start = get_time_ms();

        for (int i = 0; i < BENCHMARK_ITERATIONS / 10; i++) {
            tick_event_t tick = {
                .ts_ms = i,
                .price_tick = 50000 + (i % 1000),
                .qty = 1000000,  /* 1.0 scaled */
                .side = (i % 2) ? SIDE_BUY : SIDE_SELL
            };
            engine_step_tick(h_double, &tick);

            if (i % 100 == 0) {
                order_t order = {
                    .order_id = i,
                    .type = ORDER_TYPE_MARKET,
                    .side = (i % 2) ? SIDE_BUY : SIDE_SELL,
                    .qty = 100000,  /* 0.1 scaled */
                    .price_tick = 0
                };
                engine_place_order(h_double, &order);
            }
        }

        double end = get_time_ms();
        printf("Double engine:             %.3f ms (%d ticks)\n",
               end - start, BENCHMARK_ITERATIONS / 10);
        engine_free(h_double);

        /* Fixed engine */
        engine_fixed_handle_t* h_fixed = engine_fixed_new(&cfg);
        start = get_time_ms();

        for (int i = 0; i < BENCHMARK_ITERATIONS / 10; i++) {
            tick_event_t tick = {
                .ts_ms = i,
                .price_tick = 50000 + (i % 1000),
                .qty = 1000000,
                .side = (i % 2) ? SIDE_BUY : SIDE_SELL
            };
            engine_fixed_step_tick(h_fixed, &tick);

            if (i % 100 == 0) {
                order_t order = {
                    .order_id = i,
                    .type = ORDER_TYPE_MARKET,
                    .side = (i % 2) ? SIDE_BUY : SIDE_SELL,
                    .qty = 100000,
                    .price_tick = 0
                };
                engine_fixed_place_order(h_fixed, &order);
            }
        }

        end = get_time_ms();
        printf("Fixed engine:              %.3f ms (%d ticks)\n",
               end - start, BENCHMARK_ITERATIONS / 10);

        /* Compare final state */
        snapshot_t snap = engine_fixed_get_snapshot(h_fixed);
        printf("\nFinal fixed engine state:\n");
        printf("  Cash: %.8f\n", snap.cash);
        printf("  Position: %lld\n", (long long)snap.position);
        printf("  Realized PnL: %.8f\n", snap.realized_pnl);

        engine_fixed_free(h_fixed);
    }

    printf("\nBenchmark complete.\n");
}

/* Entry point for benchmark mode */
#ifndef BENCHMARK_AS_LIBRARY
int main(void) {
    benchmark_fixed_point();
    return 0;
}
#endif

#endif /* FIXED_POINT_BENCHMARK */
