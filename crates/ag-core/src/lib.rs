//! Safe Rust wrapper around the C engine with Python bindings

pub mod agtick;
pub mod candle;
pub mod candle_parser;
pub mod market_event;

use ag_core_sys::*;
use agtick::{AgTickEventIter, AgTickReader, AgTickRecord};
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::prelude::*;
use pyo3::types::PyDict;
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

// ========== Candle Aggregation Functions ==========

/// Aggregate tick data into OHLCV candles at specified interval.
///
/// Args:
///     timestamps: Array of tick timestamps (ms)
///     price_ticks: Array of prices in ticks
///     qtys: Array of quantities
///     sides: Array of sides (0=buy, 1=sell)
///     interval_ms: Candle interval in milliseconds
///
/// Returns:
///     Dict with arrays: ts_ms, open, high, low, close, volume, buy_volume, sell_volume, trade_count
#[pyfunction]
fn aggregate_candles<'py>(
    py: Python<'py>,
    timestamps: PyReadonlyArray1<'py, i64>,
    price_ticks: PyReadonlyArray1<'py, i64>,
    qtys: PyReadonlyArray1<'py, f64>,
    sides: PyReadonlyArray1<'py, u8>,
    interval_ms: i64,
) -> PyResult<PyObject> {
    let ts_slice = timestamps.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("timestamps must be contiguous: {}", e)))?;
    let price_slice = price_ticks.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("price_ticks must be contiguous: {}", e)))?;
    let qty_slice = qtys.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("qtys must be contiguous: {}", e)))?;
    let side_slice = sides.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("sides must be contiguous: {}", e)))?;

    let count = ts_slice.len();
    if price_slice.len() != count || qty_slice.len() != count || side_slice.len() != count {
        return Err(pyo3::exceptions::PyValueError::new_err("All arrays must have the same length"));
    }

    if count == 0 {
        let dict = PyDict::new_bound(py);
        let empty_i64: Vec<i64> = Vec::new();
        let empty_f64: Vec<f64> = Vec::new();
        let empty_u64: Vec<u64> = Vec::new();
        dict.set_item("ts_ms", empty_i64.clone().into_pyarray_bound(py))?;
        dict.set_item("open", empty_i64.clone().into_pyarray_bound(py))?;
        dict.set_item("high", empty_i64.clone().into_pyarray_bound(py))?;
        dict.set_item("low", empty_i64.clone().into_pyarray_bound(py))?;
        dict.set_item("close", empty_i64.into_pyarray_bound(py))?;
        dict.set_item("volume", empty_f64.clone().into_pyarray_bound(py))?;
        dict.set_item("buy_volume", empty_f64.clone().into_pyarray_bound(py))?;
        dict.set_item("sell_volume", empty_f64.into_pyarray_bound(py))?;
        dict.set_item("trade_count", empty_u64.into_pyarray_bound(py))?;
        return Ok(dict.into());
    }

    // Estimate max candles
    let time_span = ts_slice[count - 1] - ts_slice[0];
    let max_candles = ((time_span / interval_ms) + 2) as usize;
    let max_candles = max_candles.max(count); // At least as many as ticks

    let mut candles_out: Vec<candle_t> = vec![
        candle_t {
            ts_ms: 0, open_tick: 0, high_tick: 0, low_tick: 0, close_tick: 0,
            volume: 0.0, buy_volume: 0.0, sell_volume: 0.0, trade_count: 0
        };
        max_candles
    ];

    let result = unsafe {
        candles_aggregate(
            ts_slice.as_ptr(),
            price_slice.as_ptr(),
            qty_slice.as_ptr(),
            side_slice.as_ptr(),
            count,
            interval_ms,
            candles_out.as_mut_ptr(),
            max_candles,
        )
    };

    if result < 0 {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            format!("Candle aggregation failed with code: {}", result)
        ));
    }

    let num_candles = result as usize;
    candles_out.truncate(num_candles);

    // Convert to dict of arrays
    let dict = PyDict::new_bound(py);

    let ts_arr: Vec<i64> = candles_out.iter().map(|c| c.ts_ms).collect();
    let open_arr: Vec<i64> = candles_out.iter().map(|c| c.open_tick).collect();
    let high_arr: Vec<i64> = candles_out.iter().map(|c| c.high_tick).collect();
    let low_arr: Vec<i64> = candles_out.iter().map(|c| c.low_tick).collect();
    let close_arr: Vec<i64> = candles_out.iter().map(|c| c.close_tick).collect();
    let vol_arr: Vec<f64> = candles_out.iter().map(|c| c.volume).collect();
    let buy_vol_arr: Vec<f64> = candles_out.iter().map(|c| c.buy_volume).collect();
    let sell_vol_arr: Vec<f64> = candles_out.iter().map(|c| c.sell_volume).collect();
    let trade_count_arr: Vec<u64> = candles_out.iter().map(|c| c.trade_count).collect();

    dict.set_item("ts_ms", ts_arr.into_pyarray_bound(py))?;
    dict.set_item("open", open_arr.into_pyarray_bound(py))?;
    dict.set_item("high", high_arr.into_pyarray_bound(py))?;
    dict.set_item("low", low_arr.into_pyarray_bound(py))?;
    dict.set_item("close", close_arr.into_pyarray_bound(py))?;
    dict.set_item("volume", vol_arr.into_pyarray_bound(py))?;
    dict.set_item("buy_volume", buy_vol_arr.into_pyarray_bound(py))?;
    dict.set_item("sell_volume", sell_vol_arr.into_pyarray_bound(py))?;
    dict.set_item("trade_count", trade_count_arr.into_pyarray_bound(py))?;

    Ok(dict.into())
}

