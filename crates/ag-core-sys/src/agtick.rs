//! FFI bindings for the ag-kernel custom binary tick format (.agtick)
//!
//! This module provides safe Rust wrappers around the C agtick library for
//! reading and writing compact binary tick data files.
//!
//! # Format Features
//! - Delta-encoded timestamps and prices
//! - Varint-encoded quantities
//! - Bit-packed side flags
//! - 5-10x smaller than CSV
//! - Optional zero-copy memory mapping
//!
//! # Example
//! ```ignore
//! use ag_core_sys::agtick::{AgTickWriter, AgTickReader, AgTickMmap};
//!
//! // Write ticks
//! let ticks = vec![/* ... */];
//! AgTickWriter::write("data.agtick", &ticks, "BTCUSDT", 0.01)?;
//!
//! // Read ticks (allocating)
//! let (ticks, header) = AgTickReader::read("data.agtick")?;
//!
//! // Memory-mapped reading (zero-copy)
//! let mmap = AgTickMmap::open("data.agtick")?;
//! for tick in mmap.iter() {
//!     // process tick
//! }
//! ```

#![allow(non_camel_case_types)]

use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_double, c_int};
use std::path::Path;
use std::ptr;

use super::{side_t, tick_event_t};

// ========== Constants ==========

pub const AGTICK_MAGIC: &[u8; 4] = b"AGTK";
pub const AGTICK_VERSION: u8 = 1;
pub const AGTICK_SYMBOL_LEN: usize = 16;
pub const AGTICK_HEADER_SIZE: usize = 64;

// Error codes
pub const AGTICK_OK: c_int = 0;
pub const AGTICK_ERR_IO: c_int = -1;
pub const AGTICK_ERR_MAGIC: c_int = -2;
pub const AGTICK_ERR_VERSION: c_int = -3;
pub const AGTICK_ERR_CORRUPT: c_int = -4;
pub const AGTICK_ERR_NOMEM: c_int = -5;
pub const AGTICK_ERR_PARAM: c_int = -6;
pub const AGTICK_ERR_MMAP: c_int = -7;

// ========== C Types ==========

/// File header structure (64 bytes)
#[repr(C, packed)]
#[derive(Debug, Clone, Copy)]
pub struct agtick_header_t {
    pub magic: [c_char; 4],
    pub version: u8,
    pub flags: [u8; 3],
    pub symbol: [c_char; AGTICK_SYMBOL_LEN],
    pub tick_size: c_double,
    pub start_ts: i64,
    pub end_ts: i64,
    pub tick_count: u64,
    pub data_offset: u64,
}

impl Default for agtick_header_t {
    fn default() -> Self {
        Self {
            magic: [0; 4],
            version: 0,
            flags: [0; 3],
            symbol: [0; AGTICK_SYMBOL_LEN],
            tick_size: 0.0,
            start_ts: 0,
            end_ts: 0,
            tick_count: 0,
            data_offset: 0,
        }
    }
}

impl agtick_header_t {
    /// Get the symbol as a Rust string
    pub fn symbol_str(&self) -> String {
        let bytes: Vec<u8> = self
            .symbol
            .iter()
            .take_while(|&&c| c != 0)
            .map(|&c| c as u8)
            .collect();
        String::from_utf8_lossy(&bytes).to_string()
    }
}

/// Opaque handle for memory-mapped file
#[repr(C)]
pub struct agtick_mmap_handle_s {
    _private: [u8; 0],
}

pub type agtick_mmap_handle_t = agtick_mmap_handle_s;

// ========== C Function Bindings ==========

