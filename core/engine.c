#include "engine.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>

#define MAX_OPEN_ORDERS 1024

// SCALING CONVENTION:
// - Quantities (order->qty, position) are scaled by 1,000,000 from Rust side
// - When doing financial calculations (notional, PnL), must divide by 1,000,000.0
// - Price ticks and tick_size remain unscaled

// Internal order tracking
typedef struct {
    order_t order;
    int active;  // 1 if order is active, 0 if cancelled
} tracked_order_t;

// Internal engine state
struct engine_handle_s {
    config_t config;

    // Current state
    int64_t current_ts_ms;
    double cash;
    int64_t position;        // Positive = long, negative = short
    double avg_entry_price;  // Average entry price in ticks
    double realized_pnl;

    // Open orders
    tracked_order_t orders[MAX_OPEN_ORDERS];
    int order_count;

    // Last tick price for unrealized PnL calculation
    int64_t last_tick_price;
};

// Helper function to calculate unrealized PnL
static double calculate_unrealized_pnl(engine_handle_t* h) {
    if (h->position == 0) {
        return 0.0;
    }

    // Position is scaled by 1,000,000 from Rust side - descale for calculations
    double position_descaled = (double)h->position / 1000000.0;
    double position_value = position_descaled * (double)h->last_tick_price * h->config.tick_size;
    double entry_value = position_descaled * h->avg_entry_price * h->config.tick_size;

    return position_value - entry_value;
}

// Helper function to apply fees
static double calculate_fee(engine_handle_t* h, double notional, int is_maker) {
    double fee_bps = is_maker ? h->config.maker_fee_bps : h->config.taker_fee_bps;
    return notional * (fee_bps / 10000.0);
}

// Helper function to get effective price after spread
static int64_t apply_spread(engine_handle_t* h, int64_t price_tick, side_t side) {
    // Spread widens the market: buyers pay more, sellers receive less
    double spread_multiplier = h->config.spread_bps / 10000.0;
    double spread_ticks = (double)price_tick * spread_multiplier;

    if (side == SIDE_BUY) {
        // Buying: pay more (round up)
        return price_tick + (int64_t)ceil(spread_ticks);
    } else {
        // Selling: receive less (round down)
        return price_tick - (int64_t)ceil(spread_ticks);
    }
}

