/**
 * Volume Analysis Module
 *
 * Provides functions for volume-based analytics including:
 * - VWAP (Volume-Weighted Average Price)
 * - Volume profiles (price distribution)
 * - Cumulative delta (buy vs sell pressure)
 * - OBV (On-Balance Volume)
 */

#ifndef AG_KERNEL_VOLUME_H
#define AG_KERNEL_VOLUME_H

#include <stdint.h>
#include <stddef.h>
#include "types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Error codes */
#define VOLUME_OK             0
#define VOLUME_ERR_PARAM     -1
#define VOLUME_ERR_NOMEM     -2
#define VOLUME_ERR_EMPTY     -3

/**
 * Volume profile bin structure
 */
typedef struct {
    int64_t price_tick;      /* Price level in ticks */
    double volume;           /* Total volume at this level */
    double buy_volume;       /* Buy-side volume */
    double sell_volume;      /* Sell-side volume */
} volume_bin_t;

/**
 * Volume profile result structure
 */
typedef struct {
    volume_bin_t* bins;      /* Array of volume bins */
    size_t num_bins;         /* Number of bins */
    int64_t poc_tick;        /* Point of Control (highest volume price) */
    int64_t vah_tick;        /* Value Area High */
    int64_t val_tick;        /* Value Area Low */
    double total_volume;     /* Total volume in profile */
} volume_profile_t;

/**
 * Calculate VWAP for tick data.
 *
 * @param timestamps   Array of tick timestamps (ms)
 * @param price_ticks  Array of prices in ticks
 * @param qtys         Array of quantities
 * @param count        Number of ticks
 * @param tick_size    Tick size for price conversion
 * @param vwap_out     Output array for VWAP values (same length as input)
 * @return VOLUME_OK on success, negative error code on failure
 */
int vwap_calculate(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    size_t count,
    double tick_size,
    double* vwap_out
);

/**
 * Calculate session VWAP (resets at each new session).
 * A new session starts when timestamp crosses a day boundary (UTC).
 *
 * @param timestamps   Array of tick timestamps (ms)
 * @param price_ticks  Array of prices in ticks
 * @param qtys         Array of quantities
 * @param count        Number of ticks
 * @param tick_size    Tick size for price conversion
 * @param vwap_out     Output array for VWAP values
 * @return VOLUME_OK on success, negative error code on failure
 */
int vwap_session_calculate(
    const int64_t* timestamps,
    const int64_t* price_ticks,
    const double* qtys,
    size_t count,
    double tick_size,
    double* vwap_out
);

/**
 * Build a volume profile from tick data.
 *
 * @param price_ticks   Array of prices in ticks
 * @param qtys          Array of quantities
 * @param sides         Array of sides (0=buy, 1=sell)
 * @param count         Number of ticks
 * @param tick_size     Tick size for price conversion
 * @param num_bins      Number of bins for the profile
 * @param value_area_pct Value area percentage (e.g., 70.0 for 70%)
 * @param profile_out   Output profile structure
 * @return VOLUME_OK on success, negative error code on failure
 */
int volume_profile_build(
    const int64_t* price_ticks,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    double tick_size,
    size_t num_bins,
    double value_area_pct,
    volume_profile_t* profile_out
);

/**
 * Free memory allocated for a volume profile.
 *
 * @param profile  Profile to free
 */
void volume_profile_free(volume_profile_t* profile);

/**
 * Calculate cumulative delta (buy volume - sell volume).
 *
 * @param qtys         Array of quantities
 * @param sides        Array of sides (0=buy, 1=sell)
 * @param count        Number of ticks
 * @param delta_out    Output array for cumulative delta values
 * @return VOLUME_OK on success, negative error code on failure
 */
int cumulative_delta_calculate(
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    double* delta_out
);

/**
 * Calculate delta per candle period.
 *
 * @param timestamps   Array of tick timestamps (ms)
 * @param qtys         Array of quantities
 * @param sides        Array of sides (0=buy, 1=sell)
 * @param count        Number of ticks
 * @param interval_ms  Candle interval in milliseconds
 * @param delta_out    Output array for delta values (per candle)
 * @param max_candles  Maximum output size
 * @return Number of values written, or negative error code
 */
int64_t delta_per_candle(
    const int64_t* timestamps,
    const double* qtys,
    const uint8_t* sides,
    size_t count,
    int64_t interval_ms,
    double* delta_out,
    size_t max_candles
);

/**
 * Calculate On-Balance Volume (OBV).
 * OBV adds volume on up-ticks, subtracts on down-ticks.
 *
 * @param price_ticks  Array of prices in ticks
 * @param qtys         Array of quantities
 * @param count        Number of ticks
 * @param obv_out      Output array for OBV values
 * @return VOLUME_OK on success, negative error code on failure
 */
int obv_calculate(
    const int64_t* price_ticks,
    const double* qtys,
    size_t count,
    double* obv_out
);

/**
 * Calculate Money Flow Index (MFI).
 * Similar to RSI but volume-weighted.
 *
 * @param high_ticks   Array of high prices in ticks
 * @param low_ticks    Array of low prices in ticks
 * @param close_ticks  Array of close prices in ticks
 * @param volumes      Array of volumes
 * @param count        Number of candles
 * @param period       Lookback period (typically 14)
 * @param mfi_out      Output array for MFI values
 * @return VOLUME_OK on success, negative error code on failure
 */
int mfi_calculate(
    const int64_t* high_ticks,
    const int64_t* low_ticks,
    const int64_t* close_ticks,
    const double* volumes,
    size_t count,
    int period,
    double* mfi_out
);

#ifdef __cplusplus
}
#endif

#endif /* AG_KERNEL_VOLUME_H */
