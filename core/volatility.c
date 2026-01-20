/**
 * Volatility Calculation Implementation
 *
 * High-performance volatility estimators with SIMD acceleration.
 * Uses Welford's online algorithm for numerical stability.
 * Circular buffers for O(1) rolling window updates.
 *
 * Performance target: >200M candles/sec for all estimators.
 */

#include "volatility.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <float.h>

/* SIMD support detection */
#if defined(__AVX2__) && !defined(AG_DISABLE_SIMD)
#include <immintrin.h>
#define SIMD_WIDTH_D 4
#define HAS_AVX2 1
#endif

#if (defined(__ARM_NEON) || defined(__aarch64__)) && !defined(AG_DISABLE_SIMD)
#include <arm_neon.h>
#define HAS_NEON 1
#endif

/* Compiler optimization hints */
#if defined(__GNUC__) || defined(__clang__)
    #define LIKELY(x)   __builtin_expect(!!(x), 1)
    #define UNLIKELY(x) __builtin_expect(!!(x), 0)
    #define RESTRICT    __restrict__
    #define HOT_FUNC    __attribute__((hot))
    #define PREFETCH(a) __builtin_prefetch(a, 0, 3)
#else
    #define LIKELY(x)   (x)
    #define UNLIKELY(x) (x)
    #define RESTRICT
    #define HOT_FUNC
    #define PREFETCH(a) ((void)0)
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* Pre-computed constants for performance */
#define ANNUALIZE_FACTOR 19.1049731745428     /* sqrt(365) */
#define INV_4_LN2        0.3606737602222409   /* 1 / (4 * ln(2)) */
#define TWO_LN2_MINUS_1  0.3862943611198906   /* 2*ln(2) - 1 */
#define SQRT_INV_4_LN2   0.6005612066498586   /* sqrt(1 / (4 * ln(2))) */

/* ========== Welford's Online Algorithm ========== */

typedef struct {
    double mean;
    double M2;      /* Sum of squared deviations */
    size_t count;
} welford_t;

static inline void welford_init(welford_t* w) {
    w->mean = 0.0;
    w->M2 = 0.0;
    w->count = 0;
}

static inline void welford_update(welford_t* w, double x) {
    w->count++;
    double delta = x - w->mean;
    w->mean += delta / (double)w->count;
    double delta2 = x - w->mean;
    w->M2 += delta * delta2;
}

static inline void welford_remove(welford_t* w, double x) {
    if (w->count <= 1) {
        welford_init(w);
        return;
    }
    double old_mean = w->mean;
    w->count--;
    w->mean = (old_mean * (w->count + 1) - x) / (double)w->count;
    double delta = x - w->mean;
    double delta_old = x - old_mean;
    w->M2 -= delta * delta_old;
    if (w->M2 < 0.0) w->M2 = 0.0;  /* Numerical safety */
}

static inline double welford_variance(const welford_t* w) {
    if (w->count < 2) return 0.0;
    return w->M2 / (double)(w->count - 1);
}

static inline double welford_stddev(const welford_t* w) {
    return sqrt(welford_variance(w));
}

/* ========== SIMD Helper Functions ========== */

#ifdef HAS_AVX2
static inline double avx2_hsum(__m256d v) {
    __m128d vlow = _mm256_castpd256_pd128(v);
    __m128d vhigh = _mm256_extractf128_pd(v, 1);
    vlow = _mm_add_pd(vlow, vhigh);
    __m128d high64 = _mm_unpackhi_pd(vlow, vlow);
    return _mm_cvtsd_f64(_mm_add_sd(vlow, high64));
}
#endif

/* Internal volatility state */
struct volatility_state_s {
    volatility_method_t method;
    int window;
    double param;  /* lambda for EWMA */
    int annualize;

    /* Ring buffer for windowed calculations */
    double* buffer;
    double* buffer2;   /* For Yang-Zhang OC returns */
    double* buffer3;   /* For Yang-Zhang RS terms */
    size_t buffer_size;
    size_t buffer_idx;
    size_t count;

    /* Welford state for streaming variance */
    welford_t welford;
    welford_t welford2;  /* For Yang-Zhang OC variance */
    double rs_sum;       /* Running sum for RS terms */

    /* EWMA state */
    double ewma_var;
    double prev_close;
    int initialized;
};

static inline double calc_log_return(int64_t prev, int64_t curr) {
    if (UNLIKELY(prev <= 0 || curr <= 0)) return 0.0;
    return log((double)curr / (double)prev);
}