extern "C" {
    pub fn agtick_write(
        path: *const c_char,
        ticks: *const tick_event_t,
        count: u64,
        symbol: *const c_char,
        tick_size: c_double,
    ) -> c_int;

    pub fn agtick_read(
        path: *const c_char,
        ticks_out: *mut *mut tick_event_t,
        count_out: *mut u64,
        header_out: *mut agtick_header_t,
    ) -> c_int;

    pub fn agtick_free_ticks(ticks: *mut tick_event_t);

    pub fn agtick_mmap_open(path: *const c_char) -> *mut agtick_mmap_handle_t;

    pub fn agtick_mmap_header(handle: *mut agtick_mmap_handle_t) -> *const agtick_header_t;

    pub fn agtick_mmap_next(
        handle: *mut agtick_mmap_handle_t,
        tick_out: *mut tick_event_t,
    ) -> c_int;

    pub fn agtick_mmap_reset(handle: *mut agtick_mmap_handle_t);

    pub fn agtick_mmap_decode_all(
        handle: *mut agtick_mmap_handle_t,
        ticks_out: *mut tick_event_t,
        max_count: u64,
    ) -> i64;

    pub fn agtick_mmap_close(handle: *mut agtick_mmap_handle_t);

    pub fn agtick_strerror(err: c_int) -> *const c_char;

    // Varint utilities
    pub fn agtick_encode_varint(value: u64, buf: *mut u8) -> c_int;
    pub fn agtick_decode_varint(buf: *const u8, buf_len: usize, value_out: *mut u64) -> c_int;
    pub fn agtick_encode_svarint(value: i64, buf: *mut u8) -> c_int;
    pub fn agtick_decode_svarint(buf: *const u8, buf_len: usize, value_out: *mut i64) -> c_int;
}

// ========== Safe Rust Wrappers ==========

/// Error type for agtick operations
#[derive(Debug, Clone)]
pub struct AgTickError {
    pub code: c_int,
    pub message: String,
}

impl std::fmt::Display for AgTickError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "AgTickError({}): {}", self.code, self.message)
    }
}

impl std::error::Error for AgTickError {}

impl From<c_int> for AgTickError {
    fn from(code: c_int) -> Self {
        let message = unsafe {
            let ptr = agtick_strerror(code);
            if ptr.is_null() {
                "Unknown error".to_string()
            } else {
                CStr::from_ptr(ptr).to_string_lossy().to_string()
            }
        };
        Self { code, message }
    }
}

pub type AgTickResult<T> = Result<T, AgTickError>;

/// Writer for agtick files
pub struct AgTickWriter;

impl AgTickWriter {
    /// Write ticks to an agtick file
    pub fn write<P: AsRef<Path>>(
        path: P,
        ticks: &[tick_event_t],
        symbol: &str,
        tick_size: f64,
    ) -> AgTickResult<()> {
        let path_cstr =
            CString::new(path.as_ref().to_string_lossy().as_bytes()).map_err(|_| AgTickError {
                code: AGTICK_ERR_PARAM,
                message: "Invalid path".to_string(),
            })?;

        let symbol_cstr = CString::new(symbol).map_err(|_| AgTickError {
            code: AGTICK_ERR_PARAM,
            message: "Invalid symbol".to_string(),
        })?;

        let result = unsafe {
            agtick_write(
                path_cstr.as_ptr(),
                ticks.as_ptr(),
                ticks.len() as u64,
                symbol_cstr.as_ptr(),
                tick_size,
            )
        };

        if result == AGTICK_OK {
            Ok(())
        } else {
            Err(AgTickError::from(result))
        }
    }
}

/// Reader for agtick files (allocating)
pub struct AgTickReader;

impl AgTickReader {
    /// Read all ticks from an agtick file
    ///
    /// Returns the tick array and header information.
    /// The tick array is automatically freed when dropped.
    pub fn read<P: AsRef<Path>>(path: P) -> AgTickResult<(AgTickVec, agtick_header_t)> {
        let path_cstr =
            CString::new(path.as_ref().to_string_lossy().as_bytes()).map_err(|_| AgTickError {
                code: AGTICK_ERR_PARAM,
                message: "Invalid path".to_string(),
            })?;

        let mut ticks_ptr: *mut tick_event_t = ptr::null_mut();
        let mut count: u64 = 0;
        let mut header = agtick_header_t::default();

        let result = unsafe {
            agtick_read(
                path_cstr.as_ptr(),
                &mut ticks_ptr,
                &mut count,
                &mut header,
            )
        };

        if result == AGTICK_OK {
            Ok((
                AgTickVec {
                    ptr: ticks_ptr,
                    len: count as usize,
                },
                header,
            ))
        } else {
            Err(AgTickError::from(result))
        }
    }
}

