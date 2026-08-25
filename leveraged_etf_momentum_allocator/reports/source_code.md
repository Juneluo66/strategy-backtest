# Original QuantConnect Source — Strategy #60

**Class:** `ConditionalSectorRotation`  
**Status:** VERIFIED — frozen source of truth  
**Internal name:** `conditional_leveraged_etf_rotation`

```python
from AlgorithmImports import *


class ConditionalSectorRotation(QCAlgorithm):

    def Initialize(self):
        self.SetStartDate(2012, 1, 1)
        self.SetCash(100000)
        # ... (full source preserved in project specification)
```

See `configs/original.yaml` for frozen parameter extraction.

**Key facts:**
- NOT a generic momentum strategy — RSI + SMA decision tree
- SQQQ is signal-only, never SetHoldings target
- Target assets: TQQQ, UVXY, TECL, SPXL, TECS, BSV
- SetWarmUp(200), daily OnData, SetHoldings(1.0, liquidateExistingHoldings=True)
