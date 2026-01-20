/**
 * Volume Analysis Implementation
 *
 * High-performance volume analytics with:
 * - SIMD-optimized VWAP (AVX2, SSE4, NEON)
 * - Single-pass algorithms throughout
 * - Loop unrolling for better ILP
 * - No allocations in hot paths (except volume_profile_build, mfi_calculate)
 *
 * Target performance:
 * - VWAP: >300M ticks/sec
 * - Volume Profile: >100M ticks/sec
 * - Cumulative Delta: >400M ticks/sec
 *
 * Compile with: -O3 -march=native for best performance
 */

#include "volume.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

/* SIMD headers based on architecture */
#if defined(__AVX2__)
    #define VOLUME_HAS_AVX2 1
    #include <immintrin.h>
#else
    #define VOLUME_HAS_AVX2 0
#endif

#if defined(__ARM_NEON) || defined(__ARM_NEON__)
    #define VOLUME_HAS_NEON 1
    #include <arm_neon.h>
#else
    #define VOLUME_HAS_NEON 0
#endif

/* Compiler hints */
#if defined(__GNUC__) || defined(__clang__)
    #define VOLUME_LIKELY(x)   __builtin_expect(!!(x), 1)
    #define VOLUME_UNLIKELY(x) __builtin_expect(!!(x), 0)
    #define VOLUME_RESTRICT    __restrict__
    #define VOLUME_PREFETCH(p) __builtin_prefetch(p, 0, 3)
#else
    #define VOLUME_LIKELY(x)   (x)
    #define VOLUME_UNLIKELY(x) (x)
    #define VOLUME_RESTRICT
    #define VOLUME_PREFETCH(p) ((void)0)
#endif

/* Milliseconds per day for session detection */
#define MS_PER_DAY (24LL * 60LL * 60LL * 1000LL)

/* ---------------------------------------------------------------------
 * VWAP Implementation
 *
 * The cumulative nature of VWAP limits SIMD parallelism, but we can
 * still benefit from loop unrolling and prefetching.
 * --------------------------------------------------------------------- */

#if VOLUME_HAS_NEON

/* ARM NEON optimized VWAP with unrolling */
static int vwap_calculate_neon(
    const int64_t* VOLUME_RESTRICT price_ticks,
    const double* VOLUME_RESTRICT qtys,
    size_t count,
    double tick_size,
    double* VOLUME_RESTRICT vwap_out
) {
    double cum_pv = 0.0;
    double cum_v = 0.0;

    float64x2_t tick_size_vec = vdupq_n_f64(tick_size);

    size_t i = 0;
    const size_t simd_count = count & ~1ULL;

    for (; i < simd_count; i += 2) {
        VOLUME_PREFETCH(&price_ticks[i + 16]);
        VOLUME_PREFETCH(&qtys[i + 16]);

        /* Load 2 price ticks and convert to double */
        float64x2_t prices = vcvtq_f64_s64(vld1q_s64(&price_ticks[i]));

        /* Load 2 quantities */
        float64x2_t volumes = vld1q_f64(&qtys[i]);

        /* Convert to actual prices */
        prices = vmulq_f64(prices, tick_size_vec);

        /* price * volume */
        float64x2_t pv = vmulq_f64(prices, volumes);

        /* Extract and accumulate (cumulative requires sequential) */
        cum_pv += vgetq_lane_f64(pv, 0);
        cum_v += vgetq_lane_f64(volumes, 0);
        vwap_out[i] = cum_v > 0.0 ? cum_pv / cum_v : vgetq_lane_f64(prices, 0);

        cum_pv += vgetq_lane_f64(pv, 1);
        cum_v += vgetq_lane_f64(volumes, 1);
        vwap_out[i + 1] = cum_v > 0.0 ? cum_pv / cum_v : vgetq_lane_f64(prices, 1);
    }

    /* Handle remaining element */
    for (; i < count; i++) {
        double price = (double)price_ticks[i] * tick_size;
        double volume = qtys[i];
        cum_pv += price * volume;
        cum_v += volume;
        vwap_out[i] = cum_v > 0.0 ? cum_pv / cum_v : price;
    }

    return VOLUME_OK;
}

#endif /* VOLUME_HAS_NEON */

#if VOLUME_HAS_AVX2