// Helper function to execute a fill
static int execute_fill(engine_handle_t* h, order_t* order, int64_t fill_price_tick) {
    int64_t fill_qty = order->qty;
    double fill_price = (double)fill_price_tick * h->config.tick_size;
    // Quantity is scaled by 1,000,000 from Rust side - descale for notional calculation
    double notional = fill_price * ((double)fill_qty / 1000000.0);

    // Calculate fee (assuming taker fee for simplicity)
    double fee = calculate_fee(h, notional, 0);

    // Update position and PnL
    int64_t old_position = h->position;
    int64_t new_position = old_position;

    if (order->side == SIDE_BUY) {
        new_position += fill_qty;
        h->cash -= (notional + fee);
    } else {
        new_position -= fill_qty;
        h->cash += (notional - fee);
    }

    // Update realized PnL and average entry price
    if (old_position == 0) {
        // Opening new position
        h->avg_entry_price = (double)fill_price_tick;
    } else if ((old_position > 0 && order->side == SIDE_BUY) ||
               (old_position < 0 && order->side == SIDE_SELL)) {
        // Adding to position - update average entry price
        // Positions are already scaled, so we work directly with them for weighted average
        double old_value = (double)old_position * h->avg_entry_price;
        double new_value = (double)fill_qty * (double)fill_price_tick;
        h->avg_entry_price = (old_value + new_value) / (double)new_position;
    } else {
        // Reducing or flipping position - realize PnL
        int64_t qty_reducing = (llabs(old_position) >= fill_qty) ? fill_qty : llabs(old_position);

        // qty_reducing is scaled by 1,000,000 - descale for PnL calculations
        double qty_reducing_descaled = (double)qty_reducing / 1000000.0;
        double exit_value = qty_reducing_descaled * (double)fill_price_tick * h->config.tick_size;
        double entry_value = qty_reducing_descaled * h->avg_entry_price * h->config.tick_size;

        if (old_position > 0) {
            // Closing long position
            // Note: fee is already deducted from cash, so PnL shows gross profit
            h->realized_pnl += (exit_value - entry_value);
        } else {
            // Closing short position
            // Note: fee is already deducted from cash, so PnL shows gross profit
            h->realized_pnl += (entry_value - exit_value);
        }

        // If flipping position, set new average entry price
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

// Helper function to check if an order should be filled at given tick
static int should_fill_order(order_t* order, tick_event_t* tick) {
    if (order->type == ORDER_TYPE_MARKET) {
        return 1;  // Market orders always fill
    }

    // Limit orders fill if price crosses
    if (order->side == SIDE_BUY) {
        // Buy limit fills if tick price <= limit price
        return tick->price_tick <= order->price_tick;
    } else {
        // Sell limit fills if tick price >= limit price
        return tick->price_tick >= order->price_tick;
    }
}

engine_handle_t* engine_new(config_t* cfg) {
    if (!cfg) {
        return NULL;
    }

    engine_handle_t* h = (engine_handle_t*)malloc(sizeof(engine_handle_t));
    if (!h) {
        return NULL;
    }

    memset(h, 0, sizeof(engine_handle_t));
    h->config = *cfg;
    h->cash = cfg->initial_cash;
    h->current_ts_ms = 0;
    h->position = 0;
    h->avg_entry_price = 0.0;
    h->realized_pnl = 0.0;
    h->order_count = 0;
    h->last_tick_price = 0;

    return h;
}

void engine_free(engine_handle_t* h) {
    if (h) {
        free(h);
    }
}

void engine_reset(engine_handle_t* h) {
    if (!h) {
        return;
    }

    config_t cfg = h->config;  // Save config
    memset(h, 0, sizeof(engine_handle_t));
    h->config = cfg;
    h->cash = cfg.initial_cash;
    h->current_ts_ms = 0;
    h->position = 0;
    h->avg_entry_price = 0.0;
    h->realized_pnl = 0.0;
    h->order_count = 0;
    h->last_tick_price = 0;
}

int engine_step_tick(engine_handle_t* h, tick_event_t* tick) {
    if (!h || !tick) {
        return -1;
    }

    h->current_ts_ms = tick->ts_ms;
    h->last_tick_price = tick->price_tick;

    // Check all open orders for fills
    for (int i = 0; i < h->order_count; i++) {
        if (!h->orders[i].active) {
            continue;
        }

        if (should_fill_order(&h->orders[i].order, tick)) {
            // Determine fill price
            int64_t fill_price_tick;
            if (h->orders[i].order.type == ORDER_TYPE_MARKET) {
                // Market orders fill at tick price with spread
                fill_price_tick = apply_spread(h, tick->price_tick, h->orders[i].order.side);
            } else {
                // Limit orders fill at limit price with spread
                fill_price_tick = apply_spread(h, h->orders[i].order.price_tick, h->orders[i].order.side);
            }

            // Execute the fill
            execute_fill(h, &h->orders[i].order, fill_price_tick);

            // Mark order as inactive
            h->orders[i].active = 0;
        }
    }

    // Compact the order list (remove inactive orders)
    int write_idx = 0;
    for (int read_idx = 0; read_idx < h->order_count; read_idx++) {
        if (h->orders[read_idx].active) {
            if (write_idx != read_idx) {
                h->orders[write_idx] = h->orders[read_idx];
            }
            write_idx++;
        }
    }
    h->order_count = write_idx;

    return 0;
}

int engine_place_order(engine_handle_t* h, order_t* order) {
    if (!h || !order) {
        return -1;
    }

    if (h->order_count >= MAX_OPEN_ORDERS) {
        return -2;  // Order book full
    }

    // Add order to tracking
    h->orders[h->order_count].order = *order;
    h->orders[h->order_count].active = 1;
    h->order_count++;

    return 0;
}

int engine_cancel_order(engine_handle_t* h, uint64_t order_id) {
    if (!h) {
        return -1;
    }

    // Find and cancel the order
    for (int i = 0; i < h->order_count; i++) {
        if (h->orders[i].active && h->orders[i].order.order_id == order_id) {
            h->orders[i].active = 0;
            return 0;
        }
    }

    return -1;  // Order not found
}

snapshot_t engine_get_snapshot(engine_handle_t* h) {
    snapshot_t snap;
    memset(&snap, 0, sizeof(snapshot_t));

    if (!h) {
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
