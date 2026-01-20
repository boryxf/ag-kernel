//! Safe Rust wrapper around the C engine with Python bindings

pub mod agtick;
pub mod candle;
pub mod candle_parser;
pub mod market_event;

use ag_core_sys::*;
use agtick::{AgTickEventIter, AgTickReader, AgTickRecord};
use numpy::PyReadonlyArray1;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::os::raw::c_int;
use std::path::Path;
use std::ptr;

// ========== Safe Rust Wrapper ==========

/// Safe wrapper around the C engine
pub struct Engine {
    handle: *mut engine_handle_t,
    tick_size: f64,
}

impl Engine {
    pub fn new(
        initial_cash: f64,
        maker_fee_bps: f64,
        taker_fee_bps: f64,
        spread_bps: f64,
        tick_size: f64,
    ) -> Result<Self, String> {
        let config = config_t {
            maker_fee_bps,
            taker_fee_bps,
            spread_bps,
            initial_cash,
            tick_size,
        };

        let handle = unsafe { engine_new(&config) };

        if handle.is_null() {
            return Err("Failed to create engine".to_string());
        }

        Ok(Engine { handle, tick_size })
    }

    pub fn reset(&mut self) {
        unsafe { engine_reset(self.handle) }
    }

    pub fn step_tick(&mut self, ts_ms: i64, price_tick_i64: i64, qty: f64, side: &str) -> Result<(), String> {
        let side_enum = match side.to_uppercase().as_str() {
            "BUY" => side_t::SIDE_BUY,
            "SELL" => side_t::SIDE_SELL,
            _ => return Err(format!("Invalid side: {}", side)),
        };

        let tick = tick_event_t {
            ts_ms,
            price_tick: price_tick_i64,
            qty: (qty * 1000000.0) as i64, // Convert to integer representation
            side: side_enum,
        };

        let result = unsafe { engine_step_tick(self.handle, &tick) };

        if result < 0 {
            return Err(format!("Engine step failed with code: {}", result));
        }

        Ok(())
    }

    /// Optimized step_tick that accepts u8 side (0=BUY, 1=SELL) to avoid string parsing overhead
    #[inline]
    pub fn step_tick_fast(&mut self, ts_ms: i64, price_tick: i64, qty: f64, side: u8) -> Result<(), String> {
        let side_enum = if side == 0 {
            side_t::SIDE_BUY
        } else {
            side_t::SIDE_SELL
        };

        let tick = tick_event_t {
            ts_ms,
            price_tick,
            qty: (qty * 1000000.0) as i64,
            side: side_enum,
        };

        let result = unsafe { engine_step_tick(self.handle, &tick) };

        if result < 0 {
            return Err(format!("Engine step failed with code: {}", result));
        }

        Ok(())
    }

    /// Process a batch of ticks efficiently - accepts integer sides (0=BUY, 1=SELL)
    /// Uses single FFI call to C engine_step_batch for optimal performance
    pub fn process_tick_batch(
        &mut self,
        timestamps: Vec<i64>,
        price_ticks: Vec<i64>,
        qtys: Vec<f64>,
        sides: Vec<u8>,
    ) -> Result<(), String> {
        // Validate all vectors have same length
        let n = timestamps.len();
        if price_ticks.len() != n || qtys.len() != n || sides.len() != n {
            return Err(format!(
                "Vector length mismatch: timestamps={}, price_ticks={}, qtys={}, sides={}",
                n, price_ticks.len(), qtys.len(), sides.len()
            ));
        }

        if n == 0 {
            return Ok(());
        }

        // Pre-convert all data to tick_event_t array for single FFI call
        let mut ticks: Vec<tick_event_t> = Vec::with_capacity(n);
        for i in 0..n {
            let side_enum = if sides[i] == 0 {
                side_t::SIDE_BUY
            } else {
                side_t::SIDE_SELL
            };

            ticks.push(tick_event_t {
                ts_ms: timestamps[i],
                price_tick: price_ticks[i],
                qty: (qtys[i] * 1000000.0) as i64,
                side: side_enum,
            });
        }

        // Single FFI call for entire batch
        let result = unsafe { engine_step_batch(self.handle, ticks.as_ptr(), n as c_int) };

        if result < 0 {
            return Err(format!("Engine batch step failed with code: {}", result));
        }

        Ok(())
    }