/* AVX2 optimized VWAP with unrolling */
static int vwap_calculate_avx2(
    const int64_t* VOLUME_RESTRICT price_ticks,
    const double* VOLUME_RESTRICT qtys,
    size_t count,
    double tick_size,
    double* VOLUME_RESTRICT vwap_out
) {
    double cum_pv = 0.0;
    double cum_v = 0.0;

    __m256d tick_size_vec = _mm256_set1_pd(tick_size);

    size_t i = 0;
    const size_t simd_count = count & ~3ULL;

    for (; i < simd_count; i += 4) {
        VOLUME_PREFETCH(&price_ticks[i + 16]);
        VOLUME_PREFETCH(&qtys[i + 16]);

        /* Load 4 price ticks and convert to double */
        __m256d prices = _mm256_set_pd(
            (double)price_ticks[i+3],
            (double)price_ticks[i+2],
            (double)price_ticks[i+1],
            (double)price_ticks[i+0]
        );

        /* Load 4 quantities */
        __m256d volumes = _mm256_loadu_pd(&qtys[i]);

        /* Convert to actual prices */
        prices = _mm256_mul_pd(prices, tick_size_vec);

        /* price * volume */
        __m256d pv = _mm256_mul_pd(prices, volumes);

        /* Extract and accumulate (cumulative requires sequential) */
        double pv_arr[4];
        double vol_arr[4];
        _mm256_storeu_pd(pv_arr, pv);
        _mm256_storeu_pd(vol_arr, volumes);

        double prices_arr[4];
        _mm256_storeu_pd(prices_arr, prices);

        for (int j = 0; j < 4; j++) {
            cum_pv += pv_arr[j];
            cum_v += vol_arr[j];
            vwap_out[i + j] = cum_v > 0.0 ? cum_pv / cum_v : prices_arr[j];
        }
    }

    /* Handle remaining elements */
    for (; i < count; i++) {
        double price = (double)price_ticks[i] * tick_size;
        double volume = qtys[i];
        cum_pv += price * volume;
        cum_v += volume;
        vwap_out[i] = cum_v > 0.0 ? cum_pv / cum_v : price;
    }

    return VOLUME_OK;
}

#endif /* VOLUME_HAS_AVX2 */

#if !VOLUME_HAS_AVX2 && !VOLUME_HAS_NEON
/* Scalar implementation with manual unrolling (used when no SIMD available) */
static int vwap_calculate_scalar(
    const int64_t* VOLUME_RESTRICT price_ticks,
    const double* VOLUME_RESTRICT qtys,
    size_t count,
    double tick_size,
    double* VOLUME_RESTRICT vwap_out
) {
    double cum_pv = 0.0;
    double cum_v = 0.0;

    size_t i = 0;
    const size_t unroll_count = count & ~3ULL;

    /* Unrolled loop for better ILP */
    for (; i < unroll_count; i += 4) {
        double p0 = (double)price_ticks[i+0] * tick_size;
        double v0 = qtys[i+0];
        double p1 = (double)price_ticks[i+1] * tick_size;
        double v1 = qtys[i+1];
        double p2 = (double)price_ticks[i+2] * tick_size;
        double v2 = qtys[i+2];
        double p3 = (double)price_ticks[i+3] * tick_size;
        double v3 = qtys[i+3];

        cum_pv += p0 * v0;
        cum_v += v0;
        vwap_out[i+0] = cum_v > 0.0 ? cum_pv / cum_v : p0;

        cum_pv += p1 * v1;
        cum_v += v1;
        vwap_out[i+1] = cum_v > 0.0 ? cum_pv / cum_v : p1;

        cum_pv += p2 * v2;
        cum_v += v2;
        vwap_out[i+2] = cum_v > 0.0 ? cum_pv / cum_v : p2;

        cum_pv += p3 * v3;
        cum_v += v3;
        vwap_out[i+3] = cum_v > 0.0 ? cum_pv / cum_v : p3;
    }

    /* Handle remaining elements */
    for (; i < count; i++) {
        double price = (double)price_ticks[i] * tick_size;
        double volume = qtys[i];
        cum_pv += price * volume;
        cum_v += volume;
        vwap_out[i] = cum_v > 0.0 ? cum_pv / cum_v : price;
    }

    return VOLUME_OK;
}
#endif /* !VOLUME_HAS_AVX2 && !VOLUME_HAS_NEON */

