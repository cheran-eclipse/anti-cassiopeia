| System | n scored | Correct old -> corrected | Dangerous old -> corrected | Precision when answering old -> corrected | Claims whose score changed |
|---|---|---|---|---|---|
| Pipeline (saved run, old adapter) | 872 | 100.0% -> 97.1% (872 -> 847) | 0.0% -> 2.9% (0 -> 25) | 100.0% -> 97.1% | 25 |
| Bare Nebius | 872 | 11.9% -> 11.9% (104 -> 104) | 1.8% -> 1.8% (16 -> 16) | 86.7% -> 86.7% | 2 |
| Generic RAG | 872 | 34.3% -> 34.7% (299 -> 303) | 18.8% -> 18.3% (164 -> 160) | 64.6% -> 65.4% | 12 |
| Perplexity | 872 | 6.9% -> 6.9% (60 -> 60) | 3.0% -> 3.0% (26 -> 26) | 69.8% -> 69.8% | 0 |
| Tavily+Gemini (scored claims only) | 473 | 11.0% -> 11.4% (52 -> 54) | 4.7% -> 4.2% (22 -> 20) | 70.3% -> 73.0% | 4 |
| Code-exec | 872 | 99.1% -> 96.2% (864 -> 839) | 0.5% -> 3.3% (4 -> 29) | 99.5% -> 96.7% | 25 |
| Nebius-agent (ml/fpga = copy of pipeline) | 872 | 100.0% -> 97.1% (872 -> 847) | 0.0% -> 2.9% (0 -> 25) | 100.0% -> 97.1% | 25 |
| Pipeline (current engine re-run) | 872 | 97.1% -> 100.0% (847 -> 872) | 2.9% -> 0.0% (25 -> 0) | 97.1% -> 100.0% | 25 |
