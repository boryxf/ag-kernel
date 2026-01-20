/**
 * Volatility Calculation Module
 *
 * Provides various volatility estimators including:
 * - Realized (Close-to-Close)
 * - Parkinson (High-Low)
 * - Garman-Klass
 * - Rogers-Satchell
 * - Yang-Zhang
 * - EWMA (Exponentially Weighted)
 * - ATR (Average True Range)
 */

#ifndef AG_KERNEL_VOLATILITY_H
#define AG_KERNEL_VOLATILITY_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Error codes */
#define VOLATILITY_OK             0
#define VOLATILITY_ERR_PARAM     -1
#define VOLATILITY_ERR_NOMEM     -2
#define VOLATILITY_ERR_EMPTY     -3
#define VOLATILITY_ERR_WINDOW    -4

/**
 * Volatility calculation method
 */
typedef enum {
    VOL_METHOD_REALIZED = 0,      /* Close-to-close returns */
    VOL_METHOD_PARKINSON = 1,     /* High-Low range */
    VOL_METHOD_GARMAN_KLASS = 2,  /* Uses OHLC */
    VOL_METHOD_ROGERS_SATCHELL = 3,
    VOL_METHOD_YANG_ZHANG = 4,    /* Most efficient OHLC estimator */
    VOL_METHOD_EWMA = 5           /* Exponentially weighted */
} volatility_method_t;

/**
 * Streaming volatility state for incremental calculation
 */
typedef struct volatility_state_s volatility_state_t;

/**
 * Calculate realized volatility (close-to-close).
 *
 * @param close_ticks  Array of close prices in ticks
 * @param count        Number of candles
 * @param window       Rolling window size
 * @param annualize    If true, annualize the result (assume 365 days)
 * @param vol_out      Output array for volatility values
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int volatility_realized(
    const int64_t* close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* vol_out
);

/**
 * Calculate Parkinson volatility (high-low range estimator).
 * More efficient than realized volatility.
 *
 * @param high_ticks   Array of high prices in ticks
 * @param low_ticks    Array of low prices in ticks
 * @param count        Number of candles
 * @param window       Rolling window size
 * @param annualize    If true, annualize the result
 * @param vol_out      Output array for volatility values
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int volatility_parkinson(
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    size_t count,
    int window,
    bool annualize,
    double* vol_out
);

/**
 * Calculate Garman-Klass volatility.
 * Uses OHLC data for improved efficiency.
 *
 * @param open_ticks   Array of open prices in ticks
 * @param high_ticks   Array of high prices in ticks
 * @param low_ticks    Array of low prices in ticks
 * @param close_ticks  Array of close prices in ticks
 * @param count        Number of candles
 * @param window       Rolling window size
 * @param annualize    If true, annualize the result
 * @param vol_out      Output array for volatility values
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int volatility_garman_klass(
    const int64_t* open_ticks,
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    const int64_t* close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* vol_out
);

/**
 * Calculate Rogers-Satchell volatility.
 * Handles drift in returns.
 *
 * @param open_ticks   Array of open prices in ticks
 * @param high_ticks   Array of high prices in ticks
 * @param low_ticks    Array of low prices in ticks
 * @param close_ticks  Array of close prices in ticks
 * @param count        Number of candles
 * @param window       Rolling window size
 * @param annualize    If true, annualize the result
 * @param vol_out      Output array for volatility values
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int volatility_rogers_satchell(
    const int64_t* open_ticks,
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    const int64_t* close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* vol_out
);

/**
 * Calculate Yang-Zhang volatility.
 * Most efficient unbiased OHLC estimator.
 *
 * @param open_ticks   Array of open prices in ticks
 * @param high_ticks   Array of high prices in ticks
 * @param low_ticks    Array of low prices in ticks
 * @param close_ticks  Array of close prices in ticks
 * @param count        Number of candles
 * @param window       Rolling window size
 * @param annualize    If true, annualize the result
 * @param vol_out      Output array for volatility values
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int volatility_yang_zhang(
    const int64_t* open_ticks,
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    const int64_t* close_ticks,
    size_t count,
    int window,
    bool annualize,
    double* vol_out
);

/**
 * Calculate EWMA (Exponentially Weighted Moving Average) volatility.
 *
 * @param close_ticks  Array of close prices in ticks
 * @param count        Number of candles
 * @param lambda       Decay factor (typical: 0.94 for daily, 0.97 for weekly)
 * @param annualize    If true, annualize the result
 * @param vol_out      Output array for volatility values
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int volatility_ewma(
    const int64_t* close_ticks,
    size_t count,
    double lambda,
    bool annualize,
    double* vol_out
);

/**
 * Calculate Average True Range (ATR).
 *
 * @param high_ticks   Array of high prices in ticks
 * @param low_ticks    Array of low prices in ticks
 * @param close_ticks  Array of close prices in ticks
 * @param count        Number of candles
 * @param period       ATR period (typically 14)
 * @param tick_size    Tick size for price conversion
 * @param atr_out      Output array for ATR values (in price units)
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int atr_calculate(
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    const int64_t* close_ticks,
    size_t count,
    int period,
    double tick_size,
    double* atr_out
);

/**
 * Calculate True Range for each candle.
 *
 * @param high_ticks   Array of high prices in ticks
 * @param low_ticks    Array of low prices in ticks
 * @param close_ticks  Array of close prices in ticks
 * @param count        Number of candles
 * @param tick_size    Tick size for price conversion
 * @param tr_out       Output array for true range values
 * @return VOLATILITY_OK on success, negative error code on failure
 */
int true_range_calculate(
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    const int64_t* close_ticks,
    size_t count,
    double tick_size,
    double* tr_out
);

/* ========== Streaming Volatility API ========== */

/**
 * Create a new streaming volatility calculator.
 *
 * @param method      Volatility calculation method
 * @param window      Window size (ignored for EWMA)
 * @param param       Method-specific parameter (lambda for EWMA, ignored otherwise)
 * @param annualize   If true, annualize results
 * @return New state handle, or NULL on error
 */
volatility_state_t* volatility_state_new(
    volatility_method_t method,
    int window,
    double param,
    bool annualize
);

/**
 * Free a volatility state.
 *
 * @param state  State handle to free
 */
void volatility_state_free(volatility_state_t* state);

/**
 * Reset volatility state for a new calculation.
 *
 * @param state  State handle
 */
void volatility_state_reset(volatility_state_t* state);

/**
 * Update streaming volatility with a new candle.
 *
 * @param state       State handle
 * @param open_tick   Open price in ticks
 * @param high_tick   High price in ticks
 * @param low_tick    Low price in ticks
 * @param close_tick  Close price in ticks
 * @return Current volatility estimate, or NaN if insufficient data
 */
double volatility_state_update(
    volatility_state_t* state,
    int64_t open_tick,
    int64_t high_tick,
    int64_t low_tick,
    int64_t close_tick
);

/**
 * Get current volatility estimate without adding new data.
 *
 * @param state  State handle
 * @return Current volatility estimate, or NaN if insufficient data
 */
double volatility_state_current(const volatility_state_t* state);

#ifdef __cplusplus
}
#endif

#endif /* AG_KERNEL_VOLATILITY_H */