/* Public VWAP function - dispatches to best implementation */
int vwap_calculate(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    size_t count,
    double tick_size,
    double* vwap_out
) {
    (void)timestamps; /* unused for cumulative VWAP */

    if (VOLUME_UNLIKELY(!price_ticks || !qtys || !vwap_out)) {
        return VOLUME_ERR_PARAM;
    }
    if (VOLUME_UNLIKELY(count == 0)) {
        return VOLUME_OK;
    }
    if (VOLUME_UNLIKELY(tick_size <= 0.0)) {
        return VOLUME_ERR_PARAM;
    }

#if VOLUME_HAS_AVX2
    return vwap_calculate_avx2(price_ticks, qtys, count, tick_size, vwap_out);
#elif VOLUME_HAS_NEON
    return vwap_calculate_neon(price_ticks, qtys, count, tick_size, vwap_out);
#else
    return vwap_calculate_scalar(price_ticks, qtys, count, tick_size, vwap_out);
#endif
}

/* Session VWAP - resets at day boundary */
int vwap_session_calculate(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    size_t count,
    double tick_size,
    double* vwap_out
) {
    if (VOLUME_UNLIKELY(!timestamps || !price_ticks || !qtys || !vwap_out)) {
        return VOLUME_ERR_PARAM;
    }
    if (VOLUME_UNLIKELY(count == 0)) {
        return VOLUME_OK;
    }
    if (VOLUME_UNLIKELY(tick_size <= 0.0)) {
        return VOLUME_ERR_PARAM;
    }

    double cum_pv = 0.0;
    double cum_v = 0.0;
    int64_t current_day = timestamps[0] / MS_PER_DAY;

    for (size_t i = 0; i < count; i++) {
        int64_t day = timestamps[i] / MS_PER_DAY;

        if (day != current_day) {
            /* New session - reset */
            cum_pv = 0.0;
            cum_v = 0.0;
            current_day = day;
        }

        double price = (double)price_ticks[i] * tick_size;
        cum_pv += price * qtys[i];
        cum_v += qtys[i];

        vwap_out[i] = cum_v > 0.0 ? cum_pv / cum_v : price;
    }

    return VOLUME_OK;
}

/* ---------------------------------------------------------------------
 * Volume Profile Implementation
 * --------------------------------------------------------------------- */

