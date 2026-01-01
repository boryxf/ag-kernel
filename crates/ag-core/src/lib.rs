//! Safe Rust wrapper around the C engine with Python bindings

pub mod candle;
pub mod candle_parser;
pub mod market_event;

use ag_core_sys::*;
use pyo3::prelude::*;
use std::collections::HashMap;
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

    /// Process a batch of ticks efficiently - accepts integer sides (0=BUY, 1=SELL)
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

        // Process all ticks in the batch
        for i in 0..n {
            let side_enum = match sides[i] {
                0 => side_t::SIDE_BUY,
                1 => side_t::SIDE_SELL,
                _ => return Err(format!("Invalid side value: {} (must be 0 or 1)", sides[i])),
            };

            let tick = tick_event_t {
                ts_ms: timestamps[i],
                price_tick: price_ticks[i],
                qty: (qtys[i] * 1000000.0) as i64, // Convert to integer representation
                side: side_enum,
            };

            let result = unsafe { engine_step_tick(self.handle, &tick) };

            if result < 0 {
                return Err(format!("Engine step failed at tick {} with code: {}", i, result));
            }
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
}

#[pymodule]
fn _ag_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyEngine>()?;
    Ok(())
}
