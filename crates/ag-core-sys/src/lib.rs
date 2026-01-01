//! Unsafe FFI bindings to the ag-kernel C engine
//!
//! This crate provides low-level bindings to the C execution engine.
//! For safe wrappers, use the `ag-core` crate instead.

#![allow(non_camel_case_types)]
#![allow(non_snake_case)]

use std::os::raw::{c_double, c_int, c_void};

// ========== Type Definitions ==========

#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq)]
pub enum side_t {
    SIDE_BUY = 0,
    SIDE_SELL = 1,
}

#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct tick_event_t {
    pub ts_ms: i64,
    pub price_tick: i64,
    pub qty: i64,
    pub side: side_t,
}

#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq)]
pub enum order_type_t {
    ORDER_TYPE_LIMIT = 0,
    ORDER_TYPE_MARKET = 1,
}

#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct order_t {
    pub order_id: u64,
    pub type_: order_type_t,
    pub side: side_t,
    pub qty: i64,
    pub price_tick: i64,
}

#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct snapshot_t {
    pub ts_ms: i64,
    pub cash: c_double,
    pub position: i64,
    pub avg_entry_price: c_double,
    pub realized_pnl: c_double,
    pub unrealized_pnl: c_double,
    pub equity: c_double,
}

#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct config_t {
    pub maker_fee_bps: c_double,
    pub taker_fee_bps: c_double,
    pub spread_bps: c_double,
    pub initial_cash: c_double,
    pub tick_size: c_double,
}

// Opaque handle type
#[repr(C)]
pub struct engine_handle_s {
    _private: [u8; 0],
}

pub type engine_handle_t = engine_handle_s;

// ========== C Function Bindings ==========

extern "C" {
    pub fn engine_new(cfg: *const config_t) -> *mut engine_handle_t;

    pub fn engine_free(h: *mut engine_handle_t);

    pub fn engine_reset(h: *mut engine_handle_t);

    pub fn engine_step_tick(h: *mut engine_handle_t, tick: *const tick_event_t) -> c_int;

    pub fn engine_place_order(h: *mut engine_handle_t, order: *const order_t) -> c_int;

    pub fn engine_cancel_order(h: *mut engine_handle_t, order_id: u64) -> c_int;

    pub fn engine_get_snapshot(h: *const engine_handle_t) -> snapshot_t;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_engine_lifecycle() {
        unsafe {
            let config = config_t {
                maker_fee_bps: 1.0,
                taker_fee_bps: 2.0,
                spread_bps: 2.0,
                initial_cash: 10000.0,
                tick_size: 1.0,
            };

            let handle = engine_new(&config);
            assert!(!handle.is_null());

            let snapshot = engine_get_snapshot(handle);
            assert_eq!(snapshot.cash, 10000.0);
            assert_eq!(snapshot.position, 0);

            engine_free(handle);
        }
    }
}