int volume_profile_build(
    const int64_t* price_ticks,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    double tick_size,
    size_t num_bins,
    double value_area_pct,
    volume_profile_t* profile_out
) {
    if (VOLUME_UNLIKELY(!price_ticks || !qtys || !sides || !profile_out)) {
        return VOLUME_ERR_PARAM;
    }
    if (VOLUME_UNLIKELY(count == 0)) {
        return VOLUME_ERR_EMPTY;
    }
    if (VOLUME_UNLIKELY(num_bins == 0 || tick_size <= 0.0)) {
        return VOLUME_ERR_PARAM;
    }

    /* First pass: find price range with unrolling */
    int64_t min_tick = price_ticks[0];
    int64_t max_tick = price_ticks[0];
    double total_vol = 0.0;

    size_t i = 0;
    const size_t unroll_count = count & ~3ULL;

    for (; i < unroll_count; i += 4) {
        int64_t p0 = price_ticks[i+0];
        int64_t p1 = price_ticks[i+1];
        int64_t p2 = price_ticks[i+2];
        int64_t p3 = price_ticks[i+3];

        if (p0 < min_tick) min_tick = p0;
        if (p1 < min_tick) min_tick = p1;
        if (p2 < min_tick) min_tick = p2;
        if (p3 < min_tick) min_tick = p3;

        if (p0 > max_tick) max_tick = p0;
        if (p1 > max_tick) max_tick = p1;
        if (p2 > max_tick) max_tick = p2;
        if (p3 > max_tick) max_tick = p3;

        total_vol += qtys[i+0] + qtys[i+1] + qtys[i+2] + qtys[i+3];
    }

    for (; i < count; i++) {
        if (price_ticks[i] < min_tick) min_tick = price_ticks[i];
        if (price_ticks[i] > max_tick) max_tick = price_ticks[i];
        total_vol += qtys[i];
    }

    int64_t range = max_tick - min_tick + 1;
    int64_t ticks_per_bin = (range + (int64_t)num_bins - 1) / (int64_t)num_bins;
    if (ticks_per_bin < 1) ticks_per_bin = 1;

    /* Allocate bins */
    volume_bin_t* bins = (volume_bin_t*)calloc(num_bins, sizeof(volume_bin_t));
    if (VOLUME_UNLIKELY(!bins)) {
        return VOLUME_ERR_NOMEM;
    }

    /* Initialize bin prices */
    for (i = 0; i < num_bins; i++) {
        bins[i].price_tick = min_tick + (int64_t)i * ticks_per_bin + ticks_per_bin / 2;
    }

    /* Second pass: accumulate volume with unrolling */
    i = 0;
    for (; i < unroll_count; i += 4) {
        size_t b0 = (size_t)((price_ticks[i+0] - min_tick) / ticks_per_bin);
        size_t b1 = (size_t)((price_ticks[i+1] - min_tick) / ticks_per_bin);
        size_t b2 = (size_t)((price_ticks[i+2] - min_tick) / ticks_per_bin);
        size_t b3 = (size_t)((price_ticks[i+3] - min_tick) / ticks_per_bin);

        if (b0 >= num_bins) b0 = num_bins - 1;
        if (b1 >= num_bins) b1 = num_bins - 1;
        if (b2 >= num_bins) b2 = num_bins - 1;
        if (b3 >= num_bins) b3 = num_bins - 1;

        bins[b0].volume += qtys[i+0];
        bins[b1].volume += qtys[i+1];
        bins[b2].volume += qtys[i+2];
        bins[b3].volume += qtys[i+3];

        if (sides[i+0] == 0) bins[b0].buy_volume += qtys[i+0]; else bins[b0].sell_volume += qtys[i+0];
        if (sides[i+1] == 0) bins[b1].buy_volume += qtys[i+1]; else bins[b1].sell_volume += qtys[i+1];
        if (sides[i+2] == 0) bins[b2].buy_volume += qtys[i+2]; else bins[b2].sell_volume += qtys[i+2];
        if (sides[i+3] == 0) bins[b3].buy_volume += qtys[i+3]; else bins[b3].sell_volume += qtys[i+3];
    }

    for (; i < count; i++) {
        size_t bin_idx = (size_t)((price_ticks[i] - min_tick) / ticks_per_bin);
        if (bin_idx >= num_bins) bin_idx = num_bins - 1;

        bins[bin_idx].volume += qtys[i];
        if (sides[i] == 0) {
            bins[bin_idx].buy_volume += qtys[i];
        } else {
            bins[bin_idx].sell_volume += qtys[i];
        }
    }

    /* Find POC (Point of Control) */
    int64_t poc_tick = bins[0].price_tick;
    double max_vol = bins[0].volume;
    size_t poc_idx = 0;

    for (i = 1; i < num_bins; i++) {
        if (bins[i].volume > max_vol) {
            max_vol = bins[i].volume;
            poc_tick = bins[i].price_tick;
            poc_idx = i;
        }
    }

    /* Calculate Value Area using TPO method */
    double value_area_target = total_vol * (value_area_pct / 100.0);
    double va_volume = bins[poc_idx].volume;
    size_t va_low = poc_idx;
    size_t va_high = poc_idx;

    while (va_volume < value_area_target && (va_low > 0 || va_high < num_bins - 1)) {
        double vol_below = (va_low > 0) ? bins[va_low - 1].volume : 0.0;
        double vol_above = (va_high < num_bins - 1) ? bins[va_high + 1].volume : 0.0;

        if (vol_below >= vol_above && va_low > 0) {
            va_low--;
            va_volume += bins[va_low].volume;
        } else if (va_high < num_bins - 1) {
            va_high++;
            va_volume += bins[va_high].volume;
        } else if (va_low > 0) {
            va_low--;
            va_volume += bins[va_low].volume;
        }
    }

    /* Fill output */
    profile_out->bins = bins;
    profile_out->num_bins = num_bins;
    profile_out->poc_tick = poc_tick;
    profile_out->val_tick = bins[va_low].price_tick;
    profile_out->vah_tick = bins[va_high].price_tick;
    profile_out->total_volume = total_vol;

    return VOLUME_OK;
}

void volume_profile_free(volume_profile_t* profile) {
    if (profile && profile->bins) {
        free(profile->bins);
        profile->bins = NULL;
    }
}

/* ---------------------------------------------------------------------
 * Cumulative Delta Implementation
 * --------------------------------------------------------------------- */

