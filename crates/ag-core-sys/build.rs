// Build script to compile C engine code

use std::env;
use std::path::PathBuf;

fn main() {
    let manifest_dir = env::var("CARGO_MANIFEST_DIR").unwrap();
    let core_path = PathBuf::from(&manifest_dir)
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("core");

    // Compile C engine
    cc::Build::new()
        .file(core_path.join("engine.c"))
        .file(core_path.join("agtick.c"))
        .file(core_path.join("candles.c"))
        .file(core_path.join("volume.c"))
        .file(core_path.join("volatility.c"))
        .include(&core_path)
        .opt_level(3)
        .compile("ag_engine");

    // Tell cargo to recompile if C sources change
    println!("cargo:rerun-if-changed={}", core_path.join("engine.c").display());
    println!("cargo:rerun-if-changed={}", core_path.join("engine.h").display());
    println!("cargo:rerun-if-changed={}", core_path.join("types.h").display());
    println!("cargo:rerun-if-changed={}", core_path.join("agtick.c").display());
    println!("cargo:rerun-if-changed={}", core_path.join("agtick.h").display());
    println!("cargo:rerun-if-changed={}", core_path.join("candles.c").display());
    println!("cargo:rerun-if-changed={}", core_path.join("candles.h").display());
    println!("cargo:rerun-if-changed={}", core_path.join("volume.c").display());
    println!("cargo:rerun-if-changed={}", core_path.join("volume.h").display());
    println!("cargo:rerun-if-changed={}", core_path.join("volatility.c").display());
    println!("cargo:rerun-if-changed={}", core_path.join("volatility.h").display());
}
