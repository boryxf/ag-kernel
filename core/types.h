#ifndef AG_KERNEL_TYPES_H
#define AG_KERNEL_TYPES_H

#include <stdint.h>

// Event types
typedef enum {
    SIDE_BUY = 0,
    SIDE_SELL = 1
} side_t;

typedef struct {
    int64_t ts_ms;        // Timestamp in milliseconds
    int64_t price_tick;   // Price in ticks (integer representation)
    int64_t qty;          // Quantity
    side_t side;          // Buy or sell side
} tick_event_t;

// Order types
typedef enum {
    ORDER_TYPE_LIMIT = 0,
    ORDER_TYPE_MARKET = 1
} order_type_t;

typedef struct {
    uint64_t order_id;    // Unique order identifier
    order_type_t type;    // Limit or market
    side_t side;          // Buy or sell
    int64_t qty;          // Quantity
    int64_t price_tick;   // Price in ticks (0 for market orders)
} order_t;

// Snapshot type
typedef struct {
    int64_t ts_ms;           // Timestamp in milliseconds
    double cash;             // Current cash balance
    int64_t position;        // Current position (positive=long, negative=short)
    double avg_entry_price;  // Average entry price (in ticks)
    double realized_pnl;     // Realized profit/loss
    double unrealized_pnl;   // Unrealized profit/loss
    double equity;           // Total equity (cash + unrealized_pnl)
} snapshot_t;

// Configuration type
typedef struct {
    double maker_fee_bps;    // Maker fee in basis points (e.g., 10 = 0.1%)
    double taker_fee_bps;    // Taker fee in basis points
    double spread_bps;       // Spread in basis points (applied to each side)
    double initial_cash;     // Initial cash balance
    double tick_size;        // Size of one tick in currency units
} config_t;

#endif // AG_KERNEL_TYPES_H
