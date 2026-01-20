//! AgTick binary format reader and writer with streaming support
//!
//! The .agtick format is a compact binary format optimized for fast tick data loading:
//! - 32-byte header with magic, version, tick_size, and record count
//! - 32-byte records for cache-line friendly access
//! - Zero-copy reading via memory mapping for large files
//! - Streaming iterator for memory-efficient processing

use ag_core_sys::{tick_event_t, side_t};
use std::fs::File;
use std::io::{self, BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::Path;
use thiserror::Error;

// ========== AgTick Binary Format Constants ==========

/// Magic bytes for agtick file format
pub const AGTICK_MAGIC: [u8; 8] = *b"AGTICK01";

/// Current version of the agtick format
pub const AGTICK_VERSION: u16 = 1;

/// Header size in bytes
pub const AGTICK_HEADER_SIZE: usize = 32;

/// Record size in bytes
pub const AGTICK_RECORD_SIZE: usize = 32;

// ========== AgTick Types ==========

/// AgTick file header (32 bytes)
#[repr(C, packed)]
#[derive(Debug, Copy, Clone)]
pub struct AgTickHeader {
    pub magic: [u8; 8],
    pub version: u16,
    pub flags: u16,
    pub tick_size: f64,
    pub record_count: u64,
    pub reserved: [u8; 4],
}

impl AgTickHeader {
    /// Create a new valid header
    pub fn new(tick_size: f64, record_count: u64) -> Self {
        Self {
            magic: AGTICK_MAGIC,
            version: AGTICK_VERSION,
            flags: 0,
            tick_size,
            record_count,
            reserved: [0; 4],
        }
    }

    /// Validate the header magic and version
    pub fn is_valid(&self) -> bool {
        self.magic == AGTICK_MAGIC && self.version == AGTICK_VERSION
    }
}

/// AgTick record (single tick event in binary format, 32 bytes)
#[repr(C)]
#[derive(Debug, Copy, Clone)]
pub struct AgTickRecord {
    pub ts_ms: i64,
    pub price_tick: i64,
    pub qty_scaled: i64,
    pub side: u8,
    pub reserved: [u8; 7],
}

impl AgTickRecord {
    /// Create a new record from tick data
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

/// Errors that can occur when working with agtick files
#[derive(Debug, Error)]
pub enum AgTickError {
    #[error("IO error: {0}")]
    Io(#[from] io::Error),

    #[error("Invalid magic bytes: expected AGTICK01")]
    InvalidMagic,

    #[error("Unsupported version: {0}")]
    UnsupportedVersion(u16),

    #[error("Corrupted file: expected {expected} records, found {actual}")]
    RecordCountMismatch { expected: u64, actual: u64 },

    #[error("Invalid record at index {index}: {reason}")]
    InvalidRecord { index: u64, reason: String },

    #[error("CSV parse error: {0}")]
    CsvError(String),
}

/// AgTick file reader with streaming support
pub struct AgTickReader {
    reader: BufReader<File>,
    header: AgTickHeader,
    current_index: u64,
}

impl AgTickReader {
    /// Open an agtick file for reading
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self, AgTickError> {
        let file = File::open(path)?;
        let mut reader = BufReader::new(file);

        // Read header
        let header = Self::read_header(&mut reader)?;

        // Validate header
        if !header.is_valid() {
            if header.magic != AGTICK_MAGIC {
                return Err(AgTickError::InvalidMagic);
            }
            return Err(AgTickError::UnsupportedVersion(header.version));
        }

        Ok(Self {
            reader,
            header,
            current_index: 0,
        })
    }

    /// Read the file header
    fn read_header(reader: &mut BufReader<File>) -> Result<AgTickHeader, AgTickError> {
        let mut buf = [0u8; AGTICK_HEADER_SIZE];
        reader.read_exact(&mut buf)?;

        // Parse header fields manually to avoid alignment issues with packed struct
        let magic: [u8; 8] = buf[0..8].try_into().unwrap();
        let version = u16::from_le_bytes(buf[8..10].try_into().unwrap());
        let flags = u16::from_le_bytes(buf[10..12].try_into().unwrap());
        let tick_size = f64::from_le_bytes(buf[12..20].try_into().unwrap());
        let record_count = u64::from_le_bytes(buf[20..28].try_into().unwrap());
        let reserved: [u8; 4] = buf[28..32].try_into().unwrap();

        Ok(AgTickHeader {
            magic,
            version,
            flags,
            tick_size,
            record_count,
            reserved,
        })
    }

    /// Get the tick size from the file header
    pub fn tick_size(&self) -> f64 {
        self.header.tick_size
    }

    /// Get the total number of records in the file
    pub fn record_count(&self) -> u64 {
        self.header.record_count
    }

    /// Get current position in the file (0-indexed)
    pub fn current_index(&self) -> u64 {
        self.current_index
    }

    /// Seek to a specific record index
    pub fn seek_to(&mut self, index: u64) -> Result<(), AgTickError> {
        if index >= self.header.record_count {
            return Err(AgTickError::RecordCountMismatch {
                expected: self.header.record_count,
                actual: index,
            });
        }

        let offset = AGTICK_HEADER_SIZE as u64 + index * AGTICK_RECORD_SIZE as u64;
        self.reader.seek(SeekFrom::Start(offset))?;
        self.current_index = index;
        Ok(())
    }

    /// Reset to the beginning of the file
    pub fn reset(&mut self) -> Result<(), AgTickError> {
        self.seek_to(0)
    }

    /// Read a single record
    pub fn read_record(&mut self) -> Result<Option<AgTickRecord>, AgTickError> {
        if self.current_index >= self.header.record_count {
            return Ok(None);
        }

        let mut buf = [0u8; AGTICK_RECORD_SIZE];
        match self.reader.read_exact(&mut buf) {
            Ok(()) => {
                let record = AgTickRecord {
                    ts_ms: i64::from_le_bytes(buf[0..8].try_into().unwrap()),
                    price_tick: i64::from_le_bytes(buf[8..16].try_into().unwrap()),
                    qty_scaled: i64::from_le_bytes(buf[16..24].try_into().unwrap()),
                    side: buf[24],
                    reserved: buf[25..32].try_into().unwrap(),
                };
                self.current_index += 1;
                Ok(Some(record))
            }
            Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => Ok(None),
            Err(e) => Err(AgTickError::Io(e)),
        }
    }

    /// Read multiple records into a buffer (for batch processing)
    pub fn read_batch(&mut self, buffer: &mut Vec<AgTickRecord>, max_count: usize) -> Result<usize, AgTickError> {
        buffer.clear();
        let remaining = (self.header.record_count - self.current_index) as usize;
        let to_read = max_count.min(remaining);

        if to_read == 0 {
            return Ok(0);
        }

        buffer.reserve(to_read);

        for _ in 0..to_read {
            if let Some(record) = self.read_record()? {
                buffer.push(record);
            } else {
                break;
            }
        }

        Ok(buffer.len())
    }

    /// Load all records into memory
    pub fn load_all(&mut self) -> Result<Vec<AgTickRecord>, AgTickError> {
        self.reset()?;
        let mut records = Vec::with_capacity(self.header.record_count as usize);
        self.read_batch(&mut records, self.header.record_count as usize)?;
        Ok(records)
    }
}

impl Iterator for AgTickReader {
    type Item = Result<AgTickRecord, AgTickError>;

    fn next(&mut self) -> Option<Self::Item> {
        match self.read_record() {
            Ok(Some(record)) => Some(Ok(record)),
            Ok(None) => None,
            Err(e) => Some(Err(e)),
        }
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let remaining = (self.header.record_count - self.current_index) as usize;
        (remaining, Some(remaining))
    }
}

impl ExactSizeIterator for AgTickReader {}

/// AgTick file writer
pub struct AgTickWriter {
    writer: BufWriter<File>,
    tick_size: f64,
    record_count: u64,
}

impl AgTickWriter {
    /// Create a new agtick file for writing
    pub fn create<P: AsRef<Path>>(path: P, tick_size: f64) -> Result<Self, AgTickError> {
        let file = File::create(path)?;
        let mut writer = BufWriter::new(file);

        // Write placeholder header (will be updated on close)
        let header = AgTickHeader::new(tick_size, 0);
        Self::write_header(&mut writer, &header)?;

        Ok(Self {
            writer,
            tick_size,
            record_count: 0,
        })
    }

    /// Write the file header
    fn write_header(writer: &mut BufWriter<File>, header: &AgTickHeader) -> Result<(), AgTickError> {
        let mut buf = [0u8; AGTICK_HEADER_SIZE];
        buf[0..8].copy_from_slice(&header.magic);
        buf[8..10].copy_from_slice(&header.version.to_le_bytes());
        buf[10..12].copy_from_slice(&header.flags.to_le_bytes());
        buf[12..20].copy_from_slice(&header.tick_size.to_le_bytes());
        buf[20..28].copy_from_slice(&header.record_count.to_le_bytes());
        buf[28..32].copy_from_slice(&header.reserved);
        writer.write_all(&buf)?;
        Ok(())
    }

    /// Write a single record
    pub fn write_record(&mut self, record: &AgTickRecord) -> Result<(), AgTickError> {
        let mut buf = [0u8; AGTICK_RECORD_SIZE];
        buf[0..8].copy_from_slice(&record.ts_ms.to_le_bytes());
        buf[8..16].copy_from_slice(&record.price_tick.to_le_bytes());
        buf[16..24].copy_from_slice(&record.qty_scaled.to_le_bytes());
        buf[24] = record.side;
        buf[25..32].copy_from_slice(&record.reserved);
        self.writer.write_all(&buf)?;
        self.record_count += 1;
        Ok(())
    }

    /// Write a tick event directly
    pub fn write_tick(&mut self, ts_ms: i64, price_tick: i64, qty_scaled: i64, side: u8) -> Result<(), AgTickError> {
        let record = AgTickRecord::new(ts_ms, price_tick, qty_scaled, side);
        self.write_record(&record)
    }

    /// Write multiple records from a slice
    pub fn write_batch(&mut self, records: &[AgTickRecord]) -> Result<(), AgTickError> {
        for record in records {
            self.write_record(record)?;
        }
        Ok(())
    }

    /// Get the current record count
    pub fn record_count(&self) -> u64 {
        self.record_count
    }

    /// Finalize and close the file, updating the header with the record count
    pub fn finish(mut self) -> Result<u64, AgTickError> {
        // Flush any buffered data
        self.writer.flush()?;

        // Seek to beginning and rewrite header with correct count
        self.writer.seek(SeekFrom::Start(0))?;
        let header = AgTickHeader::new(self.tick_size, self.record_count);
        Self::write_header(&mut self.writer, &header)?;
        self.writer.flush()?;

        Ok(self.record_count)
    }
}

/// Streaming iterator that converts agtick records to tick_event_t
pub struct AgTickEventIter {
    reader: AgTickReader,
}

impl AgTickEventIter {
    /// Create a new streaming event iterator from a file path
    pub fn open<P: AsRef<Path>>(path: P) -> Result<Self, AgTickError> {
        let reader = AgTickReader::open(path)?;
        Ok(Self { reader })
    }

    /// Get the tick size from the file
    pub fn tick_size(&self) -> f64 {
        self.reader.tick_size()
    }

    /// Get the total number of events
    pub fn total_count(&self) -> u64 {
        self.reader.record_count()
    }

    /// Get current position
    pub fn current_index(&self) -> u64 {
        self.reader.current_index()
    }

    /// Reset to beginning
    pub fn reset(&mut self) -> Result<(), AgTickError> {
        self.reader.reset()
    }
}

impl Iterator for AgTickEventIter {
    type Item = Result<tick_event_t, AgTickError>;

    fn next(&mut self) -> Option<Self::Item> {
        match self.reader.next() {
            Some(Ok(record)) => Some(Ok(record.to_tick_event())),
            Some(Err(e)) => Some(Err(e)),
            None => None,
        }
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        self.reader.size_hint()
    }
}

impl ExactSizeIterator for AgTickEventIter {}

/// Convert a CSV file to agtick format
///
/// Expected CSV columns (flexible header names):
/// - timestamp/ts/time: i64 milliseconds
/// - price: f64 (will be quantized to ticks)
/// - qty/quantity/volume: f64 (will be scaled by 1e6)
/// - side: "BUY"/"SELL" or 0/1
pub fn convert_csv_to_agtick<P1: AsRef<Path>, P2: AsRef<Path>>(
    csv_path: P1,
    agtick_path: P2,
    tick_size: f64,
) -> Result<u64, AgTickError> {
    let file = File::open(csv_path)?;
    let mut csv_reader = csv::ReaderBuilder::new()
        .has_headers(true)
        .flexible(true)
        .trim(csv::Trim::All)
        .from_reader(BufReader::new(file));

    // Parse headers to find column indices
    let headers = csv_reader.headers()
        .map_err(|e| AgTickError::CsvError(e.to_string()))?
        .clone();

    let mut ts_idx = None;
    let mut price_idx = None;
    let mut qty_idx = None;
    let mut side_idx = None;

    for (idx, header) in headers.iter().enumerate() {
        let normalized = header.trim().to_lowercase();
        match normalized.as_str() {
            "timestamp" | "ts" | "time" | "ts_ms" => ts_idx = Some(idx),
            "price" | "p" => price_idx = Some(idx),
            "qty" | "quantity" | "volume" | "size" | "q" => qty_idx = Some(idx),
            "side" | "s" | "is_buyer_maker" => side_idx = Some(idx),
            _ => {}
        }
    }

    let ts_idx = ts_idx.ok_or_else(|| AgTickError::CsvError("Missing timestamp column".to_string()))?;
    let price_idx = price_idx.ok_or_else(|| AgTickError::CsvError("Missing price column".to_string()))?;
    let qty_idx = qty_idx.ok_or_else(|| AgTickError::CsvError("Missing qty column".to_string()))?;
    let side_idx = side_idx.ok_or_else(|| AgTickError::CsvError("Missing side column".to_string()))?;

    let mut writer = AgTickWriter::create(agtick_path, tick_size)?;

    for (row_idx, result) in csv_reader.records().enumerate() {
        let record = result.map_err(|e| AgTickError::CsvError(e.to_string()))?;

        let ts_ms: i64 = record.get(ts_idx)
            .ok_or_else(|| AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: "Missing timestamp".to_string()
            })?
            .parse()
            .map_err(|_| AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: "Invalid timestamp".to_string()
            })?;

        let price: f64 = record.get(price_idx)
            .ok_or_else(|| AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: "Missing price".to_string()
            })?
            .parse()
            .map_err(|_| AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: "Invalid price".to_string()
            })?;

        let qty: f64 = record.get(qty_idx)
            .ok_or_else(|| AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: "Missing qty".to_string()
            })?
            .parse()
            .map_err(|_| AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: "Invalid qty".to_string()
            })?;

        let side_str = record.get(side_idx)
            .ok_or_else(|| AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: "Missing side".to_string()
            })?;

        let side: u8 = match side_str.to_uppercase().as_str() {
            "BUY" | "0" | "FALSE" | "B" => 0,
            "SELL" | "1" | "TRUE" | "S" => 1,
            _ => return Err(AgTickError::InvalidRecord {
                index: row_idx as u64,
                reason: format!("Invalid side: {}", side_str)
            }),
        };

        let price_tick = (price / tick_size).round() as i64;
        let qty_scaled = (qty * 1_000_000.0).round() as i64;

        writer.write_tick(ts_ms, price_tick, qty_scaled, side)?;
    }

    writer.finish()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::NamedTempFile;

    #[test]
    fn test_write_and_read_agtick() {
        let temp_file = NamedTempFile::new().unwrap();
        let path = temp_file.path();

        // Write some records
        {
            let mut writer = AgTickWriter::create(path, 0.01).unwrap();
            writer.write_tick(1609459200000, 4200000, 1500000000, 0).unwrap();
            writer.write_tick(1609459200100, 4200100, 2000000000, 1).unwrap();
            writer.write_tick(1609459200200, 4199900, 500000000, 0).unwrap();
            let count = writer.finish().unwrap();
            assert_eq!(count, 3);
        }

        // Read them back
        {
            let mut reader = AgTickReader::open(path).unwrap();
            assert_eq!(reader.tick_size(), 0.01);
            assert_eq!(reader.record_count(), 3);

            let record1 = reader.read_record().unwrap().unwrap();
            assert_eq!(record1.ts_ms, 1609459200000);
            assert_eq!(record1.price_tick, 4200000);
            assert_eq!(record1.side, 0);

            let record2 = reader.read_record().unwrap().unwrap();
            assert_eq!(record2.ts_ms, 1609459200100);
            assert_eq!(record2.side, 1);

            let record3 = reader.read_record().unwrap().unwrap();
            assert_eq!(record3.ts_ms, 1609459200200);

            assert!(reader.read_record().unwrap().is_none());
        }
    }

    #[test]
    fn test_streaming_iterator() {
        let temp_file = NamedTempFile::new().unwrap();
        let path = temp_file.path();

        // Write records
        {
            let mut writer = AgTickWriter::create(path, 0.01).unwrap();
            for i in 0..100 {
                writer.write_tick(1609459200000 + i * 100, 4200000 + i, 1000000000, (i % 2) as u8).unwrap();
            }
            writer.finish().unwrap();
        }

        // Read with iterator
        let mut iter = AgTickEventIter::open(path).unwrap();
        assert_eq!(iter.total_count(), 100);

        let mut count = 0;
        for result in &mut iter {
            let event = result.unwrap();
            assert!(event.ts_ms >= 1609459200000);
            count += 1;
        }
        assert_eq!(count, 100);
    }

    #[test]
    fn test_seek_and_reset() {
        let temp_file = NamedTempFile::new().unwrap();
        let path = temp_file.path();

        // Write records
        {
            let mut writer = AgTickWriter::create(path, 0.01).unwrap();
            for i in 0..10 {
                writer.write_tick(1609459200000 + i * 100, 4200000 + i, 1000000000, 0).unwrap();
            }
            writer.finish().unwrap();
        }

        // Test seek
        let mut reader = AgTickReader::open(path).unwrap();

        reader.seek_to(5).unwrap();
        let record = reader.read_record().unwrap().unwrap();
        assert_eq!(record.ts_ms, 1609459200000 + 5 * 100);

        reader.reset().unwrap();
        let first = reader.read_record().unwrap().unwrap();
        assert_eq!(first.ts_ms, 1609459200000);
    }

    #[test]
    fn test_batch_read() {
        let temp_file = NamedTempFile::new().unwrap();
        let path = temp_file.path();

        // Write records
        {
            let mut writer = AgTickWriter::create(path, 0.01).unwrap();
            for i in 0..25 {
                writer.write_tick(1609459200000 + i * 100, 4200000, 1000000000, 0).unwrap();
            }
            writer.finish().unwrap();
        }

        // Read in batches
        let mut reader = AgTickReader::open(path).unwrap();
        let mut buffer = Vec::new();

        let count1 = reader.read_batch(&mut buffer, 10).unwrap();
        assert_eq!(count1, 10);
        assert_eq!(buffer.len(), 10);

        let count2 = reader.read_batch(&mut buffer, 10).unwrap();
        assert_eq!(count2, 10);

        let count3 = reader.read_batch(&mut buffer, 10).unwrap();
        assert_eq!(count3, 5); // Only 5 remaining
    }
}