/// Owned vector of ticks from C allocation
///
/// Automatically frees the underlying memory when dropped.
pub struct AgTickVec {
    ptr: *mut tick_event_t,
    len: usize,
}

impl AgTickVec {
    /// Get the number of ticks
    pub fn len(&self) -> usize {
        self.len
    }

    /// Check if empty
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    /// Get a slice of the ticks
    pub fn as_slice(&self) -> &[tick_event_t] {
        if self.ptr.is_null() || self.len == 0 {
            &[]
        } else {
            unsafe { std::slice::from_raw_parts(self.ptr, self.len) }
        }
    }

    /// Get a mutable slice of the ticks
    pub fn as_mut_slice(&mut self) -> &mut [tick_event_t] {
        if self.ptr.is_null() || self.len == 0 {
            &mut []
        } else {
            unsafe { std::slice::from_raw_parts_mut(self.ptr, self.len) }
        }
    }
}

impl Drop for AgTickVec {
    fn drop(&mut self) {
        if !self.ptr.is_null() {
            unsafe {
                agtick_free_ticks(self.ptr);
            }
        }
    }
}

impl std::ops::Deref for AgTickVec {
    type Target = [tick_event_t];

    fn deref(&self) -> &Self::Target {
        self.as_slice()
    }
}

impl std::ops::DerefMut for AgTickVec {
    fn deref_mut(&mut self) -> &mut Self::Target {
        self.as_mut_slice()
    }
}

// Safety: AgTickVec owns its data and can be sent across threads
unsafe impl Send for AgTickVec {}

/// Memory-mapped agtick file reader
///
/// Provides zero-copy access to tick data through memory mapping.
pub struct AgTickMmap {
    handle: *mut agtick_mmap_handle_t,
}

impl AgTickMmap {
    /// Open an agtick file for memory-mapped reading
    pub fn open<P: AsRef<Path>>(path: P) -> AgTickResult<Self> {
        let path_cstr =
            CString::new(path.as_ref().to_string_lossy().as_bytes()).map_err(|_| AgTickError {
                code: AGTICK_ERR_PARAM,
                message: "Invalid path".to_string(),
            })?;

        let handle = unsafe { agtick_mmap_open(path_cstr.as_ptr()) };

        if handle.is_null() {
            Err(AgTickError {
                code: AGTICK_ERR_MMAP,
                message: "Failed to memory-map file".to_string(),
            })
        } else {
            Ok(Self { handle })
        }
    }

    /// Get the file header
    pub fn header(&self) -> Option<&agtick_header_t> {
        let ptr = unsafe { agtick_mmap_header(self.handle) };
        if ptr.is_null() {
            None
        } else {
            Some(unsafe { &*ptr })
        }
    }

    /// Get the number of ticks in the file
    pub fn tick_count(&self) -> u64 {
        self.header().map(|h| h.tick_count).unwrap_or(0)
    }

    /// Reset the iterator to the beginning
    pub fn reset(&mut self) {
        unsafe {
            agtick_mmap_reset(self.handle);
        }
    }

    /// Read the next tick
    ///
    /// Returns None when all ticks have been read.
    pub fn next_tick(&mut self) -> Option<tick_event_t> {
        let mut tick = tick_event_t {
            ts_ms: 0,
            price_tick: 0,
            qty: 0,
            side: side_t::SIDE_BUY,
        };

        let result = unsafe { agtick_mmap_next(self.handle, &mut tick) };

        if result > 0 {
            Some(tick)
        } else {
            None
        }
    }

    /// Decode all ticks into a pre-allocated buffer
    ///
    /// Returns the number of ticks decoded.
    pub fn decode_all(&mut self, buffer: &mut [tick_event_t]) -> AgTickResult<usize> {
        let result =
            unsafe { agtick_mmap_decode_all(self.handle, buffer.as_mut_ptr(), buffer.len() as u64) };

        if result >= 0 {
            Ok(result as usize)
        } else {
            Err(AgTickError::from(result as c_int))
        }
    }