    /// Process a batch of ticks from raw slices - zero-copy from numpy arrays
    /// This is the most efficient path for numpy data
    pub fn process_tick_batch_raw(
        &mut self,
        timestamps: &[i64],
        price_ticks: &[i64],
        qtys: &[f64],
        sides: &[u8],
    ) -> Result<(), String> {
        let n = timestamps.len();
        if price_ticks.len() != n || qtys.len() != n || sides.len() != n {
            return Err(format!(
                "Slice length mismatch: timestamps={}, price_ticks={}, qtys={}, sides={}",
                n, price_ticks.len(), qtys.len(), sides.len()
            ));
        }

        if n == 0 {
            return Ok(());
        }

        // Pre-convert all data to tick_event_t array
        let mut ticks: Vec<tick_event_t> = Vec::with_capacity(n);
        for i in 0..n {
            let side_enum = if sides[i] == 0 {
                side_t::SIDE_BUY
            } else {
                side_t::SIDE_SELL
            };

            ticks.push(tick_event_t {
                ts_ms: timestamps[i],
                price_tick: price_ticks[i],
                qty: (qtys[i] * 1000000.0) as i64,
                side: side_enum,
            });
        }

        // Single FFI call for entire batch
        let result = unsafe { engine_step_batch(self.handle, ticks.as_ptr(), n as c_int) };

        if result < 0 {
            return Err(format!("Engine batch step failed with code: {}", result));
        }

        Ok(())
    }

    pub fn place_order(
        &mut self,
        order_type: &str,
        side: &str,
        qty: f64,
        price: f64,
    ) -> Result<(), String> {
        let type_enum = match order_type.to_uppercase().as_str() {
            "MARKET" => order_type_t::ORDER_TYPE_MARKET,
            "LIMIT" => order_type_t::ORDER_TYPE_LIMIT,
            _ => return Err(format!("Invalid order type: {}", order_type)),
        };

        let side_enum = match side.to_uppercase().as_str() {
            "BUY" => side_t::SIDE_BUY,
            "SELL" => side_t::SIDE_SELL,
            _ => return Err(format!("Invalid side: {}", side)),
        };

        let price_tick = (price / self.tick_size).round() as i64;
        let qty_i64 = (qty * 1000000.0) as i64;

        let order = order_t {
            order_id: 0, // Auto-assigned
            type_: type_enum,
            side: side_enum,
            qty: qty_i64,
            price_tick,
        };

        let result = unsafe { engine_place_order(self.handle, &order) };

        if result < 0 {
            return Err(format!("Place order failed with code: {}", result));
        }

        Ok(())
    }

    pub fn get_snapshot(&self) -> Snapshot {
        let snap = unsafe { engine_get_snapshot(self.handle) };

        Snapshot {
            ts_ms: snap.ts_ms,
            cash: snap.cash,
            position: snap.position as f64 / 1000000.0, // Convert back from integer
            avg_entry_price: snap.avg_entry_price,
            realized_pnl: snap.realized_pnl,
            unrealized_pnl: snap.unrealized_pnl,
            equity: snap.equity,
        }
    }

    /// Load and process all ticks from an agtick file
    ///
    /// This loads the entire file into memory and processes all ticks.
    /// For large files, use `load_agtick_streaming` instead.
    pub fn load_agtick<P: AsRef<Path>>(&mut self, path: P) -> Result<u64, String> {
        let mut reader = AgTickReader::open(path)
            .map_err(|e| format!("Failed to open agtick file: {}", e))?;

        let records = reader.load_all()
            .map_err(|e| format!("Failed to load agtick records: {}", e))?;

        let count = records.len();

        // Convert to tick_event_t array for batch processing
        let ticks: Vec<tick_event_t> = records.iter().map(|r| r.to_tick_event()).collect();

        // Process all ticks in a single FFI call
        let result = unsafe { engine_step_batch(self.handle, ticks.as_ptr(), count as c_int) };

        if result < 0 {
            return Err(format!("Engine batch step failed with code: {}", result));
        }

        Ok(count as u64)
    }

