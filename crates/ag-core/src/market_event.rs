//! Unified market event types for the Centurion engine

use crate::candle::Candle;

/// Source type for market data
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceType {
    Csv,
    Json,
    Parquet,
    WebSocket,
}

/// Data ingestion mode
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DataMode {
    /// Aggregate trades (existing)
    AggTrades(SourceType),

    /// OHLC bar data (new)
    OHLC(SourceType),

    /// Raw tick data (future)
    Ticks(SourceType),
}

/// Aggregate trade event (existing type, shown for completeness)
#[repr(C)]
#[derive(Copy, Clone, Debug)]
pub struct AggTrade {
    pub ts_ms: i64,
    pub price_tick: i64,
    pub qty_scaled: i64,
    pub side: u8, // 0 = BUY, 1 = SELL
}

/// Unified market event wrapper
#[derive(Debug, Clone, Copy)]
pub enum MarketEvent {
    /// Trade event
    Trade(AggTrade),

    /// Bar (OHLC) event
    Bar(Candle),
}

impl MarketEvent {
    /// Get the timestamp of this event
    #[inline]
    pub fn timestamp(&self) -> i64 {
        match self {
            MarketEvent::Trade(trade) => trade.ts_ms,
            MarketEvent::Bar(candle) => candle.ts_open,
        }
    }

    /// Check if this is a trade event
    #[inline]
    pub fn is_trade(&self) -> bool {
        matches!(self, MarketEvent::Trade(_))
    }

    /// Check if this is a bar event
    #[inline]
    pub fn is_bar(&self) -> bool {
        matches!(self, MarketEvent::Bar(_))
    }
}

// ============================================================================
// Event Loop Adapter
// ============================================================================

use crate::candle_parser::{CandleParser, ParseError};
use std::sync::atomic::{AtomicU64, Ordering};

/// Metrics for candle ingestion
#[derive(Debug, Default)]
pub struct IngestionMetrics {
    pub candles_processed: AtomicU64,
    pub candles_rejected: AtomicU64,
    pub parse_errors: AtomicU64,
}

