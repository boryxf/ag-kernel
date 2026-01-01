//! Streaming OHLC candle parsers with zero-copy optimization

use crate::candle::{Candle, CandleFloat};
use std::io::Read;
use thiserror::Error;

/// Parse errors for candle ingestion
#[derive(Debug, Error)]
pub enum ParseError {
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("CSV error: {0}")]
    Csv(#[from] csv::Error),

    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("Missing required field: {0}")]
    MissingField(String),

    #[error("Invalid value for field {field}: {value}")]
    InvalidValue { field: String, value: String },

    #[error("Invalid candle data: {0}")]
    InvalidCandle(String),

    #[error("Header mapping error: {0}")]
    HeaderMapping(String),
}

/// Trait for streaming candle parsers
pub trait CandleParser: Iterator<Item = Result<Candle, ParseError>> {
    /// Get the tick size used for quantization
    fn tick_size(&self) -> f64;

    /// Estimate total number of candles (if known)
    fn size_hint_total(&self) -> Option<usize> {
        None
    }
}

// ============================================================================
// CSV Parser Implementation
// ============================================================================

/// Streaming CSV candle parser with flexible header mapping
pub struct CsvCandleIter<R: Read> {
    reader: csv::Reader<R>,
    tick_size: f64,
    header_map: HeaderMap,
    _current_position: usize,
}

/// Maps CSV column indices to candle fields
#[derive(Debug)]
struct HeaderMap {
    ts_open_idx: Option<usize>,
    ts_close_idx: Option<usize>,
    open_idx: usize,
    high_idx: usize,
    low_idx: usize,
    close_idx: usize,
    volume_idx: usize,
    trade_count_idx: Option<usize>,
}

impl HeaderMap {
    /// Build header map from CSV headers with flexible matching
    fn from_headers(headers: &csv::StringRecord) -> Result<Self, ParseError> {
        let mut ts_open_idx = None;
        let mut ts_close_idx = None;
        let mut open_idx = None;
        let mut high_idx = None;
        let mut low_idx = None;
        let mut close_idx = None;
        let mut volume_idx = None;
        let mut trade_count_idx = None;

        for (idx, header) in headers.iter().enumerate() {
            let normalized = header.trim().to_lowercase();

            match normalized.as_str() {
                // Timestamp fields
                "timestamp" | "ts" | "time" | "ts_open" | "open_time" => {
                    ts_open_idx = Some(idx);
                }
                "ts_close" | "close_time" | "timestamp_close" => {
                    ts_close_idx = Some(idx);
                }
                // OHLC fields
                "open" | "o" | "open_price" => {
                    open_idx = Some(idx);
                }
                "high" | "h" | "high_price" => {
                    high_idx = Some(idx);
                }
                "low" | "l" | "low_price" => {
                    low_idx = Some(idx);
                }
                "close" | "c" | "close_price" => {
                    close_idx = Some(idx);
                }
                // Volume
                "volume" | "v" | "vol" | "base_volume" => {
                    volume_idx = Some(idx);
                }
                // Trade count
                "trades" | "trade_count" | "num_trades" | "count" => {
                    trade_count_idx = Some(idx);
                }
                _ => {} // Ignore unknown columns
            }
        }

        // Validate required fields
        Ok(Self {
            ts_open_idx,
            ts_close_idx,
            open_idx: open_idx.ok_or_else(|| {
                ParseError::HeaderMapping("Missing 'open' column".to_string())
            })?,
            high_idx: high_idx.ok_or_else(|| {
                ParseError::HeaderMapping("Missing 'high' column".to_string())
            })?,
            low_idx: low_idx.ok_or_else(|| {
                ParseError::HeaderMapping("Missing 'low' column".to_string())
            })?,
            close_idx: close_idx.ok_or_else(|| {
                ParseError::HeaderMapping("Missing 'close' column".to_string())
            })?,
            volume_idx: volume_idx.ok_or_else(|| {
                ParseError::HeaderMapping("Missing 'volume' column".to_string())
            })?,
            trade_count_idx,
        })
    }
}

impl<R: Read> CsvCandleIter<R> {
    /// Create a new CSV candle iterator
    ///
    /// # Arguments
    /// * `reader` - Buffered reader for CSV data
    /// * `tick_size` - Tick size for price quantization
    pub fn new(reader: R, tick_size: f64) -> Result<Self, ParseError> {
        let mut csv_reader = csv::ReaderBuilder::new()
            .has_headers(true)
            .flexible(false) // Strict column count
            .trim(csv::Trim::All)
            .from_reader(reader);

        // Parse headers
        let headers = csv_reader.headers()?.clone();
        let header_map = HeaderMap::from_headers(&headers)?;

        Ok(Self {
            reader: csv_reader,
            tick_size,
            header_map,
            _current_position: 0,
        })
    }