int cumulative_delta_calculate(
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    double* delta_out
) {
    if (VOLUME_UNLIKELY(!qtys || !sides || !delta_out)) {
        return VOLUME_ERR_PARAM;
    }

    double cum_delta = 0.0;

    /* Unroll by 4 for better ILP */
    size_t i = 0;
    const size_t unroll_count = count & ~3ULL;

    for (; i < unroll_count; i += 4) {
        double v0 = qtys[i+0];
        double v1 = qtys[i+1];
        double v2 = qtys[i+2];
        double v3 = qtys[i+3];

        cum_delta += (sides[i+0] == 0) ? v0 : -v0;
        delta_out[i+0] = cum_delta;

        cum_delta += (sides[i+1] == 0) ? v1 : -v1;
        delta_out[i+1] = cum_delta;

        cum_delta += (sides[i+2] == 0) ? v2 : -v2;
        delta_out[i+2] = cum_delta;

        cum_delta += (sides[i+3] == 0) ? v3 : -v3;
        delta_out[i+3] = cum_delta;
    }

    for (; i < count; i++) {
        if (sides[i] == 0) {
            cum_delta += qtys[i];
        } else {
            cum_delta -= qtys[i];
        }
        delta_out[i] = cum_delta;
    }

    return VOLUME_OK;
}

/* ---------------------------------------------------------------------
 * Delta Per Candle Implementation
 * --------------------------------------------------------------------- */

int64_t delta_per_candle(
    const int64_t* timestamps,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    int64_t interval_ms,
    double* delta_out,
    size_t max_candles
) {
    if (VOLUME_UNLIKELY(!timestamps || !qtys || !sides || !delta_out)) {
        return VOLUME_ERR_PARAM;
    }
    if (VOLUME_UNLIKELY(count == 0)) {
        return 0;
    }
    if (VOLUME_UNLIKELY(interval_ms <= 0)) {
        return VOLUME_ERR_PARAM;
    }

    size_t candle_count = 0;
    int64_t current_period = timestamps[0] / interval_ms;
    double period_delta = 0.0;

    for (size_t i = 0; i < count; i++) {
        int64_t tick_period = timestamps[i] / interval_ms;

        if (tick_period != current_period) {
            if (candle_count >= max_candles) {
                return (int64_t)candle_count;
            }
            delta_out[candle_count++] = period_delta;

            current_period = tick_period;
            period_delta = 0.0;
        }

        if (sides[i] == 0) {
            period_delta += qtys[i];
        } else {
            period_delta -= qtys[i];
        }
    }

    /* Save final period */
    if (candle_count < max_candles) {
        delta_out[candle_count++] = period_delta;
    }

    return (int64_t)candle_count;
}

/* ---------------------------------------------------------------------
 * OBV (On-Balance Volume) Implementation
 * --------------------------------------------------------------------- */

int obv_calculate(
    const int64_t* price_ticks,
    const double* qtys,
    size_t count,
    double* obv_out
) {
    if (VOLUME_UNLIKELY(!price_ticks || !qtys || !obv_out)) {
        return VOLUME_ERR_PARAM;
    }
    if (VOLUME_UNLIKELY(count == 0)) {
        return VOLUME_OK;
    }

    double obv = 0.0;
    obv_out[0] = obv;

    /* Unrolled for better ILP */
    size_t i = 1;
    const size_t unroll_count = ((count - 1) & ~3ULL) + 1;

    for (; i < unroll_count && i + 3 < count; i += 4) {
        /* Iteration 1 */
        if (price_ticks[i] > price_ticks[i-1]) {
            obv += qtys[i];
        } else if (price_ticks[i] < price_ticks[i-1]) {
            obv -= qtys[i];
        }
        obv_out[i] = obv;

        /* Iteration 2 */
        if (price_ticks[i+1] > price_ticks[i]) {
            obv += qtys[i+1];
        } else if (price_ticks[i+1] < price_ticks[i]) {
            obv -= qtys[i+1];
        }
        obv_out[i+1] = obv;

        /* Iteration 3 */
        if (price_ticks[i+2] > price_ticks[i+1]) {
            obv += qtys[i+2];
        } else if (price_ticks[i+2] < price_ticks[i+1]) {
            obv -= qtys[i+2];
        }
        obv_out[i+2] = obv;

        /* Iteration 4 */
        if (price_ticks[i+3] > price_ticks[i+2]) {
            obv += qtys[i+3];
        } else if (price_ticks[i+3] < price_ticks[i+2]) {
            obv -= qtys[i+3];
        }
        obv_out[i+3] = obv;
    }

    /* Handle remaining elements */
    for (; i < count; i++) {
        if (price_ticks[i] > price_ticks[i-1]) {
            obv += qtys[i];
        } else if (price_ticks[i] < price_ticks[i-1]) {
            obv -= qtys[i];
        }
        obv_out[i] = obv;
    }

    return VOLUME_OK;
}