    /// Stream and process ticks from an agtick file with configurable batch size
    ///
    /// This processes ticks in batches to minimize memory usage while maintaining
    /// good performance through batched FFI calls.
    pub fn load_agtick_streaming<P: AsRef<Path>>(
        &mut self,
        path: P,
        batch_size: usize,
    ) -> Result<u64, String> {
        let mut reader = AgTickReader::open(path)
            .map_err(|e| format!("Failed to open agtick file: {}", e))?;

        let mut total_processed: u64 = 0;
        let mut buffer: Vec<AgTickRecord> = Vec::with_capacity(batch_size);

        loop {
            let count = reader.read_batch(&mut buffer, batch_size)
                .map_err(|e| format!("Failed to read batch: {}", e))?;

            if count == 0 {
                break;
            }

            // Convert batch to tick_event_t array
            let ticks: Vec<tick_event_t> = buffer.iter().map(|r| r.to_tick_event()).collect();

            // Process batch
            let result = unsafe { engine_step_batch(self.handle, ticks.as_ptr(), count as c_int) };

            if result < 0 {
                return Err(format!("Engine batch step failed with code: {}", result));
            }

            total_processed += count as u64;
        }

        Ok(total_processed)
    }

    /// Create a streaming iterator for processing ticks one at a time
    ///
    /// Use this when you need fine-grained control over tick processing,
    /// such as placing orders between ticks.
    pub fn agtick_iter<P: AsRef<Path>>(path: P) -> Result<AgTickEventIter, String> {
        AgTickEventIter::open(path)
            .map_err(|e| format!("Failed to open agtick file: {}", e))
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        if !self.handle.is_null() {
            unsafe { engine_free(self.handle) };
            self.handle = ptr::null_mut();
        }
    }
}

// Ensure Engine is Send (safe to move between threads)
unsafe impl Send for Engine {}

#[derive(Debug, Clone)]
pub struct Snapshot {
    pub ts_ms: i64,
    pub cash: f64,
    pub position: f64,
    pub avg_entry_price: f64,
    pub realized_pnl: f64,
    pub unrealized_pnl: f64,
    pub equity: f64,
}

// ========== Python Bindings ==========

/// Optimized snapshot struct for Python - avoids HashMap string allocations
#[pyclass(name = "Snapshot")]
#[derive(Debug, Clone)]
pub struct PySnapshot {
    #[pyo3(get)]
    pub ts_ms: i64,
    #[pyo3(get)]
    pub cash: f64,
    #[pyo3(get)]
    pub position: f64,
    #[pyo3(get)]
    pub avg_entry_price: f64,
    #[pyo3(get)]
    pub realized_pnl: f64,
    #[pyo3(get)]
    pub unrealized_pnl: f64,
    #[pyo3(get)]
    pub equity: f64,
}

#[pymethods]
impl PySnapshot {
    fn __repr__(&self) -> String {
        format!(
            "Snapshot(cash={:.2}, position={:.6}, equity={:.2}, realized_pnl={:.2}, unrealized_pnl={:.2})",
            self.cash, self.position, self.equity, self.realized_pnl, self.unrealized_pnl
        )
    }

    /// Convert to dict for backwards compatibility
    fn to_dict(&self) -> HashMap<String, f64> {
        let mut result = HashMap::new();
        result.insert("cash".to_string(), self.cash);
        result.insert("position".to_string(), self.position);
        result.insert("avg_entry_price".to_string(), self.avg_entry_price);
        result.insert("realized_pnl".to_string(), self.realized_pnl);
        result.insert("unrealized_pnl".to_string(), self.unrealized_pnl);
        result.insert("equity".to_string(), self.equity);
        result
    }
}

#[pyclass(name = "Engine")]
struct PyEngine {
    inner: Engine,
}

