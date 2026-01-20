/**
 * High-Performance OHLCV Candle Aggregation Implementation
 *
 * Optimizations:
 * - Single-pass O(n) aggregation
 * - Branchless operations where possible
 * - Prefetching for sequential access
 * - Zero allocations in hot path
 * - SIMD-friendly memory layout
 * - Separate SoA and AoS APIs for flexibility
 *
 * Target: >500M ticks/sec for batch aggregation
 */

#include "candles.h"
#include <stdlib.h>
#include <string.h>

/* Prefetch distance - tuned for typical L1/L2 cache */
#define PREFETCH_DISTANCE 8

/* Compiler hints for branch prediction */
#ifdef __GNUC__
    #define LIKELY(x)   __builtin_expect(!!(x), 1)
    #define UNLIKELY(x) __builtin_expect(!!(x), 0)
    #define PREFETCH_READ(addr)  __builtin_prefetch((addr), 0, 1)
#else
    #define LIKELY(x)   (x)
    #define UNLIKELY(x) (x)
    #define PREFETCH_READ(addr)  ((void)0)
#endif

/* Force inline and hot function hints */
#ifdef __GNUC__
    #define HOT_FUNCTION __attribute__((hot))
#else
    #define HOT_FUNCTION
#endif

/* ---------------------------------------------------------------------
 * Streaming Aggregator Internal Structure
 * --------------------------------------------------------------------- */

struct candle_aggregator_s {
    int64_t interval_ms;          /* Candle interval in milliseconds */
    int64_t current_period_start; /* Start of current period */
    candle_t current;             /* Current (incomplete) candle */
    int has_data;                 /* 1 if current candle has data */
};

/* ---------------------------------------------------------------------
 * Batch Aggregation - Structure of Arrays (SoA)
 *
 * This is the highest-performance path for batch processing.
 * Uses separate arrays for timestamps, prices, volumes, and sides
 * to maximize cache utilization and enable potential SIMD.
 * --------------------------------------------------------------------- */

HOT_FUNCTION
int64_t candles_aggregate(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    int64_t interval_ms,
    candle_t* candles_out,
    size_t max_candles
) {
    /* Parameter validation */
    if (UNLIKELY(!timestamps || !price_ticks || !qtys || !sides || !candles_out)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(interval_ms <= 0 || max_candles == 0)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(count == 0)) {
        return 0;
    }

    size_t candle_idx = 0;
    int64_t current_period = timestamps[0] / interval_ms;

    /* Initialize first candle */
    candle_t current = {
        .ts_ms = current_period * interval_ms,
        .open_tick = price_ticks[0],
        .high_tick = price_ticks[0],
        .low_tick = price_ticks[0],
        .close_tick = price_ticks[0],
        .volume = 0.0,
        .buy_volume = 0.0,
        .sell_volume = 0.0,
        .trade_count = 0
    };

    /* Main aggregation loop - optimized for throughput */
    for (size_t i = 0; i < count; i++) {
        /* Prefetch upcoming data - multiple arrays */
        if (LIKELY(i + PREFETCH_DISTANCE < count)) {
            PREFETCH_READ(&timestamps[i + PREFETCH_DISTANCE]);
            PREFETCH_READ(&price_ticks[i + PREFETCH_DISTANCE]);
            PREFETCH_READ(&qtys[i + PREFETCH_DISTANCE]);
        }

        int64_t tick_period = timestamps[i] / interval_ms;

        if (tick_period != current_period) {
            /* New candle boundary - emit current and start fresh */
            if (UNLIKELY(candle_idx >= max_candles)) {
                return (int64_t)candle_idx;
            }
            candles_out[candle_idx++] = current;

            /* Start new candle */
            current_period = tick_period;
            current.ts_ms = current_period * interval_ms;
            current.open_tick = price_ticks[i];
            current.high_tick = price_ticks[i];
            current.low_tick = price_ticks[i];
            current.close_tick = price_ticks[i];
            current.volume = 0.0;
            current.buy_volume = 0.0;
            current.sell_volume = 0.0;
            current.trade_count = 0;
        }

        /* Update current candle - branchless high/low */
        int64_t price = price_ticks[i];
        current.high_tick = (price > current.high_tick) ? price : current.high_tick;
        current.low_tick = (price < current.low_tick) ? price : current.low_tick;
        current.close_tick = price;

        double qty = qtys[i];
        current.volume += qty;
        current.buy_volume += (sides[i] == 0) ? qty : 0.0;
        current.sell_volume += (sides[i] == 1) ? qty : 0.0;
        current.trade_count++;
    }

    /* Emit final candle */
    if (LIKELY(candle_idx < max_candles)) {
        candles_out[candle_idx++] = current;
    }

    return (int64_t)candle_idx;
}

