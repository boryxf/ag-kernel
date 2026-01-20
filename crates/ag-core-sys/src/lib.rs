//! Unsafe FFI bindings to the ag-kernel C engine
//!
//! This crate provides low-level bindings to the C execution engine.
//! For safe wrappers, use the `ag-core` crate instead.
//!
//! ## AgTick Binary Format
//!
//! The `.agtick` format is a compact binary format for tick data with:
//! - Delta-encoded timestamps and prices
//! - Varint-encoded quantities (LEB128)
//! - Bit-packed side flags (8 per byte)
//!
//! This achieves 5-10x compression over CSV and 10-50x faster loading.
//! See the `agtick` module for FFI bindings to the C implementation.

#![allow(non_camel_case_types)]
#![allow(non_snake_case)]

use std::os::raw::{c_double, c_int};

// ========== AgTick Binary Format Module ==========

pub mod agtick;

// Re-export commonly used agtick types
pub use agtick::{
    agtick_header_t as AgTickHeader,
    AgTickError, AgTickMmap, AgTickReader, AgTickResult, AgTickVec, AgTickWriter,
};

// ========== Legacy AgTick Format (Deprecated) ==========
//
// The following types are from the old fixed-record format.
// Use the new `agtick` module instead for better compression.

/// Magic bytes for legacy agtick file format
#[deprecated(note = "Use agtick module instead")]
pub const AGTICK_MAGIC_LEGACY: [u8; 8] = *b"AGTICK01";

/// Current version of the legacy agtick format
#[deprecated(note = "Use agtick module instead")]
pub const AGTICK_VERSION_LEGACY: u16 = 1;

/// Legacy header size in bytes
#[deprecated(note = "Use agtick module instead")]
pub const AGTICK_HEADER_SIZE_LEGACY: usize = 32;

/// Legacy record size in bytes
#[deprecated(note = "Use agtick module instead")]
pub const AGTICK_RECORD_SIZE_LEGACY: usize = 32;

/// Legacy AgTick file header (fixed-record format)
#[deprecated(note = "Use agtick::agtick_header_t instead")]
#[repr(C, packed)]
#[derive(Debug, Copy, Clone)]
pub struct agtick_header_legacy_t {
    pub magic: [u8; 8],
    pub version: u16,
    pub flags: u16,
    pub tick_size: f64,
    pub record_count: u64,
    pub reserved: [u8; 4],
}

/// Legacy AgTick record (single tick event in fixed-record format)
#[deprecated(note = "Use agtick module with tick_event_t instead")]
#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct agtick_record_legacy_t {
    pub ts_ms: i64,
    pub price_tick: i64,
    pub qty_scaled: i64,
    pub side: u8,
    pub reserved: [u8; 7],
}

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

    /// Batch processing - process multiple ticks in a single FFI call
    /// Returns 0 on success, negative error code on failure
    pub fn engine_step_batch(
        h: *mut engine_handle_t,
        ticks: *const tick_event_t,
        count: c_int,
    ) -> c_int;

    pub fn engine_place_order(h: *mut engine_handle_t, order: *const order_t) -> c_int;

    pub fn engine_cancel_order(h: *mut engine_handle_t, order_id: u64) -> c_int;

    pub fn engine_get_snapshot(h: *const engine_handle_t) -> snapshot_t;
}

// ========== Legacy AgTick Utility Functions (Deprecated) ==========

#[allow(deprecated)]
impl agtick_header_legacy_t {
    /// Create a new valid header
    #[deprecated(note = "Use agtick module instead")]
    pub fn new(tick_size: f64, record_count: u64) -> Self {
        #[allow(deprecated)]
        Self {
            magic: AGTICK_MAGIC_LEGACY,
            version: AGTICK_VERSION_LEGACY,
            flags: 0,
            tick_size,
            record_count,
            reserved: [0; 4],
        }
    }

    /// Validate the header magic and version
    #[deprecated(note = "Use agtick module instead")]
    pub fn is_valid(&self) -> bool {
        #[allow(deprecated)]
        {
            self.magic == AGTICK_MAGIC_LEGACY && self.version == AGTICK_VERSION_LEGACY
        }
    }
}

#[allow(deprecated)]
impl agtick_record_legacy_t {
    /// Create a new record from tick data
    #[deprecated(note = "Use agtick module with tick_event_t instead")]
    pub fn new(ts_ms: i64, price_tick: i64, qty_scaled: i64, side: u8) -> Self {
        Self {
            ts_ms,
            price_tick,
            qty_scaled,
            side,
            reserved: [0; 7],
        }
    }

    /// Convert to tick_event_t for engine processing
    #[deprecated(note = "Use agtick module with tick_event_t instead")]
    pub fn to_tick_event(&self) -> tick_event_t {
        tick_event_t {
            ts_ms: self.ts_ms,
            price_tick: self.price_tick,
            qty: self.qty_scaled,
            side: if self.side == 0 {
                side_t::SIDE_BUY
            } else {
                side_t::SIDE_SELL
            },
        }
    }
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

    #[test]
    #[allow(deprecated)]
    fn test_legacy_agtick_header_size() {
        assert_eq!(
            std::mem::size_of::<agtick_header_legacy_t>(),
            AGTICK_HEADER_SIZE_LEGACY
        );
    }

    #[test]
    #[allow(deprecated)]
    fn test_legacy_agtick_record_size() {
        assert_eq!(
            std::mem::size_of::<agtick_record_legacy_t>(),
            AGTICK_RECORD_SIZE_LEGACY
        );
    }

    #[test]
    fn test_new_agtick_header_size() {
        // New format has 64-byte header
        assert_eq!(
            std::mem::size_of::<agtick::agtick_header_t>(),
            agtick::AGTICK_HEADER_SIZE
        );
    }
}