// ========== Volume Analysis Functions ==========

/// Calculate VWAP (Volume-Weighted Average Price) for tick data.
///
/// Args:
///     timestamps: Array of tick timestamps (ms)
///     price_ticks: Array of prices in ticks
///     qtys: Array of quantities
///     tick_size: Tick size for price conversion
///
/// Returns:
///     NumPy array of VWAP values (same length as input)
#[pyfunction]
fn calculate_vwap<'py>(
    py: Python<'py>,
    timestamps: PyReadonlyArray1<'py, i64>,
    price_ticks: PyReadonlyArray1<'py, i64>,
    qtys: PyReadonlyArray1<'py, f64>,
    tick_size: f64,
) -> PyResult<Py<PyArray1<f64>>> {
    let ts_slice = timestamps.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("timestamps must be contiguous: {}", e)))?;
    let price_slice = price_ticks.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("price_ticks must be contiguous: {}", e)))?;
    let qty_slice = qtys.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("qtys must be contiguous: {}", e)))?;

    let count = ts_slice.len();
    if price_slice.len() != count || qty_slice.len() != count {
        return Err(pyo3::exceptions::PyValueError::new_err("All arrays must have the same length"));
    }

    let mut vwap_out: Vec<f64> = vec![0.0; count];

    let result = unsafe {
        vwap_calculate(
            ts_slice.as_ptr(),
            price_slice.as_ptr(),
            qty_slice.as_ptr(),
            count,
            tick_size,
            vwap_out.as_mut_ptr(),
        )
    };

    if result < 0 {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            format!("VWAP calculation failed with code: {}", result)
        ));
    }

    Ok(vwap_out.into_pyarray_bound(py).unbind())
}

