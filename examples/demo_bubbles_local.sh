#!/bin/bash
# Demo script for bubbles visualization using local sample data
# No internet connection required - uses included sample data

set -e

echo "🎨 Bubbles Visualization Demo (Local Data)"
echo "==========================================="
echo ""
echo "Using: examples/data/btcusdt_aggtrades_sample.csv"
echo ""

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Create outputs directory
mkdir -p outputs

echo -e "${CYAN}This demo will create 4 visualizations:${NC}"
echo "  1. Basic bubbles (mean-reversion strategy)"
echo "  2. Momentum strategy"
echo "  3. Mean-reversion strategy"
echo "  4. All strategies comparison"
echo ""
read -p "Press Enter to continue..."
echo ""

# Check if data file exists
if [ ! -f "examples/data/btcusdt_aggtrades_sample.csv" ]; then
    echo -e "${YELLOW}⚠️  Sample data not found!${NC}"
    echo "Expected: examples/data/btcusdt_aggtrades_sample.csv"
    exit 1
fi

echo -e "${BLUE}[1/4]${NC} Basic bubbles visualization..."
python examples/bubbles_visualization.py \
  --csv examples/data/btcusdt_aggtrades_sample.csv \
  --bucket-ms 100 \
  --output outputs/demo_basic.png \
  --title "BTCUSDT - Basic Bubbles Demo"

echo ""
echo -e "${GREEN}✅ Created: outputs/demo_basic.png${NC}"
echo ""

echo -e "${BLUE}[2/4]${NC} Momentum strategy..."
python examples/bubbles_advanced.py \
  --csv examples/data/btcusdt_aggtrades_sample.csv \
  --strategy momentum \
  --bucket-ms 100 \
  --output outputs/demo_momentum.png

echo ""
echo -e "${GREEN}✅ Created: outputs/demo_momentum.png${NC}"
echo ""

echo -e "${BLUE}[3/4]${NC} Mean-reversion strategy..."
python examples/bubbles_advanced.py \
  --csv examples/data/btcusdt_aggtrades_sample.csv \
  --strategy mean-reversion \
  --bucket-ms 100 \
  --output outputs/demo_mean_reversion.png

echo ""
echo -e "${GREEN}✅ Created: outputs/demo_mean_reversion.png${NC}"
echo ""

echo -e "${BLUE}[4/4]${NC} Strategy comparison (all strategies)..."
python examples/bubbles_advanced.py \
  --csv examples/data/btcusdt_aggtrades_sample.csv \
  --compare \
  --bucket-ms 100 \
  --output outputs/demo_comparison.png

echo ""
echo -e "${GREEN}✅ Created: outputs/demo_comparison.png${NC}"
echo ""

echo "=========================================="
echo -e "${GREEN}🎉 Demo completed successfully!${NC}"
echo ""
echo "Generated visualizations:"
echo ""
echo "  📊 outputs/demo_basic.png"
echo "     └─ Basic bubbles with mean-reversion strategy"
echo ""
echo "  📊 outputs/demo_momentum.png"
echo "     └─ Momentum strategy (MA crossover)"
echo ""
echo "  📊 outputs/demo_mean_reversion.png"
echo "     └─ Mean-reversion strategy (Bollinger Bands)"
echo ""
echo "  📊 outputs/demo_comparison.png"
echo "     └─ Side-by-side comparison of all strategies"
echo ""
echo -e "${YELLOW}💡 Tips:${NC}"
echo "  • Bubble size = order quantity"
echo "  • Green = BUY orders"
echo "  • Red = SELL orders"
echo "  • Bottom panel shows equity curve"
echo ""
echo -e "${CYAN}Next steps:${NC}"
echo "  • Open the PNG files to view visualizations"
echo "  • Try with live data: ./examples/quick_bubbles_test.sh"
echo "  • Read more: examples/BUBBLES_README.md"
echo ""
