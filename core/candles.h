/**
 * High-Performance OHLCV Candle Aggregation Module
 *
 * Features:
 * - SIMD-friendly data layout
 * - Single-pass O(n) aggregation
 * - Zero allocations in hot path
 * - Batch and streaming modes
 * - Gap handling for missing candles
 * - Multi-timeframe aggregation
 *
 * Target: >500M ticks/sec for batch aggregation
 */

#ifndef AG_KERNEL_CANDLES_H
#define AG_KERNEL_CANDLES_H

#include <stdint.h>
#include <stddef.h>
#include "types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Error codes */
#define CANDLE_OK             0
#define CANDLE_ERR_PARAM     -1
#define CANDLE_ERR_NOMEM     -2
#define CANDLE_ERR_EMPTY     -3

/* ---------------------------------------------------------------------
 * OHLCV Candle Structure (72 bytes)
 *
 * Layout optimized for:
 * - Sequential memory access patterns
 * - SIMD vectorization of price comparisons (contiguous int64_t prices)
 * - Minimal cache misses
 *
 * Note: Not cache-line aligned to avoid wasted padding, but prices
 * are grouped together for potential SIMD operations.
 * --------------------------------------------------------------------- */
typedef struct {
    int64_t ts_ms;           /* 8B: Candle open timestamp (ms) - boundary aligned */
    int64_t open_tick;       /* 8B: Open price in ticks */
    int64_t high_tick;       /* 8B: High price in ticks */
    int64_t low_tick;        /* 8B: Low price in ticks */
    int64_t close_tick;      /* 8B: Close price in ticks */
    double volume;           /* 8B: Total volume */
    double buy_volume;       /* 8B: Buy-side volume */
    double sell_volume;      /* 8B: Sell-side volume */
    uint64_t trade_count;    /* 8B: Number of trades */
    /* Total: 72 bytes */
} candle_t;

/**
 * Opaque handle for streaming candle aggregator
 */
typedef struct candle_aggregator_s candle_aggregator_t;

/* ---------------------------------------------------------------------
 * Batch Aggregation API (SoA - Structure of Arrays)
 *
 * Uses separate arrays for each field for better cache utilization
 * and SIMD vectorization potential.
 * --------------------------------------------------------------------- */

/**
 * Aggregate tick data into candles at specified interval.
 * Uses Structure-of-Arrays input for optimal memory access.
 *
 * @param timestamps   Array of tick timestamps (ms), sorted ascending
 * @param price_ticks  Array of prices in ticks
 * @param qtys         Array of quantities (double for fractional)
 * @param sides        Array of sides (0=buy, 1=sell)
 * @param count        Number of ticks
 * @param interval_ms  Candle interval in milliseconds (e.g., 60000 for 1min)
 * @param candles_out  Output buffer for candles (pre-allocated)
 * @param max_candles  Maximum candles that fit in output buffer
 * @return Number of candles created, or negative error code
 *
 * Notes:
 *   - Input arrays MUST be sorted by timestamp ascending
 *   - Gaps create separate candles (no synthetic fills)
 *   - Zero allocations in hot path
 */
int64_t candles_aggregate(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    int64_t interval_ms,
    candle_t* candles_out,
    size_t max_candles
);

/**
 * Aggregate tick_event_t array into candles (AoS input).
 * Convenience wrapper for tick_event_t arrays.
 *
 * @param ticks        Array of tick events, sorted by ts_ms ascending
 * @param tick_count   Number of ticks
 * @param interval_ms  Candle interval in milliseconds
 * @param candles_out  Output buffer for candles (pre-allocated)
 * @param max_candles  Maximum candles that fit in output buffer
 * @return Number of candles created, or negative error code
 */
int64_t candles_aggregate_ticks(
    const tick_event_t* ticks,
    size_t tick_count,
    int64_t interval_ms,
    candle_t* candles_out,
    size_t max_candles
);

/**
 * Aggregate with gap filling.
 * Creates zero-volume candles for missing intervals.
 *
 * @param timestamps   Array of tick timestamps (ms)
 * @param price_ticks  Array of prices in ticks
 * @param qtys         Array of quantities
 * @param sides        Array of sides
 * @param count        Number of ticks
 * @param interval_ms  Candle interval
 * @param candles_out  Output buffer
 * @param max_candles  Maximum output candles
 * @param fill_gaps    If non-zero, fill gaps with synthetic candles
 * @return Number of candles created, or negative error code
 */
int64_t candles_aggregate_gapfill(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    int64_t interval_ms,
    candle_t* candles_out,
    size_t max_candles,
    int fill_gaps
);

/* ---------------------------------------------------------------------
 * Resampling API
 * --------------------------------------------------------------------- */

/**
 * Resample candles to a larger interval.
 * Output interval must be >= input interval.
 *
 * @param candles       Input candle array (sorted by ts_ms)
 * @param count         Number of input candles
 * @param input_ms      Input candle interval (ms)
 * @param output_ms     Output candle interval (ms)
 * @param candles_out   Output buffer for resampled candles
 * @param max_candles   Maximum candles that fit in output buffer
 * @return Number of candles created, or negative error code
 */
int64_t candles_resample(
    const candle_t* candles,
    size_t count,
    int64_t input_ms,
    int64_t output_ms,
    candle_t* candles_out,
    size_t max_candles
);

/* ---------------------------------------------------------------------
 * Streaming Aggregator API
 *
 * For real-time tick processing with maintained state.
 * --------------------------------------------------------------------- */

/**
 * Create a new streaming candle aggregator.
 *
 * @param interval_ms  Candle interval in milliseconds
 * @return New aggregator handle, or NULL on error
 */
candle_aggregator_t* candle_aggregator_new(int64_t interval_ms);

