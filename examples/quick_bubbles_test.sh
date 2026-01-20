#!/bin/bash
# Quick test script for bubbles visualization
# This script runs all visualization modes and saves outputs

set -e

echo "🎨 Bubbles Visualization Quick Test"
echo "===================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Create outputs directory
mkdir -p outputs

echo -e "${BLUE}[1/4]${NC} Testing basic bubbles with Binance API..."
python examples/bubbles_visualization.py \
  --fetch \
  --limit 500 \
  --output outputs/test_basic.png

echo ""
echo -e "${GREEN}✅ Basic bubbles created: outputs/test_basic.png${NC}"
echo ""

echo -e "${BLUE}[2/4]${NC} Testing momentum strategy..."
python examples/bubbles_advanced.py \
  --fetch \
  --limit 500 \
  --strategy momentum \
  --output outputs/test_momentum.png

echo ""
echo -e "${GREEN}✅ Momentum strategy: outputs/test_momentum.png${NC}"
echo ""

echo -e "${BLUE}[3/4]${NC} Testing mean-reversion strategy..."
python examples/bubbles_advanced.py \
  --fetch \
  --limit 500 \
  --strategy mean-reversion \
  --output outputs/test_mean_reversion.png

echo ""
echo -e "${GREEN}✅ Mean reversion: outputs/test_mean_reversion.png${NC}"
echo ""

echo -e "${BLUE}[4/4]${NC} Testing strategy comparison (all strategies)..."
python examples/bubbles_advanced.py \
  --fetch \
  --limit 800 \
  --compare \
  --output outputs/test_comparison.png

echo ""
echo -e "${GREEN}✅ Strategy comparison: outputs/test_comparison.png${NC}"
echo ""

echo "=========================================="
echo -e "${GREEN}🎉 All tests completed successfully!${NC}"
echo ""
echo "Generated files:"
echo "  📊 outputs/test_basic.png           - Basic bubbles"
echo "  📊 outputs/test_momentum.png        - Momentum strategy"
echo "  📊 outputs/test_mean_reversion.png  - Mean reversion strategy"
echo "  📊 outputs/test_comparison.png      - All strategies compared"
echo ""
echo -e "${YELLOW}💡 Open these PNG files to view the visualizations${NC}"
