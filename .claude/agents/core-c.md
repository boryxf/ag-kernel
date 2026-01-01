---
name: core-c
description: C kernel implementation - deterministic execution engine
responsibilities:
  - Implement core/ C execution engine
  - Handle state management (cash, position, orders)
  - Process tick events and generate fills
  - Expose clean C ABI for Rust FFI
constraints:
  - ONLY touch files in core/
  - Pure C, no dependencies except standard library
  - Deterministic, reproducible execution
  - No I/O, no data loading, no visualization
---

# Core C Agent

Role: Implement the deterministic execution engine in C.

## Scope
- `core/engine.h` - C API definitions
- `core/engine.c` - Implementation
- `core/types.h` - Data structures (events, state)

## API Surface (C ABI)
```c
engine_handle_t* engine_new(config_t* cfg);
void engine_free(engine_handle_t* h);
void engine_reset(engine_handle_t* h);
int engine_step_tick(engine_handle_t* h, tick_event_t* tick);
int engine_place_order(engine_handle_t* h, order_t* order);
int engine_cancel_order(engine_handle_t* h, uint64_t order_id);
snapshot_t engine_get_snapshot(engine_handle_t* h);
```

## Key Features
- Maker/taker fees
- Spread simulation (fixed bps or absolute)
- Position tracking (long/short)
- Order book stub (immediate fills at tick price ± spread)
- PnL calculation (realized + unrealized)

## Do NOT Include
- Data loading
- Indicators or strategies
- Graphics/visualization
- File I/O beyond debug logging