impl IngestionMetrics {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn snapshot(&self) -> IngestionSnapshot {
        IngestionSnapshot {
            candles_processed: self.candles_processed.load(Ordering::Relaxed),
            candles_rejected: self.candles_rejected.load(Ordering::Relaxed),
            parse_errors: self.parse_errors.load(Ordering::Relaxed),
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct IngestionSnapshot {
    pub candles_processed: u64,
    pub candles_rejected: u64,
    pub parse_errors: u64,
}

/// Adapter that converts CandleParser into MarketEvent stream
pub struct CandleEventAdapter<P: CandleParser> {
    parser: P,
    metrics: IngestionMetrics,
}

impl<P: CandleParser> CandleEventAdapter<P> {
    pub fn new(parser: P) -> Self {
        Self {
            parser,
            metrics: IngestionMetrics::new(),
        }
    }

    pub fn metrics(&self) -> &IngestionMetrics {
        &self.metrics
    }

    pub fn tick_size(&self) -> f64 {
        self.parser.tick_size()
    }
}

impl<P: CandleParser> Iterator for CandleEventAdapter<P> {
    type Item = Result<MarketEvent, ParseError>;

    fn next(&mut self) -> Option<Self::Item> {
        match self.parser.next() {
            Some(Ok(candle)) => {
                self.metrics.candles_processed.fetch_add(1, Ordering::Relaxed);
                Some(Ok(MarketEvent::Bar(candle)))
            }
            Some(Err(e)) => {
                self.metrics.parse_errors.fetch_add(1, Ordering::Relaxed);
                Some(Err(e))
            }
            None => None,
        }
    }
}

// ============================================================================
// Channel-based Event Feed (for async event loops)
// ============================================================================

use std::sync::mpsc::{Receiver, channel};
use std::thread;

/// Spawns a background thread that feeds candles into a channel
pub fn spawn_candle_feeder<P: CandleParser + Send + 'static>(
    parser: P,
    _buffer_size: usize,
) -> (Receiver<Result<MarketEvent, ParseError>>, thread::JoinHandle<IngestionSnapshot>) {
    let (tx, rx) = channel();

    let handle = thread::spawn(move || {
        let mut adapter = CandleEventAdapter::new(parser);

        for event in &mut adapter {
            if tx.send(event).is_err() {
                // Receiver dropped, exit gracefully
                break;
            }
        }

        adapter.metrics.snapshot()
    });

    (rx, handle)
}

// ============================================================================
// Direct integration with engine
// ============================================================================

/// Process candles from parser and feed directly to engine callback
///
/// This is a zero-copy streaming approach where candles are processed
/// one at a time without buffering.
pub fn process_candles<P, F>(
    parser: P,
    mut on_event: F,
) -> Result<IngestionSnapshot, ParseError>
where
    P: CandleParser,
    F: FnMut(MarketEvent) -> Result<(), Box<dyn std::error::Error>>,
{
    let mut adapter = CandleEventAdapter::new(parser);

    for event_result in &mut adapter {
        match event_result {
            Ok(event) => {
                if let Err(e) = on_event(event) {
                    eprintln!("Engine error processing event: {}", e);
                    // Continue processing even if engine errors
                }
            }
            Err(parse_err) => {
                // Log parse error but continue
                eprintln!("Parse error: {}", parse_err);
            }
        }
    }

    Ok(adapter.metrics.snapshot())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::candle_parser::CsvCandleIter;
    use std::io::Cursor;

    #[test]
    fn test_market_event_timestamp() {
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

        let event = MarketEvent::Bar(candle);
        assert_eq!(event.timestamp(), 1609459200000);
        assert!(event.is_bar());
        assert!(!event.is_trade());
    }

    #[test]
    fn test_candle_event_adapter() {
        let csv_data = "\
timestamp,open,high,low,close,volume
1609459200000,42000,42500,41500,42200,1500
1609459260000,42200,42800,42100,42700,2000
";

        let cursor = Cursor::new(csv_data.as_bytes());
        let parser = CsvCandleIter::new(cursor, 1.0).unwrap();
        let mut adapter = CandleEventAdapter::new(parser);

        let event1 = adapter.next().unwrap().unwrap();
        assert!(event1.is_bar());

        let event2 = adapter.next().unwrap().unwrap();
        assert!(event2.is_bar());

        assert!(adapter.next().is_none());

        let metrics = adapter.metrics.snapshot();
        assert_eq!(metrics.candles_processed, 2);
        assert_eq!(metrics.parse_errors, 0);
    }

    #[test]
    fn test_process_candles() {
        let csv_data = "\
timestamp,open,high,low,close,volume
1609459200000,42000,42500,41500,42200,1500
";

        let cursor = Cursor::new(csv_data.as_bytes());
        let parser = CsvCandleIter::new(cursor, 1.0).unwrap();

        let mut events_received = Vec::new();

        let metrics = process_candles(parser, |event| {
            events_received.push(event);
            Ok(())
        }).unwrap();

        assert_eq!(events_received.len(), 1);
        assert_eq!(metrics.candles_processed, 1);
    }

    #[test]
    fn test_spawn_candle_feeder() {
        let csv_data = "\
timestamp,open,high,low,close,volume
1609459200000,42000,42500,41500,42200,1500
1609459260000,42200,42800,42100,42700,2000
1609459320000,42700,43000,42600,42900,1800
";

        let cursor = Cursor::new(csv_data.as_bytes());
        let parser = CsvCandleIter::new(cursor, 1.0).unwrap();

        let (rx, handle) = spawn_candle_feeder(parser, 100);

        let mut received_count = 0;
        for event_result in rx {
            match event_result {
                Ok(MarketEvent::Bar(_)) => {
                    received_count += 1;
                }
                Ok(MarketEvent::Trade(_)) => {
                    panic!("Unexpected trade event");
                }
                Err(e) => {
                    panic!("Parse error: {}", e);
                }
            }
        }

        let metrics = handle.join().expect("Thread panicked");
        assert_eq!(received_count, 3);
        assert_eq!(metrics.candles_processed, 3);
        assert_eq!(metrics.parse_errors, 0);
    }
}