    /// Parse a single record into a CandleFloat
    fn parse_record(&self, record: &csv::StringRecord) -> Result<CandleFloat, ParseError> {
        // Helper to parse field
        let parse_f64 = |idx: usize, field_name: &str| -> Result<f64, ParseError> {
            let value_str = record.get(idx).ok_or_else(|| {
                ParseError::MissingField(field_name.to_string())
            })?;

            value_str.parse::<f64>().map_err(|_| ParseError::InvalidValue {
                field: field_name.to_string(),
                value: value_str.to_string(),
            })
        };

        let parse_i64 = |idx: usize, field_name: &str| -> Result<i64, ParseError> {
            let value_str = record.get(idx).ok_or_else(|| {
                ParseError::MissingField(field_name.to_string())
            })?;

            value_str.parse::<i64>().map_err(|_| ParseError::InvalidValue {
                field: field_name.to_string(),
                value: value_str.to_string(),
            })
        };

        // Parse OHLC
        let open = parse_f64(self.header_map.open_idx, "open")?;
        let high = parse_f64(self.header_map.high_idx, "high")?;
        let low = parse_f64(self.header_map.low_idx, "low")?;
        let close = parse_f64(self.header_map.close_idx, "close")?;
        let volume = parse_f64(self.header_map.volume_idx, "volume")?;

        // Parse timestamps
        let ts_open = if let Some(idx) = self.header_map.ts_open_idx {
            parse_i64(idx, "ts_open")?
        } else {
            // If no open timestamp, use close timestamp or default
            if let Some(idx) = self.header_map.ts_close_idx {
                parse_i64(idx, "ts_close")? - 60000 // Assume 1-minute candle
            } else {
                return Err(ParseError::MissingField("timestamp".to_string()));
            }
        };

        let ts_close = if let Some(idx) = self.header_map.ts_close_idx {
            parse_i64(idx, "ts_close")?
        } else {
            ts_open + 60000 // Default to 1-minute candle
        };

        let trade_count = if let Some(idx) = self.header_map.trade_count_idx {
            parse_i64(idx, "trade_count")?
        } else {
            0 // Unknown trade count
        };

        Ok(CandleFloat {
            ts_open,
            ts_close,
            open,
            high,
            low,
            close,
            volume,
            trade_count,
        })
    }
}

impl<R: Read> Iterator for CsvCandleIter<R> {
    type Item = Result<Candle, ParseError>;

    fn next(&mut self) -> Option<Self::Item> {
        let mut record = csv::StringRecord::new();

        match self.reader.read_record(&mut record) {
            Ok(true) => {
                // Parse record
                match self.parse_record(&record) {
                    Ok(float_candle) => {
                        // Validate
                        if !float_candle.is_valid() {
                            return Some(Err(ParseError::InvalidCandle(
                                format!("Invalid OHLC data at record: {:?}", record)
                            )));
                        }

                        // Convert to quantized candle
                        let candle = Candle::from_float_prices(&float_candle, self.tick_size);

                        // Double-check after quantization
                        if !candle.is_valid() {
                            return Some(Err(ParseError::InvalidCandle(
                                "Candle invalid after quantization".to_string()
                            )));
                        }

                        Some(Ok(candle))
                    }
                    Err(e) => Some(Err(e)),
                }
            }
            Ok(false) => None, // End of file
            Err(e) => Some(Err(ParseError::Csv(e))),
        }
    }
}

impl<R: Read> CandleParser for CsvCandleIter<R> {
    fn tick_size(&self) -> f64 {
        self.tick_size
    }
}

// ============================================================================
// JSON Parser Implementation
// ============================================================================

/// Streaming JSON candle parser
pub struct JsonCandleIter<R: Read> {
    deserializer: serde_json::StreamDeserializer<'static, serde_json::de::IoRead<R>, CandleJson>,
    tick_size: f64,
}

/// JSON representation of a candle for serde
#[derive(serde::Deserialize, Debug)]
struct CandleJson {
    #[serde(alias = "ts", alias = "timestamp", alias = "time")]
    ts_open: Option<i64>,

    #[serde(alias = "timestamp_close", alias = "close_time")]
    ts_close: Option<i64>,

    #[serde(alias = "o", alias = "open_price")]
    open: f64,

    #[serde(alias = "h", alias = "high_price")]
    high: f64,

    #[serde(alias = "l", alias = "low_price")]
    low: f64,

    #[serde(alias = "c", alias = "close_price")]
    close: f64,

    #[serde(alias = "v", alias = "vol")]
    volume: f64,

    #[serde(alias = "trades", alias = "num_trades", default)]
    trade_count: Option<i64>,
}

impl<R: Read> JsonCandleIter<R> {
    /// Create a new JSON candle iterator
    ///
    /// Expects newline-delimited JSON (NDJSON) format
    pub fn new(reader: R, tick_size: f64) -> Self {
        let deserializer = serde_json::Deserializer::from_reader(reader)
            .into_iter::<CandleJson>();

        Self {
            deserializer: unsafe {
                // SAFETY: We ensure R: 'static or manage lifetime appropriately
                std::mem::transmute(deserializer)
            },
            tick_size,
        }
    }
}