/* ---------------------------------------------------------------------
 * Batch Aggregation - Array of Structures (AoS)
 *
 * Convenience wrapper for tick_event_t arrays.
 * --------------------------------------------------------------------- */

HOT_FUNCTION
int64_t candles_aggregate_ticks(
    const tick_event_t* ticks,
    size_t tick_count,
    int64_t interval_ms,
    candle_t* candles_out,
    size_t max_candles
) {
    /* Parameter validation */
    if (UNLIKELY(!ticks || !candles_out)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(interval_ms <= 0 || max_candles == 0)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(tick_count == 0)) {
        return 0;
    }

    size_t candle_idx = 0;
    int64_t current_period = ticks[0].ts_ms / interval_ms;

    /* Initialize first candle */
    candle_t current = {
        .ts_ms = current_period * interval_ms,
        .open_tick = ticks[0].price_tick,
        .high_tick = ticks[0].price_tick,
        .low_tick = ticks[0].price_tick,
        .close_tick = ticks[0].price_tick,
        .volume = 0.0,
        .buy_volume = 0.0,
        .sell_volume = 0.0,
        .trade_count = 0
    };

    /* Main aggregation loop */
    for (size_t i = 0; i < tick_count; i++) {
        /* Prefetch upcoming ticks */
        if (LIKELY(i + PREFETCH_DISTANCE < tick_count)) {
            PREFETCH_READ(&ticks[i + PREFETCH_DISTANCE]);
        }

        int64_t tick_period = ticks[i].ts_ms / interval_ms;

        if (tick_period != current_period) {
            /* New candle - emit and start fresh */
            if (UNLIKELY(candle_idx >= max_candles)) {
                return (int64_t)candle_idx;
            }
            candles_out[candle_idx++] = current;

            current_period = tick_period;
            current.ts_ms = current_period * interval_ms;
            current.open_tick = ticks[i].price_tick;
            current.high_tick = ticks[i].price_tick;
            current.low_tick = ticks[i].price_tick;
            current.close_tick = ticks[i].price_tick;
            current.volume = 0.0;
            current.buy_volume = 0.0;
            current.sell_volume = 0.0;
            current.trade_count = 0;
        }

        /* Update current candle */
        int64_t price = ticks[i].price_tick;
        current.high_tick = (price > current.high_tick) ? price : current.high_tick;
        current.low_tick = (price < current.low_tick) ? price : current.low_tick;
        current.close_tick = price;

        double qty = (double)ticks[i].qty;
        current.volume += qty;
        current.buy_volume += (ticks[i].side == SIDE_BUY) ? qty : 0.0;
        current.sell_volume += (ticks[i].side == SIDE_SELL) ? qty : 0.0;
        current.trade_count++;
    }

    /* Emit final candle */
    if (LIKELY(candle_idx < max_candles)) {
        candles_out[candle_idx++] = current;
    }

    return (int64_t)candle_idx;
}

/* ---------------------------------------------------------------------
 * Batch Aggregation with Gap Filling
 * --------------------------------------------------------------------- */