/// Build a volume profile from tick data.
///
/// Args:
///     price_ticks: Array of prices in ticks
///     qtys: Array of quantities
///     sides: Array of sides (0=buy, 1=sell)
///     tick_size: Tick size for price conversion
///     num_bins: Number of bins for the profile
///     value_area_pct: Value area percentage (default 70.0)
///
/// Returns:
///     Dict with bins array, poc_tick, vah_tick, val_tick, total_volume
#[pyfunction]
#[pyo3(signature = (price_ticks, qtys, sides, tick_size, num_bins, value_area_pct=70.0))]
fn build_volume_profile<'py>(
    py: Python<'py>,
    price_ticks: PyReadonlyArray1<'py, i64>,
    qtys: PyReadonlyArray1<'py, f64>,
    sides: PyReadonlyArray1<'py, u8>,
    tick_size: f64,
    num_bins: usize,
    value_area_pct: f64,
) -> PyResult<PyObject> {
    let price_slice = price_ticks.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("price_ticks must be contiguous: {}", e)))?;
    let qty_slice = qtys.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("qtys must be contiguous: {}", e)))?;
    let side_slice = sides.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("sides must be contiguous: {}", e)))?;

    let count = price_slice.len();
    if qty_slice.len() != count || side_slice.len() != count {
        return Err(pyo3::exceptions::PyValueError::new_err("All arrays must have the same length"));
    }

    if count == 0 {
        return Err(pyo3::exceptions::PyValueError::new_err("Cannot build volume profile from empty data"));
    }

    let mut profile = volume_profile_t {
        bins: std::ptr::null_mut(),
        num_bins: 0,
        poc_tick: 0,
        vah_tick: 0,
        val_tick: 0,
        total_volume: 0.0,
    };

    let result = unsafe {
        volume_profile_build(
            price_slice.as_ptr(),
            qty_slice.as_ptr(),
            side_slice.as_ptr(),
            count,
            tick_size,
            num_bins,
            value_area_pct,
            &mut profile,
        )
    };

    if result < 0 {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            format!("Volume profile build failed with code: {}", result)
        ));
    }

    // Convert bins to dict
    let dict = PyDict::new_bound(py);

    // Extract bin data
    let bins_data: Vec<(i64, f64, f64, f64)> = if !profile.bins.is_null() && profile.num_bins > 0 {
        let bins_slice = unsafe { std::slice::from_raw_parts(profile.bins, profile.num_bins) };
        bins_slice.iter().map(|b| (b.price_tick, b.volume, b.buy_volume, b.sell_volume)).collect()
    } else {
        Vec::new()
    };

    let price_arr: Vec<i64> = bins_data.iter().map(|b| b.0).collect();
    let vol_arr: Vec<f64> = bins_data.iter().map(|b| b.1).collect();
    let buy_arr: Vec<f64> = bins_data.iter().map(|b| b.2).collect();
    let sell_arr: Vec<f64> = bins_data.iter().map(|b| b.3).collect();

    let bins_dict = PyDict::new_bound(py);
    bins_dict.set_item("price_tick", price_arr.into_pyarray_bound(py))?;
    bins_dict.set_item("volume", vol_arr.into_pyarray_bound(py))?;
    bins_dict.set_item("buy_volume", buy_arr.into_pyarray_bound(py))?;
    bins_dict.set_item("sell_volume", sell_arr.into_pyarray_bound(py))?;

    dict.set_item("bins", bins_dict)?;
    dict.set_item("poc_tick", profile.poc_tick)?;
    dict.set_item("vah_tick", profile.vah_tick)?;
    dict.set_item("val_tick", profile.val_tick)?;
    dict.set_item("total_volume", profile.total_volume)?;

    // Free the C-allocated bins
    unsafe { volume_profile_free(&mut profile) };

    Ok(dict.into())
}

/// Calculate cumulative delta (buy volume - sell volume).
///
/// Args:
///     qtys: Array of quantities
///     sides: Array of sides (0=buy, 1=sell)
///
/// Returns:
///     NumPy array of cumulative delta values
#[pyfunction]
fn calculate_cumulative_delta<'py>(
    py: Python<'py>,
    qtys: PyReadonlyArray1<'py, f64>,
    sides: PyReadonlyArray1<'py, u8>,
) -> PyResult<Py<PyArray1<f64>>> {
    let qty_slice = qtys.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("qtys must be contiguous: {}", e)))?;
    let side_slice = sides.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("sides must be contiguous: {}", e)))?;

    let count = qty_slice.len();
    if side_slice.len() != count {
        return Err(pyo3::exceptions::PyValueError::new_err("Arrays must have the same length"));
    }

    let mut delta_out: Vec<f64> = vec![0.0; count];

    let result = unsafe {
        cumulative_delta_calculate(
            qty_slice.as_ptr(),
            side_slice.as_ptr(),
            count,
            delta_out.as_mut_ptr(),
        )
    };

    if result < 0 {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            format!("Cumulative delta calculation failed with code: {}", result)
        ));
    }

    Ok(delta_out.into_pyarray_bound(py).unbind())
}

