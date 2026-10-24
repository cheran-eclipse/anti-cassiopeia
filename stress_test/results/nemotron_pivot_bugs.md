
## Batch `baseline_pilot` — 2 dangerous/crash result(s) found

### research_web-003296 (research_web, tier 3)
- Claim: `{"text": "The Raspberry Pi 5 draws exactly 1.2 watts at idle", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Raspberry_Pi by reading the real page

### research_web-003302 (research_web, tier 3)
- Claim: `{"text": "The BeagleBone Black has exactly 47 GPIO pins", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/BeagleBone by reading the real page


## Batch `nemotron_pilot` — 1 dangerous/crash result(s) found

### research_web-003302 (research_web, tier 3)
- Claim: `{"text": "The BeagleBone Black has exactly 47 GPIO pins", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/BeagleBone by reading the real page


## Batch `baseline_pilot` — 1 dangerous/crash result(s) found

### research_web-003302 (research_web, tier 3)
- Claim: `{"text": "The BeagleBone Black has exactly 47 GPIO pins", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/BeagleBone by reading the real page


## Batch `nemotron_pilot` — 2 dangerous/crash result(s) found

### research_web-003297 (research_web, tier 1)
- Claim: `{"text": "The ESP32 is a microcontroller manufactured by Espressif Systems", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: fact independently confirmed live by fetching https://en.wikipedia.org/wiki/ESP32 (see PROVENANCE.md)

### research_web-003302 (research_web, tier 3)
- Claim: `{"text": "The BeagleBone Black has exactly 47 GPIO pins", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/BeagleBone by reading the real page


## Batch `nemotron_pilot` — 1 dangerous/crash result(s) found

### robotics-002931 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 110 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: real-world resolution, independent of engine.py: aluminum housing variant rated 300m (DOC1), acrylic housing variant rated 100m (DOC2), both real -- undetermined exactly when the two real housings disagree (100 < depth <= 300m), otherwise both agree and the claim is unambiguous


## Batch `baseline_pilot` — 4 dangerous/crash result(s) found

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/BlueROV2 by reading the real page

### research_web-003317 (research_web, tier 3)
- Claim: `{"text": "The Linux kernel's source tree contains exactly 40 million lines of code", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Linux_kernel by reading the real page

### research_web-003320 (research_web, tier 3)
- Claim: `{"text": "Python's reference implementation compiles source code to native machine code by default", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Python_(programming_language) by reading the real page

### research_web-003326 (research_web, tier 3)
- Claim: `{"text": "The Jetson TX2 model draws exactly 7.5 watts under all workloads", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Nvidia_Jetson by reading the real page


## Batch `baseline_pilot` — 5 dangerous/crash result(s) found

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/BlueROV2 by reading the real page

### research_web-003311 (research_web, tier 3)
- Claim: `{"text": "Xilinx's first FPGA shipped with exactly 64 configurable logic blocks", "domain": "research_web", "context": {}}`
- Predicted: **confirmed**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Xilinx by reading the real page

### research_web-003317 (research_web, tier 3)
- Claim: `{"text": "The Linux kernel's source tree contains exactly 40 million lines of code", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Linux_kernel by reading the real page

### research_web-003320 (research_web, tier 3)
- Claim: `{"text": "Python's reference implementation compiles source code to native machine code by default", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Python_(programming_language) by reading the real page

### research_web-003326 (research_web, tier 3)
- Claim: `{"text": "The Jetson TX2 model draws exactly 7.5 watts under all workloads", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Nvidia_Jetson by reading the real page


## Batch `nemotron_pilot` — 7 dangerous/crash result(s) found

### research_web-003290 (research_web, tier 3)
- Claim: `{"text": "BlueROV2 has a maximum operating time of 14 hours", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/BlueROV2 by reading the real page

### research_web-003297 (research_web, tier 1)
- Claim: `{"text": "The ESP32 is a microcontroller manufactured by Espressif Systems", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **confirmed** (dangerous)
- Ground truth method: fact independently confirmed live by fetching https://en.wikipedia.org/wiki/ESP32 (see PROVENANCE.md)

### research_web-003304 (research_web, tier 2)
- Claim: `{"text": "Analog Devices is a Japanese semiconductor manufacturer", "domain": "research_web", "context": {}}`
- Predicted: **CRASH**, ground truth: **contradicted** (crash)
- Ground truth method: negated/altered from the real fact at https://en.wikipedia.org/wiki/Analog_Devices (see PROVENANCE.md)
- Error: `ValueError: Model response was not valid JSON after stripping fences: '{"found": true, "chunk_id": "https://en.wikipedia.org/wiki/Analog_Devices#7", "quote": "American semiconductor manufacturer      This article is about the semiconductor company. For the general concept, see  Analog device .       {{cite web|url=https://www.sec.gov/ix?doc=/Archives/edgar/data/6281/000000628125000153/adi-20251101.htm |title=FY 2025 Annual Report (Form 10-K) |publisher=[[U.S. Securities and Exchange Commission]] |date=25 November 2025}}&lt;/ref>\\"}},"i":0}}]}\'>       Analog Devices, Inc.             Type   Public       Traded as           Nasdaq :   ADI    Nasdaq-100  component   S&amp;P 500  component       Industry   Semiconductors     Founded  1965  ;    61   years ago    ( 1965 )  in  Cambridge, Massachusetts , U.S.    Founders         Ray Stata    Matthew Lorber        Headquarters    Wilmington, Massachusetts , U.S.       Key   people  Vincent Ro", "value": null, "unit": null, "kind": null}'`

### research_web-003311 (research_web, tier 3)
- Claim: `{"text": "Xilinx's first FPGA shipped with exactly 64 configurable logic blocks", "domain": "research_web", "context": {}}`
- Predicted: **confirmed**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Xilinx by reading the real page

### research_web-003317 (research_web, tier 3)
- Claim: `{"text": "The Linux kernel's source tree contains exactly 40 million lines of code", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Linux_kernel by reading the real page

### research_web-003320 (research_web, tier 3)
- Claim: `{"text": "Python's reference implementation compiles source code to native machine code by default", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Python_(programming_language) by reading the real page

### research_web-003326 (research_web, tier 3)
- Claim: `{"text": "The Jetson TX2 model draws exactly 7.5 watts under all workloads", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Nvidia_Jetson by reading the real page


## Batch `nemotron_pilot` — 5 dangerous/crash result(s) found

### research_web-003296 (research_web, tier 3)
- Claim: `{"text": "The Raspberry Pi 5 draws exactly 1.2 watts at idle", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Raspberry_Pi by reading the real page

### research_web-003303 (research_web, tier 1)
- Claim: `{"text": "Analog Devices is an American semiconductor manufacturer", "domain": "research_web", "context": {}}`
- Predicted: **CRASH**, ground truth: **confirmed** (crash)
- Ground truth method: fact independently confirmed live by fetching https://en.wikipedia.org/wiki/Analog_Devices (see PROVENANCE.md)
- Error: `AttributeError: 'NoneType' object has no attribute 'strip'`

### research_web-003311 (research_web, tier 3)
- Claim: `{"text": "Xilinx's first FPGA shipped with exactly 64 configurable logic blocks", "domain": "research_web", "context": {}}`
- Predicted: **confirmed**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Xilinx by reading the real page

### research_web-003317 (research_web, tier 3)
- Claim: `{"text": "The Linux kernel's source tree contains exactly 40 million lines of code", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Linux_kernel by reading the real page

### research_web-003320 (research_web, tier 3)
- Claim: `{"text": "Python's reference implementation compiles source code to native machine code by default", "domain": "research_web", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: plausible-sounding but confirmed ABSENT from https://en.wikipedia.org/wiki/Python_(programming_language) by reading the real page


## Batch `nemotron_pilot` — 3 dangerous/crash result(s) found

### robotics-002929 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 fails at 105 m depth", "domain": "robotics", "context": {}}`
- Predicted: **confirmed**, ground truth: **undetermined** (dangerous)
- Ground truth method: real-world resolution, independent of engine.py: aluminum housing variant rated 300m (DOC1), acrylic housing variant rated 100m (DOC2), both real -- undetermined exactly when the two real housings disagree (100 < depth <= 300m), otherwise both agree and the claim is unambiguous

### robotics-002934 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 120 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: real-world resolution, independent of engine.py: aluminum housing variant rated 300m (DOC1), acrylic housing variant rated 100m (DOC2), both real -- undetermined exactly when the two real housings disagree (100 < depth <= 300m), otherwise both agree and the claim is unambiguous

### robotics-002940 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 135 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: real-world resolution, independent of engine.py: aluminum housing variant rated 300m (DOC1), acrylic housing variant rated 100m (DOC2), both real -- undetermined exactly when the two real housings disagree (100 < depth <= 300m), otherwise both agree and the claim is unambiguous


## Batch `nemotron_pilot` — 1 dangerous/crash result(s) found

### robotics-002932 (robotics, tier 3)
- Claim: `{"text": "BlueROV2 survives 115 m depth", "domain": "robotics", "context": {}}`
- Predicted: **contradicted**, ground truth: **undetermined** (dangerous)
- Ground truth method: real-world resolution, independent of engine.py: aluminum housing variant rated 300m (DOC1), acrylic housing variant rated 100m (DOC2), both real -- undetermined exactly when the two real housings disagree (100 < depth <= 300m), otherwise both agree and the claim is unambiguous

