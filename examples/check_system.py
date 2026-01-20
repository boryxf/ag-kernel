#!/usr/bin/env python3
"""
System Check Script for ag-kernel Bubbles Visualization
========================================================

This script checks that all required components are installed and working:
- Python version
- Required packages
- ag-kernel engine
- Data files
- Binance API connectivity

Run this before using the bubbles visualization scripts.
"""

import sys
from pathlib import Path


# Colors for terminal output
class Colors:
    GREEN = "\033[0;32m"
    RED = "\033[0;31m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"  # No Color


def check_python_version():
    """Check Python version >= 3.9"""
    print(f"{Colors.BLUE}[1/7]{Colors.NC} Checking Python version...", end=" ")
    version = sys.version_info
    if version.major >= 3 and version.minor >= 9:
        print(
            f"{Colors.GREEN}✓{Colors.NC} Python {version.major}.{version.minor}.{version.micro}"
        )
        return True
    else:
        print(
            f"{Colors.RED}✗{Colors.NC} Python {version.major}.{version.minor}.{version.micro} (need 3.9+)"
        )
        return False


def check_package(package_name, import_name=None):
    """Check if a package is installed"""
    if import_name is None:
        import_name = package_name

    try:
        module = __import__(import_name)
        version = getattr(module, "__version__", "unknown")
        return True, version
    except ImportError:
        return False, None


def check_required_packages():
    """Check all required packages"""
    print(f"{Colors.BLUE}[2/7]{Colors.NC} Checking required packages...")

    packages = [
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("matplotlib", "matplotlib"),
        ("requests", "requests"),
    ]

    all_ok = True
    for pkg_name, import_name in packages:
        ok, version = check_package(pkg_name, import_name)
        if ok:
            print(f"  {Colors.GREEN}✓{Colors.NC} {pkg_name} ({version})")
        else:
            print(f"  {Colors.RED}✗{Colors.NC} {pkg_name} (not installed)")
            all_ok = False

    if not all_ok:
        print(f"\n{Colors.YELLOW}Install missing packages:{Colors.NC}")
        print(f"  pip install -r requirements.txt")

    return all_ok


def check_ag_kernel():
    """Check if ag-kernel engine is available"""
    print(f"{Colors.BLUE}[3/7]{Colors.NC} Checking ag-kernel engine...", end=" ")

    # Add python directory to path
    sys.path.insert(0, str(Path(__file__).parent.parent / "python"))

    try:
        from ag_backtester import Engine, EngineConfig

        print(f"{Colors.GREEN}✓{Colors.NC} ag_backtester module loaded")

        # Try to create an engine instance
        try:
            config = EngineConfig(initial_cash=10000.0)
            engine = Engine(config)
            print(f"  {Colors.GREEN}✓{Colors.NC} Engine instantiation successful")
            return True
        except Exception as e:
            print(f"  {Colors.RED}✗{Colors.NC} Engine instantiation failed: {e}")
            print(f"\n{Colors.YELLOW}Build the engine:{Colors.NC}")
            print(f"  cd crates/ag-core")
            print(f"  maturin develop --release")
            return False

    except ImportError as e:
        print(f"{Colors.RED}✗{Colors.NC} {e}")
        print(f"\n{Colors.YELLOW}Build the engine:{Colors.NC}")
        print(f"  cd crates/ag-core")
        print(f"  maturin develop --release")
        return False


def check_data_files():
    """Check if sample data files exist"""
    print(f"{Colors.BLUE}[4/7]{Colors.NC} Checking sample data files...")

    base_path = Path(__file__).parent
    data_files = [
        base_path / "data" / "btcusdt_aggtrades_sample.csv",
        base_path / "data" / "btcusdt_aggtrades_1m.csv",
    ]

    all_ok = True
    for file_path in data_files:
        if file_path.exists():
            size_kb = file_path.stat().st_size / 1024
            print(f"  {Colors.GREEN}✓{Colors.NC} {file_path.name} ({size_kb:.1f} KB)")
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.NC} {file_path.name} (not found)")
            all_ok = False

    if not all_ok:
        print(
            f"  {Colors.CYAN}ℹ{Colors.NC} Local data missing, but you can use --fetch to get live data"
        )

    return True  # Not critical, can fetch data


