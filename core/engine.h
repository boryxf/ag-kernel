#ifndef AG_KERNEL_ENGINE_H
#define AG_KERNEL_ENGINE_H

#include "types.h"

// Opaque handle for the engine
typedef struct engine_handle_s engine_handle_t;

// Create a new engine instance with given configuration
// Returns NULL on failure
engine_handle_t* engine_new(config_t* cfg);

// Free the engine and all its resources
void engine_free(engine_handle_t* h);

// Reset the engine to initial state
void engine_reset(engine_handle_t* h);

// Process a tick event
// Returns 0 on success, negative on error
int engine_step_tick(engine_handle_t* h, tick_event_t* tick);

// Place an order
// Returns 0 on success, negative on error
int engine_place_order(engine_handle_t* h, order_t* order);

// Cancel an order by ID
// Returns 0 on success, negative on error (-1 if order not found)
int engine_cancel_order(engine_handle_t* h, uint64_t order_id);

// Get current state snapshot
snapshot_t engine_get_snapshot(engine_handle_t* h);

#endif // AG_KERNEL_ENGINE_H
