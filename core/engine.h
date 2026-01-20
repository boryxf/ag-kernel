#ifndef AG_KERNEL_ENGINE_H
#define AG_KERNEL_ENGINE_H

#include "types.h"
#include <stddef.h>

// Default maximum orders (can be changed via engine_set_max_orders)
#define ENGINE_DEFAULT_MAX_ORDERS 1024

// Opaque handle for the engine
typedef struct engine_handle_s engine_handle_t;

// Create a new engine instance with given configuration
// Returns NULL on failure
engine_handle_t* engine_new(config_t* cfg);

// Free the engine and all its resources
void engine_free(engine_handle_t* h);

// Reset the engine to initial state
void engine_reset(engine_handle_t* h);

// Process a single tick event
// Returns 0 on success, negative on error
int engine_step_tick(engine_handle_t* h, tick_event_t* tick);

// Process a batch of tick events efficiently (single FFI call for N ticks)
// This is the optimized batch API - use instead of calling engine_step_tick in a loop
// Parameters:
//   h      - engine handle
//   ticks  - array of tick events to process
//   count  - number of ticks in the array
// Returns 0 on success, negative on error
int engine_step_batch(engine_handle_t* h, const tick_event_t* ticks, int count);

// Place an order
// Returns 0 on success, negative on error
int engine_place_order(engine_handle_t* h, order_t* order);

// Cancel an order by ID
// Returns 0 on success, negative on error (-1 if order not found)
int engine_cancel_order(engine_handle_t* h, uint64_t order_id);

// Get current state snapshot
snapshot_t engine_get_snapshot(engine_handle_t* h);

// Set maximum number of open orders (dynamic pool sizing)
// Must be called before placing orders, or after engine_reset
// Parameters:
//   h     - engine handle
//   count - maximum number of concurrent open orders (0 = use default)
// Returns 0 on success, negative on error (-1 invalid args, -2 resize failed)
int engine_set_max_orders(engine_handle_t* h, size_t count);

// Get current maximum orders capacity
size_t engine_get_max_orders(engine_handle_t* h);

// Get number of currently active orders
size_t engine_get_active_order_count(engine_handle_t* h);

/* ---------------------------------------------------------------------
 * Fixed-Point Engine (Optional, for performance)
 *
 * Alternative implementation using fixed-point arithmetic instead of
 * double-precision floating-point. Provides deterministic results and
 * potentially better performance on architectures without FPU.
 *
 * The double-precision engine above remains the default.
 * Use the fixed-point variant by replacing function calls:
 *   engine_new()        -> engine_fixed_new()
 *   engine_step_tick()  -> engine_fixed_step_tick()
 *   etc.
 * --------------------------------------------------------------------- */

// Opaque handle for the fixed-point engine
typedef struct engine_fixed_handle_s engine_fixed_handle_t;

// Create a new fixed-point engine instance with given configuration
// Returns NULL on failure
engine_fixed_handle_t* engine_fixed_new(config_t* cfg);

// Free the fixed-point engine and all its resources
void engine_fixed_free(engine_fixed_handle_t* h);

// Reset the fixed-point engine to initial state
void engine_fixed_reset(engine_fixed_handle_t* h);

// Process a tick event (fixed-point version)
// Returns 0 on success, negative on error
int engine_fixed_step_tick(engine_fixed_handle_t* h, tick_event_t* tick);

// Process a batch of tick events (fixed-point version)
// Returns 0 on success, negative on error
int engine_fixed_step_batch(engine_fixed_handle_t* h, tick_event_t* ticks, int count);

// Place an order (fixed-point version)
// Returns 0 on success, negative on error
int engine_fixed_place_order(engine_fixed_handle_t* h, order_t* order);

// Cancel an order by ID (fixed-point version)
// Returns 0 on success, negative on error (-1 if order not found)
int engine_fixed_cancel_order(engine_fixed_handle_t* h, uint64_t order_id);

// Get current state snapshot (fixed-point version)
// Note: Returns snapshot_t with double values for API compatibility
snapshot_t engine_fixed_get_snapshot(engine_fixed_handle_t* h);

// Set maximum number of open orders (fixed-point version)
int engine_fixed_set_max_orders(engine_fixed_handle_t* h, size_t count);

// Get current maximum orders capacity (fixed-point version)
size_t engine_fixed_get_max_orders(engine_fixed_handle_t* h);

// Get number of currently active orders (fixed-point version)
size_t engine_fixed_get_active_order_count(engine_fixed_handle_t* h);

#endif // AG_KERNEL_ENGINE_H