HOT_FUNCTION
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
) {
    /* Parameter validation */
    if (UNLIKELY(!timestamps || !price_ticks || !qtys || !sides || !candles_out)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(interval_ms <= 0 || max_candles == 0)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(count == 0)) {
        return 0;
    }

    /* No gap filling - use fast path */
    if (!fill_gaps) {
        return candles_aggregate(timestamps, price_ticks, qtys, sides, count,
                                  interval_ms, candles_out, max_candles);
    }

    size_t candle_idx = 0;
    int64_t current_period = timestamps[0] / interval_ms;

    /* Initialize first candle */
    candle_t current = {
        .ts_ms = current_period * interval_ms,
        .open_tick = price_ticks[0],
        .high_tick = price_ticks[0],
        .low_tick = price_ticks[0],
        .close_tick = price_ticks[0],
        .volume = 0.0,
        .buy_volume = 0.0,
        .sell_volume = 0.0,
        .trade_count = 0
    };

    /* Main aggregation loop with gap detection */
    for (size_t i = 0; i < count; i++) {
        /* Prefetch upcoming data */
        if (LIKELY(i + PREFETCH_DISTANCE < count)) {
            PREFETCH_READ(&timestamps[i + PREFETCH_DISTANCE]);
            PREFETCH_READ(&price_ticks[i + PREFETCH_DISTANCE]);
        }

        int64_t tick_period = timestamps[i] / interval_ms;

        if (tick_period != current_period) {
            /* Emit current candle */
            if (UNLIKELY(candle_idx >= max_candles)) {
                return (int64_t)candle_idx;
            }
            candles_out[candle_idx++] = current;

            /* Fill gaps with synthetic candles */
            int64_t prev_close = current.close_tick;
            int64_t gap_period = current_period + 1;

            while (gap_period < tick_period) {
                if (UNLIKELY(candle_idx >= max_candles)) {
                    return (int64_t)candle_idx;
                }
                candle_init_gap(&candles_out[candle_idx++], gap_period * interval_ms, prev_close);
                gap_period++;
            }

            /* Start new candle */
            current_period = tick_period;
            current.ts_ms = current_period * interval_ms;
            current.open_tick = price_ticks[i];
            current.high_tick = price_ticks[i];
            current.low_tick = price_ticks[i];
            current.close_tick = price_ticks[i];
            current.volume = 0.0;
            current.buy_volume = 0.0;
            current.sell_volume = 0.0;
            current.trade_count = 0;
        }

        /* Update current candle */
        int64_t price = price_ticks[i];
        current.high_tick = (price > current.high_tick) ? price : current.high_tick;
        current.low_tick = (price < current.low_tick) ? price : current.low_tick;
        current.close_tick = price;

        double qty = qtys[i];
        current.volume += qty;
        current.buy_volume += (sides[i] == 0) ? qty : 0.0;
        current.sell_volume += (sides[i] == 1) ? qty : 0.0;
        current.trade_count++;
    }

    /* Emit final candle */
    if (LIKELY(candle_idx < max_candles)) {
        candles_out[candle_idx++] = current;
    }

    return (int64_t)candle_idx;
}

/* ---------------------------------------------------------------------
 * Candle Resampling
 *
 * Aggregates smaller candles into larger timeframes.
 * Single-pass O(n) algorithm.
 * --------------------------------------------------------------------- */

HOT_FUNCTION
int64_t candles_resample(
    const candle_t* candles,
    size_t count,
    int64_t input_ms,
    int64_t output_ms,
    candle_t* candles_out,
    size_t max_candles
) {
    /* Parameter validation */
    if (UNLIKELY(!candles || !candles_out)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(input_ms <= 0 || output_ms <= 0)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(output_ms < input_ms)) {
        return CANDLE_ERR_PARAM; /* Cannot downsample */
    }
    if (UNLIKELY(output_ms % input_ms != 0)) {
        return CANDLE_ERR_PARAM; /* Must be exact multiple */
    }
    if (UNLIKELY(max_candles == 0)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(count == 0)) {
        return 0;
    }

    /* If same interval, just copy */
    if (output_ms == input_ms) {
        size_t copy_count = (count < max_candles) ? count : max_candles;
        memcpy(candles_out, candles, copy_count * sizeof(candle_t));
        return (int64_t)copy_count;
    }

    size_t out_idx = 0;
    int64_t current_period = candles[0].ts_ms / output_ms;

    /* Initialize first output candle */
    candle_t current = candles[0];
    current.ts_ms = current_period * output_ms;

    /* Main resampling loop */
    for (size_t i = 1; i < count; i++) {
        /* Prefetch upcoming candles */
        if (LIKELY(i + PREFETCH_DISTANCE < count)) {
            PREFETCH_READ(&candles[i + PREFETCH_DISTANCE]);
        }

        int64_t candle_period = candles[i].ts_ms / output_ms;

        if (candle_period != current_period) {
            /* New target interval - emit and start fresh */
            if (UNLIKELY(out_idx >= max_candles)) {
                return (int64_t)out_idx;
            }
            candles_out[out_idx++] = current;

            /* Start new candle */
            current_period = candle_period;
            current = candles[i];
            current.ts_ms = current_period * output_ms;
        } else {
            /* Same target interval - merge */
            if (candles[i].high_tick > current.high_tick) {
                current.high_tick = candles[i].high_tick;
            }
            if (candles[i].low_tick < current.low_tick) {
                current.low_tick = candles[i].low_tick;
            }
            current.close_tick = candles[i].close_tick;
            current.volume += candles[i].volume;
            current.buy_volume += candles[i].buy_volume;
            current.sell_volume += candles[i].sell_volume;
            current.trade_count += candles[i].trade_count;
        }
    }

    /* Emit final candle */
    if (LIKELY(out_idx < max_candles)) {
        candles_out[out_idx++] = current;
    }

    return (int64_t)out_idx;
}

