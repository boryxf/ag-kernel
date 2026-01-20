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

// ========== Candle Types and Functions ==========

/// OHLCV candle structure
#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct candle_t {
    pub ts_ms: i64,
    pub open_tick: i64,
    pub high_tick: i64,
    pub low_tick: i64,
    pub close_tick: i64,
    pub volume: c_double,
    pub buy_volume: c_double,
    pub sell_volume: c_double,
    pub trade_count: u64,
}

/// Opaque handle for streaming candle aggregator
#[repr(C)]
pub struct candle_aggregator_s {
    _private: [u8; 0],
}

pub type candle_aggregator_t = candle_aggregator_s;

extern "C" {
    /// Aggregate tick data into candles at specified interval
    pub fn candles_aggregate(
        timestamps: *const i64,
        price_ticks: *const i64,
        qtys: *const c_double,
        sides: *const u8,
        count: usize,
        interval_ms: i64,
        candles_out: *mut candle_t,
        max_candles: usize,
    ) -> i64;

    /// Resample candles to a larger interval
    pub fn candles_resample(
        candles: *const candle_t,
        count: usize,
        input_ms: i64,
        output_ms: i64,
        candles_out: *mut candle_t,
        max_candles: usize,
    ) -> i64;

    /// Create a new streaming candle aggregator
    pub fn candle_aggregator_new(interval_ms: i64) -> *mut candle_aggregator_t;

    /// Free a candle aggregator
    pub fn candle_aggregator_free(agg: *mut candle_aggregator_t);

    /// Reset the aggregator state
    pub fn candle_aggregator_reset(agg: *mut candle_aggregator_t);

    /// Process a single tick through the aggregator
    /// Returns 1 if candle completed, 0 if not, negative on error
    pub fn candle_aggregator_update(
        agg: *mut candle_aggregator_t,
        ts_ms: i64,
        price_tick: i64,
        qty: c_double,
        side: u8,
        candle_out: *mut candle_t,
    ) -> c_int;

    /// Flush the current incomplete candle
    pub fn candle_aggregator_flush(
        agg: *mut candle_aggregator_t,
        candle_out: *mut candle_t,
    ) -> c_int;

    /// Get the current incomplete candle without flushing
    pub fn candle_aggregator_peek(
        agg: *const candle_aggregator_t,
        candle_out: *mut candle_t,
    ) -> c_int;
}

// ========== Volume Types and Functions ==========

/// Volume profile bin structure
#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct volume_bin_t {
    pub price_tick: i64,
    pub volume: c_double,
    pub buy_volume: c_double,
    pub sell_volume: c_double,
}

/// Volume profile result structure
#[repr(C)]
#[derive(Debug)]
pub struct volume_profile_t {
    pub bins: *mut volume_bin_t,
    pub num_bins: usize,
    pub poc_tick: i64,
    pub vah_tick: i64,
    pub val_tick: i64,
    pub total_volume: c_double,
}

extern "C" {
    /// Calculate VWAP for tick data
    pub fn vwap_calculate(
        timestamps: *const i64,
        price_ticks: *const i64,
        qtys: *const c_double,
        count: usize,
        tick_size: c_double,
        vwap_out: *mut c_double,
    ) -> c_int;

    /// Calculate session VWAP (resets at each new day)
    pub fn vwap_session_calculate(
        timestamps: *const i64,
        price_ticks: *const i64,
        qtys: *const c_double,
        count: usize,
        tick_size: c_double,
        vwap_out: *mut c_double,
    ) -> c_int;

    /// Build a volume profile from tick data
    pub fn volume_profile_build(
        price_ticks: *const i64,
        qtys: *const c_double,
        sides: *const u8,
        count: usize,
        tick_size: c_double,
        num_bins: usize,
        value_area_pct: c_double,
        profile_out: *mut volume_profile_t,
    ) -> c_int;

    /// Free memory allocated for a volume profile
    pub fn volume_profile_free(profile: *mut volume_profile_t);

    /// Calculate cumulative delta (buy volume - sell volume)
    pub fn cumulative_delta_calculate(
        qtys: *const c_double,
        sides: *const u8,
        count: usize,
        delta_out: *mut c_double,
    ) -> c_int;

    /// Calculate delta per candle period
    pub fn delta_per_candle(
        timestamps: *const i64,
        qtys: *const c_double,
        sides: *const u8,
        count: usize,
        interval_ms: i64,
        delta_out: *mut c_double,
        max_candles: usize,
    ) -> i64;

    /// Calculate On-Balance Volume (OBV)
    pub fn obv_calculate(
        price_ticks: *const i64,
        qtys: *const c_double,
        count: usize,
        obv_out: *mut c_double,
    ) -> c_int;

    /// Calculate Money Flow Index (MFI)
    pub fn mfi_calculate(
        high_ticks: *const i64,
        low_ticks: *const i64,
        close_ticks: *const i64,
        volumes: *const c_double,
        count: usize,
        period: c_int,
        mfi_out: *mut c_double,
    ) -> c_int;
}

