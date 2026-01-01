//! OHLC Candle data structures with zero-copy optimization

use bytemuck::{Pod, Zeroable};

/// OHLC Candle representation optimized for zero-copy deserialization
///
/// Memory layout:
/// - 64 bytes total (cache-line friendly)
/// - All fields are POD types for bytemuck compatibility
/// - Uses i64 for prices (tick-quantized) to avoid float precision issues
///
/// # Safety
/// This struct is marked as `Pod` and `Zeroable`, meaning:
/// - All bit patterns are valid
/// - Can be safely cast from/to byte slices
/// - No padding bytes contain uninitialized data
#[repr(C)]
#[derive(Copy, Clone, Debug, Default)]
pub struct Candle {
    /// Unix timestamp in milliseconds (start of candle)
    pub ts_open: i64,

    /// Unix timestamp in milliseconds (end of candle)
    pub ts_close: i64,

    /// Opening price (tick-quantized as i64)
    pub open_tick: i64,

    /// Highest price (tick-quantized as i64)
    pub high_tick: i64,

    /// Lowest price (tick-quantized as i64)
    pub low_tick: i64,

    /// Closing price (tick-quantized as i64)
    pub close_tick: i64,

    /// Total volume traded during candle period
    /// Stored as i64 with 6 decimal precision (multiply by 1e6)
    pub volume_scaled: i64,

    /// Number of trades in this candle
    pub trade_count: i64,
}

// SAFETY: Candle contains only POD types (i64)
// All bit patterns are valid (though semantically some represent invalid data)
unsafe impl Zeroable for Candle {}

// SAFETY: Candle has #[repr(C)] and contains only i64 fields
// No padding, no invalid bit patterns
unsafe impl Pod for Candle {}

impl Candle {
    /// Validate candle data integrity
    ///
    /// Checks:
    /// - Timestamps are positive and ordered correctly
    /// - OHLC relationship is valid: low <= open/close <= high
    /// - Volume is non-negative
    /// - Trade count is non-negative
    ///
    /// Returns true if candle is valid, false otherwise.
    /// Does NOT panic on invalid data.
    #[inline]
    pub fn is_valid(&self) -> bool {
        // Timestamp validation
        if self.ts_open <= 0 || self.ts_close <= 0 {
            return false;
        }

        if self.ts_close < self.ts_open {
            return false;
        }

        // OHLC relationship validation
        if self.low_tick > self.high_tick {
            return false;
        }

        if self.open_tick < self.low_tick || self.open_tick > self.high_tick {
            return false;
        }

        if self.close_tick < self.low_tick || self.close_tick > self.high_tick {
            return false;
        }

        // Volume validation
        if self.volume_scaled < 0 {
            return false;
        }

        // Trade count validation
        if self.trade_count < 0 {
            return false;
        }

        true
    }

    /// Convert tick-quantized prices to float prices
    ///
    /// # Arguments
    /// * `tick_size` - The tick size used for quantization
    #[inline]
    pub fn to_float_prices(&self, tick_size: f64) -> CandleFloat {
        CandleFloat {
            ts_open: self.ts_open,
            ts_close: self.ts_close,
            open: self.open_tick as f64 * tick_size,
            high: self.high_tick as f64 * tick_size,
            low: self.low_tick as f64 * tick_size,
            close: self.close_tick as f64 * tick_size,
            volume: self.volume_scaled as f64 / 1_000_000.0,
            trade_count: self.trade_count,
        }
    }

    /// Create a candle from float prices
    ///
    /// # Arguments
    /// * `tick_size` - The tick size for quantization
    #[inline]
    pub fn from_float_prices(float_candle: &CandleFloat, tick_size: f64) -> Self {
        Self {
            ts_open: float_candle.ts_open,
            ts_close: float_candle.ts_close,
            open_tick: (float_candle.open / tick_size).round() as i64,
            high_tick: (float_candle.high / tick_size).round() as i64,
            low_tick: (float_candle.low / tick_size).round() as i64,
            close_tick: (float_candle.close / tick_size).round() as i64,
            volume_scaled: (float_candle.volume * 1_000_000.0).round() as i64,
            trade_count: float_candle.trade_count,
        }
    }
}