#[pymethods]
impl PyEngine {
    #[new]
    #[pyo3(signature = (initial_cash=100_000.0, maker_fee=0.0001, taker_fee=0.0002, spread_bps=2.0, tick_size=0.01))]
    fn new(
        initial_cash: f64,
        maker_fee: f64,
        taker_fee: f64,
        spread_bps: f64,
        tick_size: f64,
    ) -> PyResult<Self> {
        let maker_fee_bps = maker_fee * 10000.0;
        let taker_fee_bps = taker_fee * 10000.0;

        let engine = Engine::new(
            initial_cash,
            maker_fee_bps,
            taker_fee_bps,
            spread_bps,
            tick_size,
        )
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))?;

        Ok(PyEngine { inner: engine })
    }

    fn reset(&mut self) {
        self.inner.reset();
    }

    fn step_tick(&mut self, ts_ms: i64, price_tick_i64: i64, qty: f64, side: &str) -> PyResult<()> {
        self.inner
            .step_tick(ts_ms, price_tick_i64, qty, side)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    fn step_batch(
        &mut self,
        timestamps: Vec<i64>,
        price_ticks: Vec<i64>,
        qtys: Vec<f64>,
        sides: Vec<u8>,
    ) -> PyResult<()> {
        self.inner
            .process_tick_batch(timestamps, price_ticks, qtys, sides)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    fn place_order(&mut self, order_type: &str, side: &str, qty: f64, price: f64) -> PyResult<()> {
        self.inner
            .place_order(order_type, side, qty, price)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Get snapshot as dict (backwards compatible)
    fn get_snapshot(&self) -> PyResult<HashMap<String, f64>> {
        let snap = self.inner.get_snapshot();

        let mut result = HashMap::new();
        result.insert("cash".to_string(), snap.cash);
        result.insert("position".to_string(), snap.position);
        result.insert("avg_entry_price".to_string(), snap.avg_entry_price);
        result.insert("realized_pnl".to_string(), snap.realized_pnl);
        result.insert("unrealized_pnl".to_string(), snap.unrealized_pnl);
        result.insert("equity".to_string(), snap.equity);

        Ok(result)
    }

    /// Optimized snapshot retrieval - returns PySnapshot struct instead of HashMap
    /// Avoids 6 string allocations per call
    fn get_snapshot_fast(&self) -> PySnapshot {
        let snap = self.inner.get_snapshot();
        PySnapshot {
            ts_ms: snap.ts_ms,
            cash: snap.cash,
            position: snap.position,
            avg_entry_price: snap.avg_entry_price,
            realized_pnl: snap.realized_pnl,
            unrealized_pnl: snap.unrealized_pnl,
            equity: snap.equity,
        }
    }

    /// Optimized step_tick that accepts u8 side (0=BUY, 1=SELL)
    /// Avoids string parsing overhead
    fn step_tick_fast(&mut self, ts_ms: i64, price_tick: i64, qty: f64, side: u8) -> PyResult<()> {
        self.inner
            .step_tick_fast(ts_ms, price_tick, qty, side)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Zero-copy batch processing from numpy arrays
    /// Most efficient path for processing tick data from Python
    fn step_batch_numpy<'py>(
        &mut self,
        timestamps: PyReadonlyArray1<'py, i64>,
        price_ticks: PyReadonlyArray1<'py, i64>,
        qtys: PyReadonlyArray1<'py, f64>,
        sides: PyReadonlyArray1<'py, u8>,
    ) -> PyResult<()> {
        let ts_slice = timestamps.as_slice()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("timestamps must be contiguous: {}", e)))?;
        let price_slice = price_ticks.as_slice()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("price_ticks must be contiguous: {}", e)))?;
        let qty_slice = qtys.as_slice()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("qtys must be contiguous: {}", e)))?;
        let side_slice = sides.as_slice()
            .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("sides must be contiguous: {}", e)))?;

        self.inner
            .process_tick_batch_raw(ts_slice, price_slice, qty_slice, side_slice)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Load and process all ticks from an agtick binary file
    ///
    /// This loads the entire file and processes all ticks in one batch.
    /// Returns the number of ticks processed.
    ///
    /// Args:
    ///     path: Path to the .agtick file
    ///
    /// Returns:
    ///     Number of ticks processed
    fn load_agtick(&mut self, path: &str) -> PyResult<u64> {
        self.inner
            .load_agtick(path)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }

    /// Load and process ticks from an agtick file in streaming mode
    ///
    /// This processes ticks in batches to minimize memory usage.
    /// Use this for very large files that don't fit in memory.
    ///
    /// Args:
    ///     path: Path to the .agtick file
    ///     batch_size: Number of ticks to process per batch (default: 10000)
    ///
    /// Returns:
    ///     Number of ticks processed
    #[pyo3(signature = (path, batch_size=10000))]
    fn load_agtick_streaming(&mut self, path: &str, batch_size: usize) -> PyResult<u64> {
        self.inner
            .load_agtick_streaming(path, batch_size)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e))
    }
}