/* ---------------------------------------------------------------------
 * MFI (Money Flow Index) Implementation
 *
 * Uses rolling window for O(n) complexity instead of O(n*period)
 * --------------------------------------------------------------------- */

int mfi_calculate(
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    const int64_t* close_ticks,
    const double* volumes,
    size_t count,
    int period,
    double* mfi_out
) {
    if (VOLUME_UNLIKELY(!high_ticks || !low_ticks || !close_ticks || !volumes || !mfi_out)) {
        return VOLUME_ERR_PARAM;
    }
    if (VOLUME_UNLIKELY(period <= 0 || (size_t)period >= count)) {
        return VOLUME_ERR_PARAM;
    }

    size_t period_sz = (size_t)period;

    /* Allocate buffers for typical prices and raw money flow */
    double* typical = (double*)malloc(count * sizeof(double));
    double* raw_mf = (double*)malloc(count * sizeof(double));
    if (VOLUME_UNLIKELY(!typical || !raw_mf)) {
        free(typical);
        free(raw_mf);
        return VOLUME_ERR_NOMEM;
    }

    /* Calculate typical prices and raw money flow */
    for (size_t i = 0; i < count; i++) {
        typical[i] = (double)(high_ticks[i] + low_ticks[i] + close_ticks[i]) / 3.0;
        raw_mf[i] = typical[i] * volumes[i];
    }

    /* Initialize first (period) values to neutral */
    for (size_t i = 0; i < period_sz; i++) {
        mfi_out[i] = 50.0;
    }

    /* Build initial window */
    double pos_mf_sum = 0.0;
    double neg_mf_sum = 0.0;

    for (size_t i = 1; i <= period_sz; i++) {
        if (typical[i] > typical[i-1]) {
            pos_mf_sum += raw_mf[i];
        } else if (typical[i] < typical[i-1]) {
            neg_mf_sum += raw_mf[i];
        }
    }

    /* Calculate MFI for period-th element */
    if (neg_mf_sum > 0.0) {
        double mf_ratio = pos_mf_sum / neg_mf_sum;
        mfi_out[period_sz] = 100.0 - (100.0 / (1.0 + mf_ratio));
    } else if (pos_mf_sum > 0.0) {
        mfi_out[period_sz] = 100.0;
    } else {
        mfi_out[period_sz] = 50.0;
    }

    /* Rolling calculation for remaining elements - O(n) total */
    for (size_t i = period_sz + 1; i < count; i++) {
        /* Remove oldest from window */
        size_t old_idx = i - period_sz;
        if (typical[old_idx] > typical[old_idx - 1]) {
            pos_mf_sum -= raw_mf[old_idx];
        } else if (typical[old_idx] < typical[old_idx - 1]) {
            neg_mf_sum -= raw_mf[old_idx];
        }

        /* Add newest to window */
        if (typical[i] > typical[i-1]) {
            pos_mf_sum += raw_mf[i];
        } else if (typical[i] < typical[i-1]) {
            neg_mf_sum += raw_mf[i];
        }

        /* Ensure non-negative sums (floating point precision) */
        if (pos_mf_sum < 0.0) pos_mf_sum = 0.0;
        if (neg_mf_sum < 0.0) neg_mf_sum = 0.0;

        /* Calculate MFI */
        if (neg_mf_sum > 0.0) {
            double mf_ratio = pos_mf_sum / neg_mf_sum;
            mfi_out[i] = 100.0 - (100.0 / (1.0 + mf_ratio));
        } else if (pos_mf_sum > 0.0) {
            mfi_out[i] = 100.0;
        } else {
            mfi_out[i] = 50.0;
        }
    }

    free(typical);
    free(raw_mf);

    return VOLUME_OK;
}