HOT_FUNC
int volatility_realized(
    const int64_t* RESTRICT close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* RESTRICT vol_out
) {
    if (UNLIKELY(!close_ticks || !vol_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(window <= 1 || (size_t)window > count)) {
        return VOLATILITY_ERR_WINDOW;
    }

    size_t win = (size_t)window;
    double ann_factor = annualize ? ANNUALIZE_FACTOR : 1.0;

    /* Fill initial values with 0 (insufficient data) */
    for (size_t i = 0; i < win && i < count; i++) {
        vol_out[i] = 0.0;
    }

    if (count <= win) {
        return VOLATILITY_OK;
    }

    /* Allocate circular buffer for log returns */
    double* returns_buf = (double*)malloc(win * sizeof(double));
    if (UNLIKELY(!returns_buf)) {
        return VOLATILITY_ERR_NOMEM;
    }

    /* Initialize Welford state and fill buffer with first window of returns */
    welford_t w;
    welford_init(&w);

    for (size_t i = 0; i < win; i++) {
        double ret = calc_log_return(close_ticks[i], close_ticks[i + 1]);
        returns_buf[i] = ret;
        welford_update(&w, ret);
    }

    /* First valid volatility at index 'window' */
    vol_out[win] = welford_stddev(&w) * ann_factor;

    /* Rolling calculation using circular buffer - O(1) per update */
    size_t buf_pos = 0;
    for (size_t i = win + 1; i < count; i++) {
        PREFETCH(&close_ticks[i + 8]);

        /* Remove oldest return from Welford state */
        double old_ret = returns_buf[buf_pos];
        welford_remove(&w, old_ret);

        /* Add new return */
        double new_ret = calc_log_return(close_ticks[i - 1], close_ticks[i]);
        returns_buf[buf_pos] = new_ret;
        welford_update(&w, new_ret);

        /* Advance circular buffer position */
        buf_pos = (buf_pos + 1) % win;

        /* Output volatility */
        vol_out[i] = welford_stddev(&w) * ann_factor;
    }

    free(returns_buf);
    return VOLATILITY_OK;
}

HOT_FUNC
int volatility_parkinson(
    const int64_t* RESTRICT high_ticks,
    const int64_t* RESTRICT low_ticks,
    size_t count,
    int window,
    bool annualize,
    double* RESTRICT vol_out
) {
    if (UNLIKELY(!high_ticks || !low_ticks || !vol_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(window <= 0 || (size_t)window > count)) {
        return VOLATILITY_ERR_WINDOW;
    }

    size_t win = (size_t)window;

    /* Annualization factor includes Parkinson constant */
    double scale_factor = annualize ? SQRT_INV_4_LN2 * ANNUALIZE_FACTOR : SQRT_INV_4_LN2;

    /* Fill initial values with 0 */
    for (size_t i = 0; i < win - 1 && i < count; i++) {
        vol_out[i] = 0.0;
    }

    if (count < win) {
        return VOLATILITY_OK;
    }

    /* Allocate circular buffer for squared log H/L */
    double* hl_buf = (double*)malloc(win * sizeof(double));
    if (UNLIKELY(!hl_buf)) {
        return VOLATILITY_ERR_NOMEM;
    }

    /* Initialize buffer and running sum */
    double sum_sq = 0.0;

#ifdef HAS_AVX2
    /* SIMD initialization for large windows */
    size_t i = 0;
    if (win >= 4) {
        __m256d v_sum = _mm256_setzero_pd();
        for (; i + 4 <= win; i += 4) {
            /* Load high and low ticks */
            double h0 = (double)high_ticks[i], h1 = (double)high_ticks[i+1];
            double h2 = (double)high_ticks[i+2], h3 = (double)high_ticks[i+3];
            double l0 = (double)low_ticks[i], l1 = (double)low_ticks[i+1];
            double l2 = (double)low_ticks[i+2], l3 = (double)low_ticks[i+3];

            /* Compute log ratios and square them */
            double sq0 = (l0 > 0) ? log(h0/l0) : 0.0; sq0 *= sq0;
            double sq1 = (l1 > 0) ? log(h1/l1) : 0.0; sq1 *= sq1;
            double sq2 = (l2 > 0) ? log(h2/l2) : 0.0; sq2 *= sq2;
            double sq3 = (l3 > 0) ? log(h3/l3) : 0.0; sq3 *= sq3;

            hl_buf[i] = sq0; hl_buf[i+1] = sq1;
            hl_buf[i+2] = sq2; hl_buf[i+3] = sq3;

            __m256d v_sq = _mm256_set_pd(sq3, sq2, sq1, sq0);
            v_sum = _mm256_add_pd(v_sum, v_sq);
        }
        sum_sq = avx2_hsum(v_sum);
    }
    /* Scalar remainder */
    for (; i < win; i++) {
        double log_hl = (low_ticks[i] > 0) ? log((double)high_ticks[i] / (double)low_ticks[i]) : 0.0;
        double sq = log_hl * log_hl;
        hl_buf[i] = sq;
        sum_sq += sq;
    }
#else
    /* Pure scalar initialization */
    for (size_t i = 0; i < win; i++) {
        double log_hl = (low_ticks[i] > 0) ? log((double)high_ticks[i] / (double)low_ticks[i]) : 0.0;
        double sq = log_hl * log_hl;
        hl_buf[i] = sq;
        sum_sq += sq;
    }
#endif

    /* First valid volatility */
    vol_out[win - 1] = sqrt(sum_sq / (double)win) * scale_factor;

    /* Rolling calculation with O(1) updates */
    size_t buf_pos = 0;
    for (size_t i = win; i < count; i++) {
        PREFETCH(&high_ticks[i + 8]);
        PREFETCH(&low_ticks[i + 8]);

        /* Remove oldest value */
        sum_sq -= hl_buf[buf_pos];

        /* Add new value */
        double log_hl = (low_ticks[i] > 0) ? log((double)high_ticks[i] / (double)low_ticks[i]) : 0.0;
        double sq = log_hl * log_hl;
        hl_buf[buf_pos] = sq;
        sum_sq += sq;

        /* Advance position */
        buf_pos = (buf_pos + 1) % win;

        /* Output volatility */
        vol_out[i] = sqrt(sum_sq / (double)win) * scale_factor;
    }

    free(hl_buf);
    return VOLATILITY_OK;
}

HOT_FUNC
int volatility_garman_klass(
    const int64_t* RESTRICT open_ticks,
    const int64_t* RESTRICT high_ticks,
    const int64_t* RESTRICT low_ticks,
    const int64_t* RESTRICT close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* RESTRICT vol_out
) {
    if (UNLIKELY(!open_ticks || !high_ticks || !low_ticks || !close_ticks || !vol_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(window <= 0 || (size_t)window > count)) {
        return VOLATILITY_ERR_WINDOW;
    }

    size_t win = (size_t)window;
    double ann_factor = annualize ? ANNUALIZE_FACTOR : 1.0;

    /* Fill initial values with 0 */
    for (size_t i = 0; i < win - 1 && i < count; i++) {
        vol_out[i] = 0.0;
    }

    if (count < win) {
        return VOLATILITY_OK;
    }

    /* Allocate circular buffer for GK variance terms */
    double* gk_buf = (double*)malloc(win * sizeof(double));
    if (UNLIKELY(!gk_buf)) {
        return VOLATILITY_ERR_NOMEM;
    }

    /* Initialize buffer and running sum */
    double sum_var = 0.0;
    for (size_t i = 0; i < win; i++) {
        double var_term = 0.0;
        if (LIKELY(low_ticks[i] > 0 && open_ticks[i] > 0)) {
            double log_hl = log((double)high_ticks[i] / (double)low_ticks[i]);
            double log_co = log((double)close_ticks[i] / (double)open_ticks[i]);
            /* Garman-Klass: 0.5*(ln(H/L))^2 - (2*ln(2)-1)*(ln(C/O))^2 */
            var_term = 0.5 * log_hl * log_hl - TWO_LN2_MINUS_1 * log_co * log_co;
            /* Clamp to non-negative */
            if (var_term < 0.0) var_term = 0.0;
        }
        gk_buf[i] = var_term;
        sum_var += var_term;
    }

    /* First valid volatility */
    vol_out[win - 1] = sqrt(sum_var / (double)win) * ann_factor;

    /* Rolling calculation with O(1) updates */
    size_t buf_pos = 0;
    for (size_t i = win; i < count; i++) {
        PREFETCH(&open_ticks[i + 8]);
        PREFETCH(&high_ticks[i + 8]);
        PREFETCH(&low_ticks[i + 8]);
        PREFETCH(&close_ticks[i + 8]);

        /* Remove oldest */
        sum_var -= gk_buf[buf_pos];

        /* Add new */
        double var_term = 0.0;
        if (LIKELY(low_ticks[i] > 0 && open_ticks[i] > 0)) {
            double log_hl = log((double)high_ticks[i] / (double)low_ticks[i]);
            double log_co = log((double)close_ticks[i] / (double)open_ticks[i]);
            var_term = 0.5 * log_hl * log_hl - TWO_LN2_MINUS_1 * log_co * log_co;
            if (var_term < 0.0) var_term = 0.0;
        }
        gk_buf[buf_pos] = var_term;
        sum_var += var_term;

        /* Advance position */
        buf_pos = (buf_pos + 1) % win;

        /* Output volatility */
        vol_out[i] = sqrt(sum_var / (double)win) * ann_factor;
    }

    free(gk_buf);
    return VOLATILITY_OK;
}

HOT_FUNC
int volatility_rogers_satchell(
    const int64_t* RESTRICT open_ticks,
    const int64_t* RESTRICT high_ticks,
    const int64_t* RESTRICT low_ticks,
    const int64_t* RESTRICT close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* RESTRICT vol_out
) {
    if (UNLIKELY(!open_ticks || !high_ticks || !low_ticks || !close_ticks || !vol_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(window <= 0 || (size_t)window > count)) {
        return VOLATILITY_ERR_WINDOW;
    }

    size_t win = (size_t)window;
    double ann_factor = annualize ? ANNUALIZE_FACTOR : 1.0;

    /* Fill initial values with 0 */
    for (size_t i = 0; i < win - 1 && i < count; i++) {
        vol_out[i] = 0.0;
    }

    if (count < win) {
        return VOLATILITY_OK;
    }

    /* Allocate circular buffer */
    double* rs_buf = (double*)malloc(win * sizeof(double));
    if (UNLIKELY(!rs_buf)) {
        return VOLATILITY_ERR_NOMEM;
    }

    /* Initialize buffer and running sum
     * Rogers-Satchell: sigma^2 = ln(H/C)*ln(H/O) + ln(L/C)*ln(L/O) */
    double sum_var = 0.0;
    for (size_t i = 0; i < win; i++) {
        double var_term = 0.0;
        if (LIKELY(open_ticks[i] > 0 && low_ticks[i] > 0 && close_ticks[i] > 0)) {
            double o = (double)open_ticks[i];
            double h = (double)high_ticks[i];
            double l = (double)low_ticks[i];
            double c = (double)close_ticks[i];
            var_term = log(h/c) * log(h/o) + log(l/c) * log(l/o);
        }
        rs_buf[i] = var_term;
        sum_var += var_term;
    }

    /* First valid volatility */
    double var_est = sum_var / (double)win;
    vol_out[win - 1] = (var_est > 0.0) ? sqrt(var_est) * ann_factor : 0.0;

    /* Rolling calculation with O(1) updates */
    size_t buf_pos = 0;
    for (size_t i = win; i < count; i++) {
        PREFETCH(&open_ticks[i + 8]);
        PREFETCH(&high_ticks[i + 8]);
        PREFETCH(&low_ticks[i + 8]);
        PREFETCH(&close_ticks[i + 8]);

        /* Remove oldest */
        sum_var -= rs_buf[buf_pos];

        /* Add new */
        double var_term = 0.0;
        if (LIKELY(open_ticks[i] > 0 && low_ticks[i] > 0 && close_ticks[i] > 0)) {
            double o = (double)open_ticks[i];
            double h = (double)high_ticks[i];
            double l = (double)low_ticks[i];
            double c = (double)close_ticks[i];
            var_term = log(h/c) * log(h/o) + log(l/c) * log(l/o);
        }
        rs_buf[buf_pos] = var_term;
        sum_var += var_term;

        /* Advance position */
        buf_pos = (buf_pos + 1) % win;

        /* Output volatility */
        var_est = sum_var / (double)win;
        vol_out[i] = (var_est > 0.0) ? sqrt(var_est) * ann_factor : 0.0;
    }

    free(rs_buf);
    return VOLATILITY_OK;
}

HOT_FUNC
int volatility_yang_zhang(
    const int64_t* RESTRICT open_ticks,
    const int64_t* RESTRICT high_ticks,
    const int64_t* RESTRICT low_ticks,
    const int64_t* RESTRICT close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* RESTRICT vol_out
) {
    if (UNLIKELY(!open_ticks || !high_ticks || !low_ticks || !close_ticks || !vol_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(window <= 1 || (size_t)window > count)) {
        return VOLATILITY_ERR_WINDOW;
    }

    size_t win = (size_t)window;
    double ann_factor = annualize ? ANNUALIZE_FACTOR : 1.0;

    /* Fill initial values with 0 (need i >= 1 for overnight return) */
    for (size_t i = 0; i <= win && i < count; i++) {
        vol_out[i] = 0.0;
    }

    if (count <= win + 1) {
        return VOLATILITY_OK;
    }

    /* Yang-Zhang combines:
     * - Overnight variance (close[i-1] to open[i])
     * - Open-to-close variance
     * - Rogers-Satchell variance
     * sigma^2_yz = sigma^2_o + k*sigma^2_c + (1-k)*sigma^2_rs
     * k = 0.34 / (1.34 + (n+1)/(n-1))
     */
    double k = 0.34 / (1.34 + (double)(win + 1) / (double)(win - 1));

    /* Allocate buffers for three variance components */
    double* overnight_buf = (double*)malloc(win * sizeof(double));
    double* oc_buf = (double*)malloc(win * sizeof(double));
    double* rs_buf = (double*)malloc(win * sizeof(double));

    if (UNLIKELY(!overnight_buf || !oc_buf || !rs_buf)) {
        free(overnight_buf);
        free(oc_buf);
        free(rs_buf);
        return VOLATILITY_ERR_NOMEM;
    }

    /* Initialize Welford states for overnight and OC, simple sum for RS */
    welford_t overnight_w, oc_w;
    welford_init(&overnight_w);
    welford_init(&oc_w);
    double rs_sum = 0.0;

    /* Fill initial window (starting from i=1 since we need prev close) */
    for (size_t i = 1; i <= win; i++) {
        /* Overnight: log(open[i] / close[i-1]) */
        double log_overnight = calc_log_return(close_ticks[i - 1], open_ticks[i]);
        overnight_buf[i - 1] = log_overnight;
        welford_update(&overnight_w, log_overnight);

        /* Open-to-close: log(close[i] / open[i]) */
        double log_oc = calc_log_return(open_ticks[i], close_ticks[i]);
        oc_buf[i - 1] = log_oc;
        welford_update(&oc_w, log_oc);

        /* Rogers-Satchell */
        double rs_term = 0.0;
        if (LIKELY(open_ticks[i] > 0 && low_ticks[i] > 0 && close_ticks[i] > 0)) {
            double o = (double)open_ticks[i];
            double h = (double)high_ticks[i];
            double l = (double)low_ticks[i];
            double c = (double)close_ticks[i];
            rs_term = log(h/c) * log(h/o) + log(l/c) * log(l/o);
        }
        rs_buf[i - 1] = rs_term;
        rs_sum += rs_term;
    }

    /* Calculate first valid volatility */
    double sigma_o = welford_variance(&overnight_w);
    double sigma_c = welford_variance(&oc_w);
    double sigma_rs = rs_sum / (double)win;
    double total_var = sigma_o + k * sigma_c + (1.0 - k) * sigma_rs;
    if (total_var < 0.0) total_var = 0.0;
    vol_out[win] = sqrt(total_var) * ann_factor;

    /* Rolling calculation with O(1) Welford updates */
    size_t buf_pos = 0;
    for (size_t i = win + 1; i < count; i++) {
        PREFETCH(&open_ticks[i + 8]);
        PREFETCH(&high_ticks[i + 8]);
        PREFETCH(&low_ticks[i + 8]);
        PREFETCH(&close_ticks[i + 8]);

        /* Remove oldest values */
        welford_remove(&overnight_w, overnight_buf[buf_pos]);
        welford_remove(&oc_w, oc_buf[buf_pos]);
        rs_sum -= rs_buf[buf_pos];

        /* Add new values */
        double log_overnight = calc_log_return(close_ticks[i - 1], open_ticks[i]);
        overnight_buf[buf_pos] = log_overnight;
        welford_update(&overnight_w, log_overnight);

        double log_oc = calc_log_return(open_ticks[i], close_ticks[i]);
        oc_buf[buf_pos] = log_oc;
        welford_update(&oc_w, log_oc);

        double rs_term = 0.0;
        if (LIKELY(open_ticks[i] > 0 && low_ticks[i] > 0 && close_ticks[i] > 0)) {
            double o = (double)open_ticks[i];
            double h = (double)high_ticks[i];
            double l = (double)low_ticks[i];
            double c = (double)close_ticks[i];
            rs_term = log(h/c) * log(h/o) + log(l/c) * log(l/o);
        }
        rs_buf[buf_pos] = rs_term;
        rs_sum += rs_term;

        /* Advance position */
        buf_pos = (buf_pos + 1) % win;

        /* Calculate and output volatility */
        sigma_o = welford_variance(&overnight_w);
        sigma_c = welford_variance(&oc_w);
        sigma_rs = rs_sum / (double)win;
        total_var = sigma_o + k * sigma_c + (1.0 - k) * sigma_rs;
        if (total_var < 0.0) total_var = 0.0;
        vol_out[i] = sqrt(total_var) * ann_factor;
    }

    free(overnight_buf);
    free(oc_buf);
    free(rs_buf);
    return VOLATILITY_OK;
}

HOT_FUNC
int volatility_ewma(
    const int64_t* RESTRICT close_ticks,
    size_t count,
    double lambda,
    bool annualize,
    double* RESTRICT vol_out
) {
    if (UNLIKELY(!close_ticks || !vol_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(lambda <= 0.0 || lambda >= 1.0)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(count < 2)) {
        return VOLATILITY_ERR_EMPTY;
    }

    double ann_factor = annualize ? ANNUALIZE_FACTOR : 1.0;
    double one_minus_lambda = 1.0 - lambda;

    vol_out[0] = 0.0;

    /* Initial variance from first return */
    double ret = calc_log_return(close_ticks[0], close_ticks[1]);
    double variance = ret * ret;

    vol_out[1] = sqrt(variance) * ann_factor;

    /* EWMA: sigma^2_t = lambda * sigma^2_{t-1} + (1 - lambda) * r^2_t */
    for (size_t i = 2; i < count; i++) {
        PREFETCH(&close_ticks[i + 8]);

        ret = calc_log_return(close_ticks[i - 1], close_ticks[i]);
        variance = lambda * variance + one_minus_lambda * ret * ret;
        vol_out[i] = sqrt(variance) * ann_factor;
    }

    return VOLATILITY_OK;
}

HOT_FUNC
int atr_calculate(
    const int64_t* RESTRICT high_ticks,
    const int64_t* RESTRICT low_ticks,
    const int64_t* RESTRICT close_ticks,
    size_t count,
    int period,
    double tick_size,
    double* RESTRICT atr_out
) {
    if (UNLIKELY(!high_ticks || !low_ticks || !close_ticks || !atr_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(period <= 0 || (size_t)period > count)) {
        return VOLATILITY_ERR_WINDOW;
    }
    if (UNLIKELY(tick_size <= 0.0)) {
        return VOLATILITY_ERR_PARAM;
    }

    size_t win = (size_t)period;

    /* Fill initial values with 0 */
    for (size_t i = 0; i < win - 1 && i < count; i++) {
        atr_out[i] = 0.0;
    }

    if (count < win) {
        return VOLATILITY_OK;
    }

    /* Allocate circular buffer for true ranges */
    double* tr_buf = (double*)malloc(win * sizeof(double));
    if (UNLIKELY(!tr_buf)) {
        return VOLATILITY_ERR_NOMEM;
    }

    /* Calculate TR for first element: TR = H - L */
    tr_buf[0] = (double)(high_ticks[0] - low_ticks[0]) * tick_size;
    double sum_tr = tr_buf[0];

    /* Fill initial window */
    for (size_t i = 1; i < win; i++) {
        int64_t h = high_ticks[i];
        int64_t l = low_ticks[i];
        int64_t prev_c = close_ticks[i - 1];

        /* True Range = max(H-L, |H-prevC|, |L-prevC|) */
        int64_t hl = h - l;
        int64_t h_pc = h - prev_c; if (h_pc < 0) h_pc = -h_pc;
        int64_t l_pc = l - prev_c; if (l_pc < 0) l_pc = -l_pc;

        int64_t tr = hl;
        if (h_pc > tr) tr = h_pc;
        if (l_pc > tr) tr = l_pc;

        double tr_d = (double)tr * tick_size;
        tr_buf[i] = tr_d;
        sum_tr += tr_d;
    }

    /* First valid ATR (simple moving average) */
    atr_out[win - 1] = sum_tr / (double)win;

    /* Rolling calculation with O(1) updates */
    size_t buf_pos = 0;
    for (size_t i = win; i < count; i++) {
        PREFETCH(&high_ticks[i + 8]);
        PREFETCH(&low_ticks[i + 8]);
        PREFETCH(&close_ticks[i + 7]);

        /* Remove oldest */
        sum_tr -= tr_buf[buf_pos];

        /* Calculate new TR */
        int64_t h = high_ticks[i];
        int64_t l = low_ticks[i];
        int64_t prev_c = close_ticks[i - 1];

        int64_t hl = h - l;
        int64_t h_pc = h - prev_c; if (h_pc < 0) h_pc = -h_pc;
        int64_t l_pc = l - prev_c; if (l_pc < 0) l_pc = -l_pc;

        int64_t tr = hl;
        if (h_pc > tr) tr = h_pc;
        if (l_pc > tr) tr = l_pc;

        double tr_d = (double)tr * tick_size;
        tr_buf[buf_pos] = tr_d;
        sum_tr += tr_d;

        /* Advance position */
        buf_pos = (buf_pos + 1) % win;

        /* Output ATR */
        atr_out[i] = sum_tr / (double)win;
    }

    free(tr_buf);
    return VOLATILITY_OK;
}

HOT_FUNC
int true_range_calculate(
    const int64_t* RESTRICT high_ticks,
    const int64_t* RESTRICT low_ticks,
    const int64_t* RESTRICT close_ticks,
    size_t count,
    double tick_size,
    double* RESTRICT tr_out
) {
    if (UNLIKELY(!high_ticks || !low_ticks || !close_ticks || !tr_out)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(tick_size <= 0.0)) {
        return VOLATILITY_ERR_PARAM;
    }
    if (UNLIKELY(count == 0)) {
        return VOLATILITY_ERR_EMPTY;
    }

    /* First candle: TR = H - L */
    tr_out[0] = (double)(high_ticks[0] - low_ticks[0]) * tick_size;

    /* Subsequent candles: TR = max(H-L, |H-prevC|, |L-prevC|) */
    for (size_t i = 1; i < count; i++) {
        PREFETCH(&high_ticks[i + 8]);
        PREFETCH(&low_ticks[i + 8]);
        PREFETCH(&close_ticks[i + 7]);

        int64_t h = high_ticks[i];
        int64_t l = low_ticks[i];
        int64_t prev_c = close_ticks[i - 1];

        int64_t hl = h - l;
        int64_t h_pc = h - prev_c; if (h_pc < 0) h_pc = -h_pc;
        int64_t l_pc = l - prev_c; if (l_pc < 0) l_pc = -l_pc;

        int64_t tr = hl;
        if (h_pc > tr) tr = h_pc;
        if (l_pc > tr) tr = l_pc;

        tr_out[i] = (double)tr * tick_size;
    }

    return VOLATILITY_OK;
}

/* ========== Streaming Volatility API ========== */

volatility_state_t* volatility_state_new(
    volatility_method_t method,
    int window,
    double param,
    bool annualize
) {
    if (method != VOL_METHOD_EWMA && window <= 0) {
        return NULL;
    }

    volatility_state_t* state = (volatility_state_t*)calloc(1, sizeof(volatility_state_t));
    if (!state) {
        return NULL;
    }

    state->method = method;
    state->window = window;
    state->param = param;
    state->annualize = annualize ? 1 : 0;
    state->count = 0;
    state->initialized = 0;
    state->ewma_var = 0.0;
    state->prev_close = 0.0;
    state->rs_sum = 0.0;
    state->buffer2 = NULL;
    state->buffer3 = NULL;

    welford_init(&state->welford);
    welford_init(&state->welford2);

    /* Allocate buffer for windowed methods */
    if (method != VOL_METHOD_EWMA && window > 0) {
        state->buffer_size = (size_t)window;
        state->buffer = (double*)calloc(state->buffer_size, sizeof(double));
        if (!state->buffer) {
            free(state);
            return NULL;
        }
        state->buffer_idx = 0;

        /* Yang-Zhang needs additional buffers */
        if (method == VOL_METHOD_YANG_ZHANG) {
            state->buffer2 = (double*)calloc(state->buffer_size, sizeof(double));
            state->buffer3 = (double*)calloc(state->buffer_size, sizeof(double));
            if (!state->buffer2 || !state->buffer3) {
                free(state->buffer);
                free(state->buffer2);
                free(state->buffer3);
                free(state);
                return NULL;
            }
        }
    } else {
        state->buffer = NULL;
        state->buffer_size = 0;
        state->buffer_idx = 0;
    }

    return state;
}

void volatility_state_free(volatility_state_t* state) {
    if (state) {
        free(state->buffer);
        free(state->buffer2);
        free(state->buffer3);
        free(state);
    }
}

void volatility_state_reset(volatility_state_t* state) {
    if (state) {
        state->count = 0;
        state->initialized = 0;
        state->ewma_var = 0.0;
        state->prev_close = 0.0;
        state->buffer_idx = 0;
        state->rs_sum = 0.0;

        welford_init(&state->welford);
        welford_init(&state->welford2);

        if (state->buffer) {
            memset(state->buffer, 0, state->buffer_size * sizeof(double));
        }
        if (state->buffer2) {
            memset(state->buffer2, 0, state->buffer_size * sizeof(double));
        }
        if (state->buffer3) {
            memset(state->buffer3, 0, state->buffer_size * sizeof(double));
        }
    }
}

HOT_FUNC
double volatility_state_update(
    volatility_state_t* state,
    int64_t open_tick,
    int64_t high_tick,
    int64_t low_tick,
    int64_t close_tick
) {
    if (UNLIKELY(!state)) {
        return NAN;
    }

    double ann_factor = state->annualize ? ANNUALIZE_FACTOR : 1.0;
    size_t win = state->buffer_size;

    switch (state->method) {
        case VOL_METHOD_REALIZED: {
            if (!state->initialized) {
                state->prev_close = (double)close_tick;
                state->initialized = 1;
                return NAN;
            }

            double ret = calc_log_return((int64_t)state->prev_close, close_tick);
            state->prev_close = (double)close_tick;

            if (state->count < win) {
                /* Still filling window */
                state->buffer[state->count] = ret;
                welford_update(&state->welford, ret);
                state->count++;
                if (state->count < win) {
                    return NAN;
                }
            } else {
                /* Window full - remove oldest, add newest */
                double old_ret = state->buffer[state->buffer_idx];
                welford_remove(&state->welford, old_ret);
                state->buffer[state->buffer_idx] = ret;
                welford_update(&state->welford, ret);
                state->buffer_idx = (state->buffer_idx + 1) % win;
            }
            return welford_stddev(&state->welford) * ann_factor;
        }

        case VOL_METHOD_PARKINSON: {
            double log_hl = (low_tick > 0) ? log((double)high_tick / (double)low_tick) : 0.0;
            double sq = log_hl * log_hl;

            if (state->count < win) {
                state->buffer[state->count] = sq;
                state->rs_sum += sq;  /* Reuse rs_sum for running sum */
                state->count++;
                if (state->count < win) {
                    state->initialized = 1;
                    return NAN;
                }
            } else {
                state->rs_sum -= state->buffer[state->buffer_idx];
                state->buffer[state->buffer_idx] = sq;
                state->rs_sum += sq;
                state->buffer_idx = (state->buffer_idx + 1) % win;
            }
            state->initialized = 1;
            return sqrt(state->rs_sum / (double)win) * SQRT_INV_4_LN2 * ann_factor;
        }

        case VOL_METHOD_GARMAN_KLASS: {
            double var_term = 0.0;
            if (LIKELY(low_tick > 0 && open_tick > 0)) {
                double log_hl = log((double)high_tick / (double)low_tick);
                double log_co = log((double)close_tick / (double)open_tick);
                var_term = 0.5 * log_hl * log_hl - TWO_LN2_MINUS_1 * log_co * log_co;
                if (var_term < 0.0) var_term = 0.0;
            }

            if (state->count < win) {
                state->buffer[state->count] = var_term;
                state->rs_sum += var_term;
                state->count++;
                if (state->count < win) {
                    state->initialized = 1;
                    return NAN;
                }
            } else {
                state->rs_sum -= state->buffer[state->buffer_idx];
                state->buffer[state->buffer_idx] = var_term;
                state->rs_sum += var_term;
                state->buffer_idx = (state->buffer_idx + 1) % win;
            }
            state->initialized = 1;
            return sqrt(state->rs_sum / (double)win) * ann_factor;
        }

        case VOL_METHOD_ROGERS_SATCHELL: {
            double var_term = 0.0;
            if (LIKELY(open_tick > 0 && low_tick > 0 && close_tick > 0)) {
                double o = (double)open_tick;
                double h = (double)high_tick;
                double l = (double)low_tick;
                double c = (double)close_tick;
                var_term = log(h/c) * log(h/o) + log(l/c) * log(l/o);
            }

            if (state->count < win) {
                state->buffer[state->count] = var_term;
                state->rs_sum += var_term;
                state->count++;
                if (state->count < win) {
                    state->initialized = 1;
                    return NAN;
                }
            } else {
                state->rs_sum -= state->buffer[state->buffer_idx];
                state->buffer[state->buffer_idx] = var_term;
                state->rs_sum += var_term;
                state->buffer_idx = (state->buffer_idx + 1) % win;
            }
            state->initialized = 1;
            double var_est = state->rs_sum / (double)win;
            return (var_est > 0.0) ? sqrt(var_est) * ann_factor : 0.0;
        }

        case VOL_METHOD_YANG_ZHANG: {
            if (!state->initialized) {
                state->prev_close = (double)close_tick;
                state->initialized = 1;
                return NAN;
            }

            /* Calculate three components */
            double log_overnight = calc_log_return((int64_t)state->prev_close, open_tick);
            double log_oc = calc_log_return(open_tick, close_tick);

            double rs_term = 0.0;
            if (LIKELY(open_tick > 0 && low_tick > 0 && close_tick > 0)) {
                double o = (double)open_tick;
                double h = (double)high_tick;
                double l = (double)low_tick;
                double c = (double)close_tick;
                rs_term = log(h/c) * log(h/o) + log(l/c) * log(l/o);
            }

            state->prev_close = (double)close_tick;

            if (state->count < win) {
                state->buffer[state->count] = log_overnight;
                state->buffer2[state->count] = log_oc;
                state->buffer3[state->count] = rs_term;
                welford_update(&state->welford, log_overnight);
                welford_update(&state->welford2, log_oc);
                state->rs_sum += rs_term;
                state->count++;
                if (state->count < win) {
                    return NAN;
                }
            } else {
                /* Remove oldest */
                welford_remove(&state->welford, state->buffer[state->buffer_idx]);
                welford_remove(&state->welford2, state->buffer2[state->buffer_idx]);
                state->rs_sum -= state->buffer3[state->buffer_idx];

                /* Add newest */
                state->buffer[state->buffer_idx] = log_overnight;
                state->buffer2[state->buffer_idx] = log_oc;
                state->buffer3[state->buffer_idx] = rs_term;
                welford_update(&state->welford, log_overnight);
                welford_update(&state->welford2, log_oc);
                state->rs_sum += rs_term;

                state->buffer_idx = (state->buffer_idx + 1) % win;
            }

            double k = 0.34 / (1.34 + (double)(win + 1) / (double)(win - 1));
            double sigma_o = welford_variance(&state->welford);
            double sigma_c = welford_variance(&state->welford2);
            double sigma_rs = state->rs_sum / (double)win;
            double total_var = sigma_o + k * sigma_c + (1.0 - k) * sigma_rs;
            if (total_var < 0.0) total_var = 0.0;
            return sqrt(total_var) * ann_factor;
        }

        case VOL_METHOD_EWMA: {
            if (!state->initialized) {
                state->prev_close = (double)close_tick;
                state->initialized = 1;
                return NAN;
            }

            double ret = calc_log_return((int64_t)state->prev_close, close_tick);
            state->prev_close = (double)close_tick;

            if (state->count == 0) {
                /* First return - seed variance */
                state->ewma_var = ret * ret;
                state->count = 1;
            } else {
                /* EWMA update */
                state->ewma_var = state->param * state->ewma_var +
                                  (1.0 - state->param) * ret * ret;
            }
            return sqrt(state->ewma_var) * ann_factor;
        }

        default:
            return NAN;
    }
}

double volatility_state_current(const volatility_state_t* state) {
    if (!state || !state->initialized) {
        return NAN;
    }

    double ann_factor = state->annualize ? ANNUALIZE_FACTOR : 1.0;
    size_t win = state->buffer_size;

    switch (state->method) {
        case VOL_METHOD_REALIZED:
            if (state->count < win) return NAN;
            return welford_stddev(&state->welford) * ann_factor;

        case VOL_METHOD_PARKINSON:
            if (state->count < win) return NAN;
            return sqrt(state->rs_sum / (double)win) * SQRT_INV_4_LN2 * ann_factor;

        case VOL_METHOD_GARMAN_KLASS:
            if (state->count < win) return NAN;
            return sqrt(state->rs_sum / (double)win) * ann_factor;

        case VOL_METHOD_ROGERS_SATCHELL: {
            if (state->count < win) return NAN;
            double var_est = state->rs_sum / (double)win;
            return (var_est > 0.0) ? sqrt(var_est) * ann_factor : 0.0;
        }

        case VOL_METHOD_YANG_ZHANG: {
            if (state->count < win) return NAN;
            double k = 0.34 / (1.34 + (double)(win + 1) / (double)(win - 1));
            double sigma_o = welford_variance(&state->welford);
            double sigma_c = welford_variance(&state->welford2);
            double sigma_rs = state->rs_sum / (double)win;
            double total_var = sigma_o + k * sigma_c + (1.0 - k) * sigma_rs;
            if (total_var < 0.0) total_var = 0.0;
            return sqrt(total_var) * ann_factor;
        }

        case VOL_METHOD_EWMA:
            if (state->count == 0) return NAN;
            return sqrt(state->ewma_var) * ann_factor;

        default:
            return NAN;
    }
}