// ========== Volatility Functions ==========

/// Calculate volatility using various methods.
///
/// Args:
///     candles: Dict with open/high/low/close arrays (in ticks)
///     method: "realized", "parkinson", "garman_klass", "rogers_satchell", "yang_zhang", or "ewma"
///     window: Rolling window size (ignored for EWMA)
///     annualize: Whether to annualize the result
///     lambda_param: Lambda for EWMA (default 0.94)
///
/// Returns:
///     NumPy array of volatility values
#[pyfunction]
#[pyo3(signature = (candles, method, window, annualize=true, lambda_param=0.94))]
fn calculate_volatility<'py>(
    py: Python<'py>,
    candles: &Bound<'py, PyDict>,
    method: &str,
    window: i32,
    annualize: bool,
    lambda_param: f64,
) -> PyResult<Py<PyArray1<f64>>> {
    // Extract arrays from candles dict
    let open_arr: PyReadonlyArray1<i64> = candles.get_item("open")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'open' key"))?
        .extract()?;
    let high_arr: PyReadonlyArray1<i64> = candles.get_item("high")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'high' key"))?
        .extract()?;
    let low_arr: PyReadonlyArray1<i64> = candles.get_item("low")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'low' key"))?
        .extract()?;
    let close_arr: PyReadonlyArray1<i64> = candles.get_item("close")?
        .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing 'close' key"))?
        .extract()?;

    let open_slice = open_arr.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("open must be contiguous: {}", e)))?;
    let high_slice = high_arr.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("high must be contiguous: {}", e)))?;
    let low_slice = low_arr.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("low must be contiguous: {}", e)))?;
    let close_slice = close_arr.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("close must be contiguous: {}", e)))?;

    let count = close_slice.len();
    if open_slice.len() != count || high_slice.len() != count || low_slice.len() != count {
        return Err(pyo3::exceptions::PyValueError::new_err("All OHLC arrays must have the same length"));
    }

    let mut vol_out: Vec<f64> = vec![0.0; count];

    let result = match method.to_lowercase().as_str() {
        "realized" => unsafe {
            volatility_realized(
                close_slice.as_ptr(),
                count,
                window,
                annualize,
                vol_out.as_mut_ptr(),
            )
        },
        "parkinson" => unsafe {
            volatility_parkinson(
                high_slice.as_ptr(),
                low_slice.as_ptr(),
                count,
                window,
                annualize,
                vol_out.as_mut_ptr(),
            )
        },
        "garman_klass" => unsafe {
            volatility_garman_klass(
                open_slice.as_ptr(),
                high_slice.as_ptr(),
                low_slice.as_ptr(),
                close_slice.as_ptr(),
                count,
                window,
                annualize,
                vol_out.as_mut_ptr(),
            )
        },
        "rogers_satchell" => unsafe {
            volatility_rogers_satchell(
                open_slice.as_ptr(),
                high_slice.as_ptr(),
                low_slice.as_ptr(),
                close_slice.as_ptr(),
                count,
                window,
                annualize,
                vol_out.as_mut_ptr(),
            )
        },
        "yang_zhang" => unsafe {
            volatility_yang_zhang(
                open_slice.as_ptr(),
                high_slice.as_ptr(),
                low_slice.as_ptr(),
                close_slice.as_ptr(),
                count,
                window,
                annualize,
                vol_out.as_mut_ptr(),
            )
        },
        "ewma" => unsafe {
            volatility_ewma(
                close_slice.as_ptr(),
                count,
                lambda_param,
                annualize,
                vol_out.as_mut_ptr(),
            )
        },
        _ => {
            return Err(pyo3::exceptions::PyValueError::new_err(
                format!("Unknown volatility method: {}. Use: realized, parkinson, garman_klass, rogers_satchell, yang_zhang, ewma", method)
            ));
        }
    };

    if result < 0 {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            format!("Volatility calculation failed with code: {}", result)
        ));
    }

    Ok(vol_out.into_pyarray_bound(py).unbind())
}