/// Float-price representation of a candle (for user-facing APIs)
#[derive(Clone, Debug, Default)]
pub struct CandleFloat {
    pub ts_open: i64,
    pub ts_close: i64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: f64,
    pub trade_count: i64,
}

impl CandleFloat {
    /// Validate candle data (float version)
    #[inline]
    pub fn is_valid(&self) -> bool {
        // Timestamp validation
        if self.ts_open <= 0 || self.ts_close <= 0 {
            return false;
        }

        if self.ts_close < self.ts_open {
            return false;
        }

        // Check for NaN or infinity
        if !self.open.is_finite() || !self.high.is_finite()
           || !self.low.is_finite() || !self.close.is_finite() {
            return false;
        }

        // OHLC relationship validation
        if self.low > self.high {
            return false;
        }

        if self.open < self.low || self.open > self.high {
            return false;
        }

        if self.close < self.low || self.close > self.high {
            return false;
        }

        // Volume validation
        if !self.volume.is_finite() || self.volume < 0.0 {
            return false;
        }

        // Trade count validation
        if self.trade_count < 0 {
            return false;
        }

        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_candle_is_pod() {
        // Verify size is what we expect (8 i64s = 64 bytes)
        assert_eq!(std::mem::size_of::<Candle>(), 64);

        // Verify alignment
        assert_eq!(std::mem::align_of::<Candle>(), 8);
    }

    #[test]
    fn test_valid_candle() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4220,
            volume_scaled: 1_500_000_000, // 1500.0
            trade_count: 42,
        };