/**
 * Free a candle aggregator and its resources.
 *
 * @param agg  Aggregator handle (NULL-safe)
 */
void candle_aggregator_free(candle_aggregator_t* agg);

/**
 * Reset the aggregator state for a new session.
 *
 * @param agg  Aggregator handle
 */
void candle_aggregator_reset(candle_aggregator_t* agg);

/**
 * Process a single tick through the aggregator.
 *
 * @param agg         Aggregator handle
 * @param ts_ms       Tick timestamp (ms)
 * @param price_tick  Price in ticks
 * @param qty         Quantity
 * @param side        Side (0=buy, 1=sell)
 * @param candle_out  Output buffer for completed candle (if any)
 * @return 1 if candle completed and written to candle_out, 0 if not, negative on error
 */
int candle_aggregator_update(
    candle_aggregator_t* agg,
    int64_t ts_ms,
    int64_t price_tick,
    double qty,
    uint8_t side,
    candle_t* candle_out
);

/**
 * Process a tick_event_t through the aggregator.
 * Convenience wrapper for tick_event_t.
 *
 * @param agg         Aggregator handle
 * @param tick        Tick event
 * @param candle_out  Output buffer for completed candle
 * @return 1 if candle completed, 0 if not, negative on error
 */
int candle_aggregator_feed(
    candle_aggregator_t* agg,
    const tick_event_t* tick,
    candle_t* candle_out
);

/**
 * Flush the current incomplete candle.
 * Call at end of data to get the final partial candle.
 *
 * @param agg         Aggregator handle
 * @param candle_out  Output buffer for current candle
 * @return 1 if candle written, 0 if no data accumulated, negative on error
 */
int candle_aggregator_flush(candle_aggregator_t* agg, candle_t* candle_out);

/**
 * Get the current incomplete candle without flushing.
 *
 * @param agg         Aggregator handle
 * @param candle_out  Output buffer for current candle
 * @return 1 if candle written, 0 if no data accumulated, negative on error
 */
int candle_aggregator_peek(const candle_aggregator_t* agg, candle_t* candle_out);

/* ---------------------------------------------------------------------
 * Utility Functions - Inlined for Hot Path Performance
 * --------------------------------------------------------------------- */

/**
 * Calculate the candle boundary timestamp for a given timestamp.
 * Floor-divides timestamp to interval boundary.
 */
static inline int64_t candle_boundary(int64_t ts_ms, int64_t interval_ms) {
    return (ts_ms / interval_ms) * interval_ms;
}

/**
 * Check if two timestamps belong to the same candle interval.
 */
static inline int candle_same_interval(int64_t ts1, int64_t ts2, int64_t interval_ms) {
    return (ts1 / interval_ms) == (ts2 / interval_ms);
}

/**
 * Zero-initialize a candle structure.
 */
static inline void candle_zero(candle_t* c) {
    c->ts_ms = 0;
    c->open_tick = 0;
    c->high_tick = 0;
    c->low_tick = 0;
    c->close_tick = 0;
    c->volume = 0.0;
    c->buy_volume = 0.0;
    c->sell_volume = 0.0;
    c->trade_count = 0;
}

/**
 * Initialize a candle from a single tick.
 */
static inline void candle_init(
    candle_t* c,
    int64_t ts_ms,
    int64_t price_tick,
    double qty,
    uint8_t side,
    int64_t interval_ms
) {
    c->ts_ms = candle_boundary(ts_ms, interval_ms);
    c->open_tick = price_tick;
    c->high_tick = price_tick;
    c->low_tick = price_tick;
    c->close_tick = price_tick;
    c->volume = qty;
    c->buy_volume = (side == 0) ? qty : 0.0;
    c->sell_volume = (side == 1) ? qty : 0.0;
    c->trade_count = 1;
}

/**
 * Update a candle with a new tick (branchless high/low).
 */
static inline void candle_update(
    candle_t* c,
    int64_t price_tick,
    double qty,
    uint8_t side
) {
    /* Branchless min/max using conditional move */
    c->high_tick = (price_tick > c->high_tick) ? price_tick : c->high_tick;
    c->low_tick = (price_tick < c->low_tick) ? price_tick : c->low_tick;
    c->close_tick = price_tick;
    c->volume += qty;
    c->buy_volume += (side == 0) ? qty : 0.0;
    c->sell_volume += (side == 1) ? qty : 0.0;
    c->trade_count++;
}

/**
 * Merge source candle into destination (for resampling).
 */
static inline void candle_merge(candle_t* dst, const candle_t* src) {
    if (src->high_tick > dst->high_tick) dst->high_tick = src->high_tick;
    if (src->low_tick < dst->low_tick) dst->low_tick = src->low_tick;
    dst->close_tick = src->close_tick;
    dst->volume += src->volume;
    dst->buy_volume += src->buy_volume;
    dst->sell_volume += src->sell_volume;
    dst->trade_count += src->trade_count;
}

/**
 * Create a gap-fill candle (zero volume, OHLC = prev close).
 */
static inline void candle_init_gap(
    candle_t* c,
    int64_t ts_ms,
    int64_t prev_close
) {
    c->ts_ms = ts_ms;
    c->open_tick = prev_close;
    c->high_tick = prev_close;
    c->low_tick = prev_close;
    c->close_tick = prev_close;
    c->volume = 0.0;
    c->buy_volume = 0.0;
    c->sell_volume = 0.0;
    c->trade_count = 0;
}

/**
 * Check if candle has any trades.
 */
static inline int candle_is_valid(const candle_t* c) {
    return c->trade_count > 0;
}

#ifdef __cplusplus
}
#endif

#endif /* AG_KERNEL_CANDLES_H */
