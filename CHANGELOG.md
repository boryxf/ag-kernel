# Changelog

All notable changes to ag-kernel will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-01-02

### Fixed
- **CRITICAL**: Fixed quantity scaling bug in C engine where quantities scaled by 1,000,000 from Rust were used without descaling in financial calculations
  - Fixed `calculate_unrealized_pnl()` to descale position before calculations
  - Fixed `execute_fill()` notional calculation to descale quantity
  - Fixed `execute_fill()` PnL realization to descale qty_reducing
  - Result: All financial calculations now produce correct values (were off by 1,000,000x factor)
- **MEDIUM**: Fixed fee double-counting bug where fees were subtracted from both cash AND realized_pnl
  - Fees now only deducted from cash
  - Realized PnL now shows gross profit/loss (fees tracked separately in cash)
- Fixed Python module import issue (_ag_core not loading correctly)
- Fixed `abs()` to `llabs()` for int64_t to eliminate compiler warnings

### Added
- Comprehensive test suite with 26 tests:
  - Unit tests for quantity scaling (9 tests)
  - Unit tests for batch processing (6 tests)
  - Unit tests for fee accounting (5 tests)
  - Integration tests for end-to-end scaling (6 tests)
- `pytest.ini` configuration for test management
- `CRITICAL_AUDIT_REPORT.md` documenting full security and correctness audit
- Documentation comments in engine.c explaining scaling convention

### Changed
- Improved `.gitignore` to exclude all build artifacts
- Test assertions updated to reflect fee accounting fix
- Enhanced error messages in Rust wrapper

### Security
- Conducted full project audit for scaling bugs and security issues
- All critical issues resolved
- Medium-priority issues documented for future improvement

## [0.2.0] - 2025-01-01

### Added
- Batch processing with zero-copy OHLC ingestion
- Streaming Parquet parser for efficient data loading
- Performance benchmarks showing 10M+ ticks/sec throughput

### Changed
- Major architecture refactor for performance
- Binary Parquet format support

## [0.1.0] - Initial Release

### Added
- C kernel for deterministic execution
- Rust FFI bindings with PyO3
- Python API
- Market and limit order support
- Position and PnL tracking
- Configurable fees and spread