impl<R: Read> Iterator for JsonCandleIter<R> {
    type Item = Result<Candle, ParseError>;

    fn next(&mut self) -> Option<Self::Item> {
        match self.deserializer.next() {
            Some(Ok(candle_json)) => {
                // Convert to CandleFloat
                let ts_open = candle_json.ts_open.unwrap_or(0);
                let ts_close = candle_json.ts_close.unwrap_or(ts_open + 60000);

                let float_candle = CandleFloat {
                    ts_open,
                    ts_close,
                    open: candle_json.open,
                    high: candle_json.high,
                    low: candle_json.low,
                    close: candle_json.close,
                    volume: candle_json.volume,
                    trade_count: candle_json.trade_count.unwrap_or(0),
                };

                // Validate
                if !float_candle.is_valid() {
                    return Some(Err(ParseError::InvalidCandle(
                        format!("Invalid OHLC data: {:?}", candle_json)
                    )));
                }

                // Convert to quantized candle
                let candle = Candle::from_float_prices(&float_candle, self.tick_size);

                if !candle.is_valid() {
                    return Some(Err(ParseError::InvalidCandle(
                        "Candle invalid after quantization".to_string()
                    )));
                }

                Some(Ok(candle))
            }
            Some(Err(e)) => Some(Err(ParseError::Json(e))),
            None => None,
        }
    }
}

impl<R: Read> CandleParser for JsonCandleIter<R> {
    fn tick_size(&self) -> f64 {
        self.tick_size
    }
}

// ============================================================================
// Convenience constructors
// ============================================================================

/// Create a candle parser from a file path based on extension
pub fn from_file_path(
    path: impl AsRef<std::path::Path>,
    tick_size: f64,
) -> Result<Box<dyn CandleParser>, ParseError> {
    let path = path.as_ref();
    let file = std::fs::File::open(path)?;
    let reader = std::io::BufReader::new(file);

    match path.extension().and_then(|s| s.to_str()) {
        Some("csv") => {
            Ok(Box::new(CsvCandleIter::new(reader, tick_size)?))
        }
        Some("json") | Some("jsonl") | Some("ndjson") => {
            Ok(Box::new(JsonCandleIter::new(reader, tick_size)))
        }
        _ => Err(ParseError::InvalidValue {
            field: "file_extension".to_string(),
            value: format!("{:?}", path.extension()),
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    #[test]
    fn test_csv_parser_basic() {
        let csv_data = "\
timestamp,open,high,low,close,volume
1609459200000,42000.5,42500.0,41500.0,42200.0,1500.5
1609459260000,42200.0,42800.0,42100.0,42700.0,2000.3
";

        let cursor = Cursor::new(csv_data.as_bytes());
        let mut parser = CsvCandleIter::new(cursor, 0.5).unwrap();

        let candle1 = parser.next().unwrap().unwrap();
        assert_eq!(candle1.ts_open, 1609459200000);
        assert_eq!(candle1.open_tick, 84001); // 42000.5 / 0.5

        let candle2 = parser.next().unwrap().unwrap();
        assert_eq!(candle2.ts_open, 1609459260000);

        assert!(parser.next().is_none());
    }

    #[test]
    fn test_csv_parser_flexible_headers() {
        let csv_data = "\
time,o,h,l,c,vol
1609459200000,42000,42500,41500,42200,1500
";

        let cursor = Cursor::new(csv_data.as_bytes());
        let mut parser = CsvCandleIter::new(cursor, 1.0).unwrap();

        let candle = parser.next().unwrap().unwrap();
        assert_eq!(candle.open_tick, 42000);
        assert_eq!(candle.high_tick, 42500);
    }

    #[test]
    fn test_csv_parser_invalid_data() {
        let csv_data = "\
timestamp,open,high,low,close,volume
1609459200000,42500,42000,41500,42200,1500
";  // high < open (will fail validation)

        let cursor = Cursor::new(csv_data.as_bytes());
        let mut parser = CsvCandleIter::new(cursor, 1.0).unwrap();

        // This should return an error due to invalid OHLC
        let result = parser.next().unwrap();
        assert!(result.is_err());
    }

    #[test]
    fn test_json_parser_basic() {
        let json_data = r#"
{"ts_open":1609459200000,"ts_close":1609459260000,"open":42000,"high":42500,"low":41500,"close":42200,"volume":1500}
{"ts_open":1609459260000,"ts_close":1609459320000,"open":42200,"high":42800,"low":42100,"close":42700,"volume":2000}
"#;

        let cursor = Cursor::new(json_data.as_bytes());
        let mut parser = JsonCandleIter::new(cursor, 1.0);

        let candle1 = parser.next().unwrap().unwrap();
        assert_eq!(candle1.ts_open, 1609459200000);
        assert_eq!(candle1.open_tick, 42000);

        let candle2 = parser.next().unwrap().unwrap();
        assert_eq!(candle2.close_tick, 42700);

        assert!(parser.next().is_none());
    }
}
