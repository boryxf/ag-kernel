/*
 * Fixed-Point Arithmetic Library for ag-kernel
 *
 * This header provides 64-bit fixed-point arithmetic with 8 decimal places
 * of precision for high-performance, deterministic financial calculations.
 *
 * Type: fixed64_t (int64_t with implicit scaling)
 * Range: -92,233,720,368.54775808 to +92,233,720,368.54775807
 * Precision: 0.00000001 (1e-8)
 *
 * Usage: This is an OPTIONAL alternative to double-precision arithmetic.
 * The double-precision engine (engine.c) remains the default.
 */

#ifndef AG_KERNEL_FIXED_POINT_H
#define AG_KERNEL_FIXED_POINT_H

#include <stdint.h>

/* ---------------------------------------------------------------------
 * Fixed-point type definition
 * --------------------------------------------------------------------- */

typedef int64_t fixed64_t;

/* ---------------------------------------------------------------------
 * Scale constants
 * --------------------------------------------------------------------- */

#define FIXED_SCALE         100000000LL     /* 1e8 - 8 decimal places */
#define FIXED_HALF_SCALE    50000000LL      /* For rounding */

/* ---------------------------------------------------------------------
 * Common constants
 * --------------------------------------------------------------------- */

#define FIXED_ZERO          0LL
#define FIXED_ONE           FIXED_SCALE                 /* 1.0 */
#define FIXED_MINUS_ONE     (-FIXED_SCALE)              /* -1.0 */
#define FIXED_MAX           INT64_MAX                   /* ~92 billion */
#define FIXED_MIN           INT64_MIN                   /* ~-92 billion */

/*
 * Basis point conversion:
 * 10000 bps = 100% = 1.0 = FIXED_SCALE (1e8)
 * Therefore: 1 bps = 0.0001 = 10000 in fixed representation
 */
#define FIXED_BPS_DIVISOR   10000LL         /* 1 bps = FIXED_SCALE / 10000 */
#define BPS_TO_FIXED(bps)   ((fixed64_t)((bps) * (FIXED_SCALE / 10000LL)))

/* ---------------------------------------------------------------------
 * Conversion macros
 * --------------------------------------------------------------------- */

/* Convert double to fixed-point with proper rounding */
#define DOUBLE_TO_FIXED(d) \
    ((fixed64_t)((d) * (double)FIXED_SCALE + ((d) >= 0 ? 0.5 : -0.5)))

/* Convert fixed-point to double */
#define FIXED_TO_DOUBLE(f) \
    ((double)(f) / (double)FIXED_SCALE)

/* Convert int64_t to fixed-point (multiply by scale) */
#define INT_TO_FIXED(i) \
    ((fixed64_t)(i) * FIXED_SCALE)

/* Convert fixed-point to int64_t (truncate, not round) */
#define FIXED_TO_INT(f) \
    ((int64_t)((f) / FIXED_SCALE))

/* Convert fixed-point to int64_t with rounding */
#define FIXED_TO_INT_ROUND(f) \
    ((int64_t)(((f) >= 0) ? ((f) + FIXED_HALF_SCALE) / FIXED_SCALE \
                          : ((f) - FIXED_HALF_SCALE) / FIXED_SCALE))

/* ---------------------------------------------------------------------
 * Comparison macros
 * --------------------------------------------------------------------- */

#define fixed_lt(a, b)  ((a) < (b))
#define fixed_le(a, b)  ((a) <= (b))
#define fixed_gt(a, b)  ((a) > (b))
#define fixed_ge(a, b)  ((a) >= (b))
#define fixed_eq(a, b)  ((a) == (b))
#define fixed_ne(a, b)  ((a) != (b))

/* ---------------------------------------------------------------------
 * Basic arithmetic operations (inline functions)
 * --------------------------------------------------------------------- */

/*
 * Addition: a + b
 * Note: No overflow protection - caller must ensure values are in range
 */
static inline fixed64_t fixed_add(fixed64_t a, fixed64_t b) {
    return a + b;
}

/*
 * Subtraction: a - b
 * Note: No overflow protection - caller must ensure values are in range
 */
static inline fixed64_t fixed_sub(fixed64_t a, fixed64_t b) {
    return a - b;
}

/*
 * Multiplication: a * b
 * Uses 128-bit intermediate to prevent overflow
 * Result is properly rounded
 */