/* ---------------------------------------------------------------------
 * Streaming Aggregator Implementation
 * --------------------------------------------------------------------- */

candle_aggregator_t* candle_aggregator_new(int64_t interval_ms) {
    if (interval_ms <= 0) {
        return NULL;
    }

    candle_aggregator_t* agg = (candle_aggregator_t*)malloc(sizeof(candle_aggregator_t));
    if (!agg) {
        return NULL;
    }

    agg->interval_ms = interval_ms;
    agg->current_period_start = 0;
    agg->has_data = 0;
    memset(&agg->current, 0, sizeof(candle_t));

    return agg;
}

void candle_aggregator_free(candle_aggregator_t* agg) {
    free(agg); /* free(NULL) is safe */
}

void candle_aggregator_reset(candle_aggregator_t* agg) {
    if (agg) {
        agg->current_period_start = 0;
        agg->has_data = 0;
        memset(&agg->current, 0, sizeof(candle_t));
    }
}

HOT_FUNCTION
int candle_aggregator_update(
    candle_aggregator_t* agg,
    int64_t ts_ms,
    int64_t price_tick,
    double qty,
    uint8_t side,
    candle_t* candle_out
) {
    if (UNLIKELY(!agg || !candle_out)) {
        return CANDLE_ERR_PARAM;
    }

    int64_t period_start = (ts_ms / agg->interval_ms) * agg->interval_ms;
    int completed = 0;

    if (agg->has_data && period_start != agg->current_period_start) {
        /* Output completed candle */
        *candle_out = agg->current;
        completed = 1;

        /* Reset for new period */
        agg->has_data = 0;
    }

    if (!agg->has_data) {
        /* Start new candle */
        agg->current_period_start = period_start;
        agg->current.ts_ms = period_start;
        agg->current.open_tick = price_tick;
        agg->current.high_tick = price_tick;
        agg->current.low_tick = price_tick;
        agg->current.close_tick = price_tick;
        agg->current.volume = 0.0;
        agg->current.buy_volume = 0.0;
        agg->current.sell_volume = 0.0;
        agg->current.trade_count = 0;
        agg->has_data = 1;
    }

    /* Update current candle - branchless high/low */
    agg->current.high_tick = (price_tick > agg->current.high_tick) ?
                              price_tick : agg->current.high_tick;
    agg->current.low_tick = (price_tick < agg->current.low_tick) ?
                             price_tick : agg->current.low_tick;
    agg->current.close_tick = price_tick;
    agg->current.volume += qty;
    agg->current.buy_volume += (side == 0) ? qty : 0.0;
    agg->current.sell_volume += (side == 1) ? qty : 0.0;
    agg->current.trade_count++;

    return completed;
}

HOT_FUNCTION
int candle_aggregator_feed(
    candle_aggregator_t* agg,
    const tick_event_t* tick,
    candle_t* candle_out
) {
    if (UNLIKELY(!agg || !tick || !candle_out)) {
        return CANDLE_ERR_PARAM;
    }

    return candle_aggregator_update(
        agg,
        tick->ts_ms,
        tick->price_tick,
        (double)tick->qty,
        (uint8_t)tick->side,
        candle_out
    );
}

int candle_aggregator_flush(candle_aggregator_t* agg, candle_t* candle_out) {
    if (UNLIKELY(!agg || !candle_out)) {
        return CANDLE_ERR_PARAM;
    }

    if (!agg->has_data) {
        return 0; /* No data to flush */
    }

    *candle_out = agg->current;
    agg->has_data = 0;

    return 1;
}

int candle_aggregator_peek(const candle_aggregator_t* agg, candle_t* candle_out) {
    if (UNLIKELY(!agg || !candle_out)) {
        return CANDLE_ERR_PARAM;
    }

    if (!agg->has_data) {
        return 0;
    }

    *candle_out = agg->current;
    return 1;
}