    /// Decode all ticks into a new Vec
    pub fn decode_all_vec(&mut self) -> AgTickResult<Vec<tick_event_t>> {
        let count = self.tick_count() as usize;
        let mut buffer = vec![
            tick_event_t {
                ts_ms: 0,
                price_tick: 0,
                qty: 0,
                side: side_t::SIDE_BUY,
            };
            count
        ];

        let decoded = self.decode_all(&mut buffer)?;
        buffer.truncate(decoded);
        Ok(buffer)
    }

    /// Create an iterator over ticks
    pub fn iter(&mut self) -> AgTickMmapIter<'_> {
        self.reset();
        AgTickMmapIter { mmap: self }
    }
}

impl Drop for AgTickMmap {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe {
                agtick_mmap_close(self.handle);
            }
        }
    }
}

// Safety: AgTickMmap owns its handle and can be sent across threads
unsafe impl Send for AgTickMmap {}

/// Iterator over memory-mapped ticks
pub struct AgTickMmapIter<'a> {
    mmap: &'a mut AgTickMmap,
}

impl<'a> Iterator for AgTickMmapIter<'a> {
    type Item = tick_event_t;

    fn next(&mut self) -> Option<Self::Item> {
        self.mmap.next_tick()
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let count = self.mmap.tick_count() as usize;
        (0, Some(count))
    }
}

// ========== Varint Utilities ==========

/// Encode an unsigned integer as a varint
pub fn encode_varint(value: u64) -> Vec<u8> {
    let mut buf = [0u8; 10];
    let len = unsafe { agtick_encode_varint(value, buf.as_mut_ptr()) };
    buf[..len as usize].to_vec()
}

/// Decode a varint from bytes
pub fn decode_varint(bytes: &[u8]) -> Option<(u64, usize)> {
    let mut value: u64 = 0;
    let len = unsafe { agtick_decode_varint(bytes.as_ptr(), bytes.len(), &mut value) };
    if len > 0 {
        Some((value, len as usize))
    } else {
        None
    }
}

/// Encode a signed integer as a zigzag varint
pub fn encode_svarint(value: i64) -> Vec<u8> {
    let mut buf = [0u8; 10];
    let len = unsafe { agtick_encode_svarint(value, buf.as_mut_ptr()) };
    buf[..len as usize].to_vec()
}

/// Decode a zigzag varint from bytes
pub fn decode_svarint(bytes: &[u8]) -> Option<(i64, usize)> {
    let mut value: i64 = 0;
    let len = unsafe { agtick_decode_svarint(bytes.as_ptr(), bytes.len(), &mut value) };
    if len > 0 {
        Some((value, len as usize))
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_header_size() {
        assert_eq!(std::mem::size_of::<agtick_header_t>(), AGTICK_HEADER_SIZE);
    }

    #[test]
    fn test_varint_roundtrip() {
        let values: &[u64] = &[0, 1, 127, 128, 255, 256, 16383, 16384, u64::MAX];

        for &v in values {
            let encoded = encode_varint(v);
            let (decoded, _) = decode_varint(&encoded).unwrap();
            assert_eq!(v, decoded, "Varint roundtrip failed for {}", v);
        }
    }

    #[test]
    fn test_svarint_roundtrip() {
        let values: &[i64] = &[0, 1, -1, 63, -64, 64, -65, i64::MAX, i64::MIN];

        for &v in values {
            let encoded = encode_svarint(v);
            let (decoded, _) = decode_svarint(&encoded).unwrap();
            assert_eq!(v, decoded, "Signed varint roundtrip failed for {}", v);
        }
    }

    #[test]
    fn test_header_symbol_str() {
        let mut header = agtick_header_t::default();
        let symbol = b"BTCUSDT";
        for (i, &b) in symbol.iter().enumerate() {
            header.symbol[i] = b as c_char;
        }

        assert_eq!(header.symbol_str(), "BTCUSDT");
    }
}