def check_binance_api():
    """Check if Binance API is accessible"""
    print(
        f"{Colors.BLUE}[5/7]{Colors.NC} Checking Binance API connectivity...", end=" "
    )

    try:
        import requests

        response = requests.get("https://api.binance.com/api/v3/ping", timeout=5)
        if response.status_code == 200:
            print(f"{Colors.GREEN}✓{Colors.NC} Binance API accessible")
            return True
        else:
            print(
                f"{Colors.YELLOW}⚠{Colors.NC} Binance API returned status {response.status_code}"
            )
            return False
    except Exception as e:
        print(f"{Colors.YELLOW}⚠{Colors.NC} Cannot reach Binance API: {e}")
        print(f"  {Colors.CYAN}ℹ{Colors.NC} You can still use local CSV files")
        return False


def check_visualization_scripts():
    """Check if visualization scripts exist"""
    print(f"{Colors.BLUE}[6/7]{Colors.NC} Checking visualization scripts...")

    base_path = Path(__file__).parent
    scripts = [
        "bubbles_visualization.py",
        "bubbles_advanced.py",
        "demo_bubbles_local.sh",
        "quick_bubbles_test.sh",
    ]

    all_ok = True
    for script in scripts:
        script_path = base_path / script
        if script_path.exists():
            print(f"  {Colors.GREEN}✓{Colors.NC} {script}")
        else:
            print(f"  {Colors.RED}✗{Colors.NC} {script} (missing)")
            all_ok = False

    return all_ok


def check_outputs_directory():
    """Check/create outputs directory"""
    print(f"{Colors.BLUE}[7/7]{Colors.NC} Checking outputs directory...", end=" ")

    outputs_dir = Path(__file__).parent.parent / "outputs"

    if outputs_dir.exists():
        print(f"{Colors.GREEN}✓{Colors.NC} outputs/ exists")
    else:
        try:
            outputs_dir.mkdir(parents=True, exist_ok=True)
            print(f"{Colors.GREEN}✓{Colors.NC} outputs/ created")
        except Exception as e:
            print(f"{Colors.RED}✗{Colors.NC} Cannot create outputs/ : {e}")
            return False

    return True


def print_summary(checks):
    """Print summary of all checks"""
    print("\n" + "=" * 60)

    passed = sum(checks.values())
    total = len(checks)

    if passed == total:
        print(f"{Colors.GREEN}🎉 All checks passed! ({passed}/{total}){Colors.NC}")
        print("\nYou're ready to use the bubbles visualization!")
        print("\nQuick start:")
        print(f"  {Colors.CYAN}# Demo with local data{Colors.NC}")
        print(f"  ./examples/demo_bubbles_local.sh")
        print()
        print(f"  {Colors.CYAN}# Fetch live data from Binance{Colors.NC}")
        print(f"  python examples/bubbles_visualization.py --fetch --limit 500")
        print()
        print(f"  {Colors.CYAN}# Compare strategies{Colors.NC}")
        print(f"  python examples/bubbles_advanced.py --fetch --limit 1000 --compare")
    else:
        print(
            f"{Colors.YELLOW}⚠ Some checks failed ({passed}/{total} passed){Colors.NC}"
        )
        print("\nPlease fix the issues above before proceeding.")

        if not checks["ag_kernel"]:
            print(
                f"\n{Colors.YELLOW}Most important:{Colors.NC} Build the ag-kernel engine:"
            )
            print("  cd crates/ag-core")
            print("  maturin develop --release")

        if not checks["packages"]:
            print(f"\n{Colors.YELLOW}Install missing packages:{Colors.NC}")
            print("  pip install -r requirements.txt")

    print("=" * 60)


def main():
    """Run all checks"""
    print(f"\n{Colors.CYAN}ag-kernel Bubbles Visualization System Check{Colors.NC}")
    print("=" * 60)
    print()

    checks = {
        "python": check_python_version(),
        "packages": check_required_packages(),
        "ag_kernel": check_ag_kernel(),
        "data": check_data_files(),
        "binance_api": check_binance_api(),
        "scripts": check_visualization_scripts(),
        "outputs": check_outputs_directory(),
    }

    print_summary(checks)

    # Exit code
    if all(checks.values()):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