/* ---------------------------------------------------------------------
 * Multi-Timeframe Batch Aggregation
 *
 * Process ticks once and output multiple timeframes simultaneously.
 * More cache-efficient than calling candles_aggregate multiple times.
 * --------------------------------------------------------------------- */

int candles_aggregate_multi(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    const int64_t* intervals_ms,
    size_t interval_count,
    candle_t** out_candles,
    const size_t* max_candles,
    size_t* out_counts
) {
    /* Parameter validation */
    if (UNLIKELY(!timestamps || !price_ticks || !qtys || !sides)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(!intervals_ms || !out_candles || !max_candles || !out_counts)) {
        return CANDLE_ERR_PARAM;
    }
    if (UNLIKELY(interval_count == 0)) {
        return CANDLE_ERR_PARAM;
    }

    /* Initialize output counts */
    for (size_t i = 0; i < interval_count; i++) {
        out_counts[i] = 0;
    }

    if (count == 0) {
        return CANDLE_OK;
    }

    /* Allocate temporary state for each timeframe */
    candle_t* currents = (candle_t*)malloc(interval_count * sizeof(candle_t));
    int64_t* periods = (int64_t*)malloc(interval_count * sizeof(int64_t));
    size_t* indices = (size_t*)malloc(interval_count * sizeof(size_t));

    if (!currents || !periods || !indices) {
        free(currents);
        free(periods);
        free(indices);
        return CANDLE_ERR_NOMEM;
    }

    /* Initialize all timeframes with first tick */
    for (size_t tf = 0; tf < interval_count; tf++) {
        periods[tf] = timestamps[0] / intervals_ms[tf];
        currents[tf].ts_ms = periods[tf] * intervals_ms[tf];
        currents[tf].open_tick = price_ticks[0];
        currents[tf].high_tick = price_ticks[0];
        currents[tf].low_tick = price_ticks[0];
        currents[tf].close_tick = price_ticks[0];
        currents[tf].volume = 0.0;
        currents[tf].buy_volume = 0.0;
        currents[tf].sell_volume = 0.0;
        currents[tf].trade_count = 0;
        indices[tf] = 0;
    }

    /* Process all ticks */
    for (size_t t = 0; t < count; t++) {
        /* Prefetch */
        if (LIKELY(t + PREFETCH_DISTANCE < count)) {
            PREFETCH_READ(&timestamps[t + PREFETCH_DISTANCE]);
            PREFETCH_READ(&price_ticks[t + PREFETCH_DISTANCE]);
        }

        int64_t ts = timestamps[t];
        int64_t price = price_ticks[t];
        double qty = qtys[t];
        uint8_t side = sides[t];

        /* Update all timeframes */
        for (size_t tf = 0; tf < interval_count; tf++) {
            int64_t tick_period = ts / intervals_ms[tf];

            if (tick_period != periods[tf]) {
                /* Emit candle */
                if (indices[tf] < max_candles[tf]) {
                    out_candles[tf][indices[tf]++] = currents[tf];
                }

                /* Start new candle */
                periods[tf] = tick_period;
                currents[tf].ts_ms = tick_period * intervals_ms[tf];
                currents[tf].open_tick = price;
                currents[tf].high_tick = price;
                currents[tf].low_tick = price;
                currents[tf].close_tick = price;
                currents[tf].volume = 0.0;
                currents[tf].buy_volume = 0.0;
                currents[tf].sell_volume = 0.0;
                currents[tf].trade_count = 0;
            }

            /* Update candle */
            currents[tf].high_tick = (price > currents[tf].high_tick) ?
                                      price : currents[tf].high_tick;
            currents[tf].low_tick = (price < currents[tf].low_tick) ?
                                     price : currents[tf].low_tick;
            currents[tf].close_tick = price;
            currents[tf].volume += qty;
            currents[tf].buy_volume += (side == 0) ? qty : 0.0;
            currents[tf].sell_volume += (side == 1) ? qty : 0.0;
            currents[tf].trade_count++;
        }
    }

    /* Emit final candles */
    for (size_t tf = 0; tf < interval_count; tf++) {
        if (indices[tf] < max_candles[tf]) {
            out_candles[tf][indices[tf]++] = currents[tf];
        }
        out_counts[tf] = indices[tf];
    }

    free(currents);
    free(periods);
    free(indices);

    return CANDLE_OK;
}