// ========== Volatility Types and Functions ==========

/// Volatility calculation method
#[repr(C)]
#[derive(Debug, Copy, Clone, PartialEq)]
pub enum volatility_method_t {
    VOL_METHOD_REALIZED = 0,
    VOL_METHOD_PARKINSON = 1,
    VOL_METHOD_GARMAN_KLASS = 2,
    VOL_METHOD_ROGERS_SATCHELL = 3,
    VOL_METHOD_YANG_ZHANG = 4,
    VOL_METHOD_EWMA = 5,
}

/// Opaque handle for streaming volatility state
#[repr(C)]
pub struct volatility_state_s {
    _private: [u8; 0],
}

pub type volatility_state_t = volatility_state_s;

extern "C" {
    /// Calculate realized volatility (close-to-close)
    pub fn volatility_realized(
        close_ticks: *const i64,
        count: usize,
        window: c_int,
        annualize: bool,
        vol_out: *mut c_double,
    ) -> c_int;

    /// Calculate Parkinson volatility (high-low range estimator)
    pub fn volatility_parkinson(
        high_ticks: *const i64,
        low_ticks: *const i64,
        count: usize,
        window: c_int,
        annualize: bool,
        vol_out: *mut c_double,
    ) -> c_int;

    /// Calculate Garman-Klass volatility
    pub fn volatility_garman_klass(
        open_ticks: *const i64,
        high_ticks: *const i64,
        low_ticks: *const i64,
        close_ticks: *const i64,
        count: usize,
        window: c_int,
        annualize: bool,
        vol_out: *mut c_double,
    ) -> c_int;

    /// Calculate Rogers-Satchell volatility
    pub fn volatility_rogers_satchell(
        open_ticks: *const i64,
        high_ticks: *const i64,
        low_ticks: *const i64,
        close_ticks: *const i64,
        count: usize,
        window: c_int,
        annualize: bool,
        vol_out: *mut c_double,
    ) -> c_int;

    /// Calculate Yang-Zhang volatility
    pub fn volatility_yang_zhang(
        open_ticks: *const i64,
        high_ticks: *const i64,
        low_ticks: *const i64,
        close_ticks: *const i64,
        count: usize,
        window: c_int,
        annualize: bool,
        vol_out: *mut c_double,
    ) -> c_int;

    /// Calculate EWMA volatility
    pub fn volatility_ewma(
        close_ticks: *const i64,
        count: usize,
        lambda: c_double,
        annualize: bool,
        vol_out: *mut c_double,
    ) -> c_int;

    /// Calculate Average True Range (ATR)
    pub fn atr_calculate(
        high_ticks: *const i64,
        low_ticks: *const i64,
        close_ticks: *const i64,
        count: usize,
        period: c_int,
        tick_size: c_double,
        atr_out: *mut c_double,
    ) -> c_int;

    /// Calculate True Range for each candle
    pub fn true_range_calculate(
        high_ticks: *const i64,
        low_ticks: *const i64,
        close_ticks: *const i64,
        count: usize,
        tick_size: c_double,
        tr_out: *mut c_double,
    ) -> c_int;

    /// Create a new streaming volatility calculator
    pub fn volatility_state_new(
        method: volatility_method_t,
        window: c_int,
        param: c_double,
        annualize: bool,
    ) -> *mut volatility_state_t;

    /// Free a volatility state
    pub fn volatility_state_free(state: *mut volatility_state_t);

    /// Reset volatility state
    pub fn volatility_state_reset(state: *mut volatility_state_t);

    /// Update streaming volatility with a new candle
    pub fn volatility_state_update(
        state: *mut volatility_state_t,
        open_tick: i64,
        high_tick: i64,
        low_tick: i64,
        close_tick: i64,
    ) -> c_double;

    /// Get current volatility estimate without adding new data
    pub fn volatility_state_current(state: *const volatility_state_t) -> c_double;
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
