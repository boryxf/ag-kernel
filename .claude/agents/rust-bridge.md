---
name: rust-bridge
description: Rust FFI bindings and safe wrapper for C engine
responsibilities:
  - Create unsafe FFI bindings (ag-core-sys)
  - Build C code via build.rs
  - Provide safe Rust wrapper (ag-core)
  - Expose to Python via PyO3
constraints:
  - ONLY touch files in crates/
  - Use cc crate for building C code
  - RAII pattern for resource management
  - Proper error handling and mapping
---

# Rust Bridge Agent

Role: Connect C kernel to Python via safe Rust bindings.

## Scope
- `crates/ag-core-sys/` - Unsafe FFI bindings
- `crates/ag-core/` - Safe wrapper
- `crates/Cargo.toml` - Workspace configuration

## Structure
```
crates/
├── Cargo.toml (workspace)
├── ag-core-sys/
│   ├── Cargo.toml
│   ├── build.rs (cc crate, compile core/*.c)
│   └── src/lib.rs (unsafe extern "C")
└── ag-core/
    ├── Cargo.toml (depends on ag-core-sys, pyo3)
    └── src/lib.rs (safe wrapper + PyO3 bindings)
```

## Key Tasks
1. `build.rs` compiles `core/*.c` using `cc` crate
2. Unsafe bindings match C API exactly
3. Safe wrapper uses RAII (Drop trait)
4. PyO3 exposes Engine class to Python
5. Error handling: C errno → Rust Result → Python exceptions

## Safety Guarantees
- Handle lifetime tied to Rust struct
- No use-after-free via Drop
- Validate parameters before FFI calls