/// Convert a CSV file to agtick binary format
///
/// The CSV file should have columns for timestamp, price, quantity, and side.
/// Column names are matched flexibly (e.g., "ts", "timestamp", "time" all work).
///
/// Args:
///     csv_path: Path to the input CSV file
///     agtick_path: Path for the output .agtick file
///     tick_size: Tick size for price quantization (e.g., 0.01 for 1 cent)
///
/// Returns:
///     Number of records written
///
/// Raises:
///     RuntimeError: If conversion fails
#[pyfunction]
#[pyo3(signature = (csv_path, agtick_path, tick_size=0.01))]
fn convert_csv_to_agtick(csv_path: &str, agtick_path: &str, tick_size: f64) -> PyResult<u64> {
    agtick::convert_csv_to_agtick(csv_path, agtick_path, tick_size)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Conversion failed: {}", e)))
}

/// Get information about an agtick file
///
/// Args:
///     path: Path to the .agtick file
///
/// Returns:
///     Dict with tick_size, record_count, and file_size_bytes
#[pyfunction]
fn agtick_info(path: &str) -> PyResult<HashMap<String, f64>> {
    let reader = AgTickReader::open(path)
        .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to open file: {}", e)))?;

    let file_size = std::fs::metadata(path)
        .map(|m| m.len())
        .unwrap_or(0);

    let mut info = HashMap::new();
    info.insert("tick_size".to_string(), reader.tick_size());
    info.insert("record_count".to_string(), reader.record_count() as f64);
    info.insert("file_size_bytes".to_string(), file_size as f64);

    Ok(info)
}

/// Python iterator for streaming agtick records
#[pyclass(name = "AgTickIterator")]
struct PyAgTickIterator {
    iter: AgTickEventIter,
}

#[pymethods]
impl PyAgTickIterator {
    #[new]
    fn new(path: &str) -> PyResult<Self> {
        let iter = AgTickEventIter::open(path)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Failed to open file: {}", e)))?;
        Ok(Self { iter })
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(&mut self) -> Option<PyResult<(i64, i64, i64, u8)>> {
        match self.iter.next() {
            Some(Ok(tick)) => {
                let side = if tick.side == side_t::SIDE_BUY { 0u8 } else { 1u8 };
                Some(Ok((tick.ts_ms, tick.price_tick, tick.qty, side)))
            }
            Some(Err(e)) => Some(Err(pyo3::exceptions::PyRuntimeError::new_err(format!("{}", e)))),
            None => None,
        }
    }

    fn __len__(&self) -> usize {
        self.iter.total_count() as usize
    }

    /// Get the tick size from the file header
    fn tick_size(&self) -> f64 {
        self.iter.tick_size()
    }

    /// Get the total number of records
    fn total_count(&self) -> u64 {
        self.iter.total_count()
    }

    /// Get current position (0-indexed)
    fn current_index(&self) -> u64 {
        self.iter.current_index()
    }

    /// Reset to beginning of file
    fn reset(&mut self) -> PyResult<()> {
        self.iter.reset()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{}", e)))
    }
}

#[pymodule]
fn _ag_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEngine>()?;
    m.add_class::<PySnapshot>()?;
    m.add_class::<PyAgTickIterator>()?;
    m.add_function(wrap_pyfunction!(convert_csv_to_agtick, m)?)?;
    m.add_function(wrap_pyfunction!(agtick_info, m)?)?;
    Ok(())
}