static inline fixed64_t fixed_mul(fixed64_t a, fixed64_t b) {
    __int128 temp = (__int128)a * b;
    /* Round to nearest (add half scale before division) */
    if (temp >= 0) {
        temp += FIXED_HALF_SCALE;
    } else {
        temp -= FIXED_HALF_SCALE;
    }
    return (fixed64_t)(temp / FIXED_SCALE);
}

/*
 * Division: a / b
 * Uses 128-bit intermediate to maintain precision
 * Note: Division by zero will cause undefined behavior
 */
static inline fixed64_t fixed_div(fixed64_t a, fixed64_t b) {
    __int128 temp = (__int128)a * FIXED_SCALE;
    return (fixed64_t)(temp / b);
}

/*
 * Division with rounding: a / b (rounded to nearest)
 */
static inline fixed64_t fixed_div_round(fixed64_t a, fixed64_t b) {
    __int128 temp = (__int128)a * FIXED_SCALE;
    __int128 half_b = (b >= 0) ? (b / 2) : (-b / 2);
    if ((temp >= 0 && b > 0) || (temp < 0 && b < 0)) {
        temp += half_b;
    } else {
        temp -= half_b;
    }
    return (fixed64_t)(temp / b);
}

/*
 * Negation: -a
 */
static inline fixed64_t fixed_neg(fixed64_t a) {
    return -a;
}

/*
 * Absolute value: |a|
 */
static inline fixed64_t fixed_abs(fixed64_t a) {
    return (a >= 0) ? a : -a;
}

/* ---------------------------------------------------------------------
 * Special operations for financial calculations
 * --------------------------------------------------------------------- */

/*
 * Multiply fixed-point by an integer (unscaled)
 * Useful for: price * quantity where quantity is an integer
 */
static inline fixed64_t fixed_mul_int(fixed64_t a, int64_t b) {
    return a * b;
}

/*
 * Divide fixed-point by an integer (unscaled)
 * Useful for: total / count where count is an integer
 */
static inline fixed64_t fixed_div_int(fixed64_t a, int64_t b) {
    return a / b;
}

/*
 * Calculate percentage: value * (bps / 10000)
 * Useful for: fee calculations
 */
static inline fixed64_t fixed_apply_bps(fixed64_t value, int64_t bps) {
    /* value * bps / 10000 */
    /* Since value is already scaled by 1e8, and we want bps/10000: */
    /* result = value * bps / 10000 */
    __int128 temp = (__int128)value * bps;
    return (fixed64_t)(temp / 10000LL);
}

/*
 * Calculate ceiling division: ceil(a / b) for positive values
 */
static inline fixed64_t fixed_div_ceil(fixed64_t a, fixed64_t b) {
    __int128 temp = (__int128)a * FIXED_SCALE;
    __int128 result = temp / b;
    if (temp % b != 0 && ((temp > 0 && b > 0) || (temp < 0 && b < 0))) {
        result += 1;
    }
    return (fixed64_t)result;
}

/* ---------------------------------------------------------------------
 * Conversion utilities for tick prices
 *
 * Tick prices in ag-kernel are stored as int64_t price_tick.
 * The actual price = price_tick * tick_size
 *
 * For fixed-point: we convert tick_size to fixed and multiply
 * --------------------------------------------------------------------- */

/*
 * Convert a tick price to fixed-point value
 * price_fixed = price_tick * tick_size_fixed
 */
static inline fixed64_t tick_to_fixed(int64_t price_tick, fixed64_t tick_size_fixed) {
    return fixed_mul_int(tick_size_fixed, price_tick);
}

/*
 * Convert fixed-point price to tick price (truncate)
 * price_tick = price_fixed / tick_size_fixed
 */
static inline int64_t fixed_to_tick(fixed64_t price_fixed, fixed64_t tick_size_fixed) {
    return (int64_t)(price_fixed / tick_size_fixed);
}

/* ---------------------------------------------------------------------
 * Min/Max operations
 * --------------------------------------------------------------------- */

static inline fixed64_t fixed_min(fixed64_t a, fixed64_t b) {
    return (a < b) ? a : b;
}

static inline fixed64_t fixed_max(fixed64_t a, fixed64_t b) {
    return (a > b) ? a : b;
}

#endif /* AG_KERNEL_FIXED_POINT_H */