/// Calculate Average True Range (ATR).
///
/// Args:
///     high_ticks: Array of high prices in ticks
///     low_ticks: Array of low prices in ticks
///     close_ticks: Array of close prices in ticks
///     period: ATR period (typically 14)
///     tick_size: Tick size for price conversion
///
/// Returns:
///     NumPy array of ATR values (in price units)
#[pyfunction]
#[pyo3(signature = (high_ticks, low_ticks, close_ticks, period=14, tick_size=0.01))]
fn calculate_atr<'py>(
    py: Python<'py>,
    high_ticks: PyReadonlyArray1<'py, i64>,
    low_ticks: PyReadonlyArray1<'py, i64>,
    close_ticks: PyReadonlyArray1<'py, i64>,
    period: i32,
    tick_size: f64,
) -> PyResult<Py<PyArray1<f64>>> {
    let high_slice = high_ticks.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("high_ticks must be contiguous: {}", e)))?;
    let low_slice = low_ticks.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("low_ticks must be contiguous: {}", e)))?;
    let close_slice = close_ticks.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("close_ticks must be contiguous: {}", e)))?;

    let count = close_slice.len();
    if high_slice.len() != count || low_slice.len() != count {
        return Err(pyo3::exceptions::PyValueError::new_err("All arrays must have the same length"));
    }

    let mut atr_out: Vec<f64> = vec![0.0; count];

    let result = unsafe {
        atr_calculate(
            high_slice.as_ptr(),
            low_slice.as_ptr(),
            close_slice.as_ptr(),
            count,
            period,
            tick_size,
            atr_out.as_mut_ptr(),
        )
    };

    if result < 0 {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            format!("ATR calculation failed with code: {}", result)
        ));
    }

    Ok(atr_out.into_pyarray_bound(py).unbind())
}

/// Calculate On-Balance Volume (OBV).
///
/// Args:
///     price_ticks: Array of prices in ticks
///     qtys: Array of quantities
///
/// Returns:
///     NumPy array of OBV values
#[pyfunction]
fn calculate_obv<'py>(
    py: Python<'py>,
    price_ticks: PyReadonlyArray1<'py, i64>,
    qtys: PyReadonlyArray1<'py, f64>,
) -> PyResult<Py<PyArray1<f64>>> {
    let price_slice = price_ticks.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("price_ticks must be contiguous: {}", e)))?;
    let qty_slice = qtys.as_slice()
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("qtys must be contiguous: {}", e)))?;

    let count = price_slice.len();
    if qty_slice.len() != count {
        return Err(pyo3::exceptions::PyValueError::new_err("Arrays must have the same length"));
    }

    let mut obv_out: Vec<f64> = vec![0.0; count];

    let result = unsafe {
        obv_calculate(
            price_slice.as_ptr(),
            qty_slice.as_ptr(),
            count,
            obv_out.as_mut_ptr(),
        )
    };

    if result < 0 {
        return Err(pyo3::exceptions::PyRuntimeError::new_err(
            format!("OBV calculation failed with code: {}", result)
        ));
    }

    Ok(obv_out.into_pyarray_bound(py).unbind())
}

#[pymodule]
fn _ag_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEngine>()?;
    m.add_class::<PySnapshot>()?;
    m.add_class::<PyAgTickIterator>()?;
    m.add_function(wrap_pyfunction!(convert_csv_to_agtick, m)?)?;
    m.add_function(wrap_pyfunction!(agtick_info, m)?)?;

    // Candle aggregation
    m.add_function(wrap_pyfunction!(aggregate_candles, m)?)?;

    // Volume analysis
    m.add_function(wrap_pyfunction!(calculate_vwap, m)?)?;
    m.add_function(wrap_pyfunction!(build_volume_profile, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_cumulative_delta, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_obv, m)?)?;

    // Volatility
    m.add_function(wrap_pyfunction!(calculate_volatility, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_atr, m)?)?;

    Ok(())
}