        assert!(candle.is_valid());
    }

    #[test]
    fn test_invalid_candle_timestamps() {
        let mut candle = Candle {
            ts_open: 1609459260000,
            ts_close: 1609459200000, // Close before open
            open_tick: 4200,
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4220,
            volume_scaled: 1_500_000_000,
            trade_count: 42,
        };

        assert!(!candle.is_valid());

        candle.ts_open = -1; // Negative timestamp
        candle.ts_close = 1609459200000;
        assert!(!candle.is_valid());
    }

    #[test]
    fn test_invalid_candle_ohlc() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4150, // High < Low
            low_tick: 4250,
            close_tick: 4220,
            volume_scaled: 1_500_000_000,
            trade_count: 42,
        };

        assert!(!candle.is_valid());
    }

    #[test]
    fn test_float_conversion() {
        let float_candle = CandleFloat {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open: 42000.5,
            high: 42500.0,
            low: 41500.25,
            close: 42200.75,
            volume: 1500.123456,
            trade_count: 42,
        };

        let tick_size = 0.25;
        let candle = Candle::from_float_prices(&float_candle, tick_size);

        assert_eq!(candle.open_tick, 168002); // 42000.5 / 0.25
        assert_eq!(candle.high_tick, 170000);
        assert_eq!(candle.low_tick, 166001);
        assert_eq!(candle.close_tick, 168803);

        let recovered = candle.to_float_prices(tick_size);
        assert!((recovered.open - float_candle.open).abs() < 0.01);
    }

    #[test]
    fn test_zero_copy_cast() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4220,
            volume_scaled: 1_500_000_000,
            trade_count: 42,
        };

        // Cast to bytes
        let bytes: &[u8] = bytemuck::bytes_of(&candle);
        assert_eq!(bytes.len(), 64);

        // Cast back from bytes
        let recovered: &Candle = bytemuck::from_bytes(bytes);
        assert_eq!(recovered.open_tick, candle.open_tick);
        assert_eq!(recovered.close_tick, candle.close_tick);
    }

    #[test]
    fn test_zero_copy_slice_cast() {
        let candles = vec![
            Candle {
                ts_open: 1609459200000,
                ts_close: 1609459260000,
                open_tick: 4200,
                high_tick: 4250,
                low_tick: 4150,
                close_tick: 4220,
                volume_scaled: 1_500_000_000,
                trade_count: 42,
            },
            Candle {
                ts_open: 1609459260000,
                ts_close: 1609459320000,
                open_tick: 4220,
                high_tick: 4280,
                low_tick: 4200,
                close_tick: 4250,
                volume_scaled: 2_000_000_000,
                trade_count: 56,
            },
        ];

        // Cast slice to bytes
        let bytes: &[u8] = bytemuck::cast_slice(&candles);
        assert_eq!(bytes.len(), 128); // 2 * 64 bytes

        // Cast back from bytes to slice
        let recovered: &[Candle] = bytemuck::cast_slice(bytes);
        assert_eq!(recovered.len(), 2);
        assert_eq!(recovered[0].open_tick, candles[0].open_tick);
        assert_eq!(recovered[1].close_tick, candles[1].close_tick);
    }

    #[test]
    fn test_candle_default() {
        let candle = Candle::default();

        // Default candle should be all zeros (from Zeroable)
        assert_eq!(candle.ts_open, 0);
        assert_eq!(candle.ts_close, 0);
        assert_eq!(candle.open_tick, 0);
        assert_eq!(candle.high_tick, 0);
        assert_eq!(candle.low_tick, 0);
        assert_eq!(candle.close_tick, 0);
        assert_eq!(candle.volume_scaled, 0);
        assert_eq!(candle.trade_count, 0);

        // Default candle should not be valid
        assert!(!candle.is_valid());
    }

    #[test]
    fn test_invalid_open_outside_range() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 5000, // Open > High
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4220,
            volume_scaled: 1_500_000_000,
            trade_count: 42,
        };

        assert!(!candle.is_valid());
    }

    #[test]
    fn test_invalid_close_outside_range() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4100, // Close < Low
            volume_scaled: 1_500_000_000,
            trade_count: 42,
        };

        assert!(!candle.is_valid());
    }

    #[test]
    fn test_invalid_negative_volume() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4220,
            volume_scaled: -1000,
            trade_count: 42,
        };

        assert!(!candle.is_valid());
    }

    #[test]
    fn test_invalid_negative_trade_count() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4220,
            volume_scaled: 1_500_000_000,
            trade_count: -1,
        };

        assert!(!candle.is_valid());
    }

    #[test]
    fn test_edge_case_equal_ohlc() {
        // All prices equal (flat candle)
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4200,
            low_tick: 4200,
            close_tick: 4200,
            volume_scaled: 1_500_000_000,
            trade_count: 42,
        };

        assert!(candle.is_valid());
    }

    #[test]
    fn test_edge_case_zero_volume() {
        let candle = Candle {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open_tick: 4200,
            high_tick: 4250,
            low_tick: 4150,
            close_tick: 4220,
            volume_scaled: 0,
            trade_count: 0,
        };

        assert!(candle.is_valid());
    }

    #[test]
    fn test_candle_float_validation() {
        let valid = CandleFloat {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open: 42000.5,
            high: 42500.0,
            low: 41500.25,
            close: 42200.75,
            volume: 1500.123,
            trade_count: 42,
        };

        assert!(valid.is_valid());

        // Test NaN
        let nan_candle = CandleFloat {
            open: f64::NAN,
            ..valid.clone()
        };
        assert!(!nan_candle.is_valid());

        // Test infinity
        let inf_candle = CandleFloat {
            high: f64::INFINITY,
            ..valid.clone()
        };
        assert!(!inf_candle.is_valid());

        // Test negative volume
        let neg_volume = CandleFloat {
            volume: -100.0,
            ..valid.clone()
        };
        assert!(!neg_volume.is_valid());
    }

    #[test]
    fn test_round_trip_conversion() {
        let original = CandleFloat {
            ts_open: 1609459200000,
            ts_close: 1609459260000,
            open: 42000.5,
            high: 42500.0,
            low: 41500.25,
            close: 42200.75,
            volume: 1500.123456789,
            trade_count: 42,
        };

        let tick_size = 0.25;

        // Convert to tick representation and back
        let tick_candle = Candle::from_float_prices(&original, tick_size);
        let recovered = tick_candle.to_float_prices(tick_size);

        // Prices should be within tick_size tolerance
        assert!((recovered.open - original.open).abs() < tick_size);
        assert!((recovered.high - original.high).abs() < tick_size);
        assert!((recovered.low - original.low).abs() < tick_size);
        assert!((recovered.close - original.close).abs() < tick_size);

        // Volume should be within floating point precision (6 decimals)
        assert!((recovered.volume - original.volume).abs() < 0.000001);

        // Timestamps and trade count should be exact
        assert_eq!(recovered.ts_open, original.ts_open);
        assert_eq!(recovered.ts_close, original.ts_close);
        assert_eq!(recovered.trade_count, original.trade_count);
    }
}
