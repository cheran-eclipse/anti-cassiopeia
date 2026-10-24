
## Test codeexec batch `investigate_empty` — 3 dangerous/crash result(s) (code-execution baseline; not a pipeline bug)

### ml_data-000767 (ml_data, tier 1)
- Claim: `{"text": "stdev(RH_3) in appliances_energy_prediction.csv is 7.51", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_3", "stat": "stdev", "expected_value": 7.509152985250896, "tolerance": 0.003254576492625448}}`
- Code-exec predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `CodeExecError: NEBIUS_API_KEY not loaded from .env via dotenv_values().`

### ml_data-001857 (ml_data, tier 1)
- Claim: `{"text": "min(AP) in gas_turbine_emission.csv is 985.85", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AP", "stat": "min", "expected_value": 985.85, "tolerance": 1e-09}}`
- Code-exec predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `CodeExecError: NEBIUS_API_KEY not loaded from .env via dotenv_values().`

### ml_data-001860 (ml_data, tier 2)
- Claim: `{"text": "mean(AP) in gas_turbine_emission.csv is 1165", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AP", "stat": "mean", "expected_value": 1165.0306897204148, "tolerance": 50.65350824871369}}`
- Code-exec predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `CodeExecError: NEBIUS_API_KEY not loaded from .env via dotenv_values().`


## Test codeexec batch `investigate_empty` — 3 dangerous/crash result(s) (code-execution baseline; not a pipeline bug)

### ml_data-000767 (ml_data, tier 1)
- Claim: `{"text": "stdev(RH_3) in appliances_energy_prediction.csv is 7.51", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/appliances_energy_prediction.csv", "column": "RH_3", "stat": "stdev", "expected_value": 7.509152985250896, "tolerance": 0.003254576492625448}}`
- Code-exec predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `CodeExecError: Nebius returned 503: <html>
<head><title>503 Service Temporarily Unavailable</title></head>
<body>
<center><h1>503 Service Temporarily Unavailable</h1></center>
<hr><center>nginx</center>
</body>
</html>
`

### ml_data-001857 (ml_data, tier 1)
- Claim: `{"text": "min(AP) in gas_turbine_emission.csv is 985.85", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AP", "stat": "min", "expected_value": 985.85, "tolerance": 1e-09}}`
- Code-exec predicted: **CRASH**, ground truth: **confirmed** (crash)
- Error: `CodeExecError: Nebius returned 503: <html>
<head><title>503 Service Temporarily Unavailable</title></head>
<body>
<center><h1>503 Service Temporarily Unavailable</h1></center>
<hr><center>nginx</center>
</body>
</html>
`

### ml_data-001860 (ml_data, tier 2)
- Claim: `{"text": "mean(AP) in gas_turbine_emission.csv is 1165", "domain": "ml_data", "context": {"dataset_path": "stress_test/data/ml_data/gas_turbine_emission.csv", "column": "AP", "stat": "mean", "expected_value": 1165.0306897204148, "tolerance": 50.65350824871369}}`
- Code-exec predicted: **CRASH**, ground truth: **contradicted** (crash)
- Error: `CodeExecError: Nebius returned 503: <html>
<head><title>503 Service Temporarily Unavailable</title></head>
<body>
<center><h1>503 Service Temporarily Unavailable</h1></center>
<hr><center>nginx</center>
</body>
</html>
`

