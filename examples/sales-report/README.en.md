# CSV → summary, chart and report

[简体中文](README.md)

A reproducible PocketExpertHarness example using **12 rows of synthetic sales data**. These are not customer records or actual business revenue.

![Chart from the reference run](reference/revenue.png)

The agent checks the input, aggregates orders and revenue, draws a chart, and writes a Chinese report. [prompt.txt](prompt.txt) contains the complete prompt; [reference/](reference/) contains actual outputs from one run. Wording and chart styling may vary.

## Run from the repository root

Install the package and configure a tool-capable model following the main README. No web search or pandas is needed.

```bash
export PEH_PROVIDER=deepseek
export LLM_API_KEY=your-model-key
mkdir -p workspace/sales-example
cp examples/sales-report/sales.csv workspace/sales-example/sales.csv
PEH_HOME="$PWD/data/sales-example" \
PEH_WORKSPACE="$PWD/workspace/sales-example" \
PEH_PYTHON=ask \
peh run "$(cat examples/sales-report/prompt.txt)"
```

Inspect generated Python before approving its execution. The Python tool is not a security sandbox; use an isolated environment if needed. Remote model services receive task data. Read the generated files in `workspace/sales-example/` and use the independent standard-library verification snippet in the [Chinese guide](README.md#独立核对数字).

Expected total: **478 orders and CNY 146,670 of synthetic revenue**. The overall average order value is **306.84**, calculated from total revenue divided by total orders, not the unweighted average of channel averages.

| Channel | Orders | Synthetic revenue / CNY | Average / CNY |
|---|---:|---:|---:|
| Web | 175 | 54,330 | 310.46 |
| App | 172 | 56,060 | 325.93 |
| MiniProgram | 131 | 36,280 | 276.95 |
| TOTAL | 478 | 146,670 | 306.84 |

Reference run: 2026-09-30, Harness 0.2.0, a compatible endpoint configured with model ID `deepseek-v4.1-flash`, Python enabled, no MCP or search backend. The turn took about 69 seconds. This is one small example, not a benchmark, performance promise, or real business result. All reference summary totals and weighted averages were independently recomputed from the input.

For configured experts without setting up model keys, try [Pocket Expert AI](https://agentsdance.ai/?utm_source=github&utm_medium=example&utm_campaign=peh-organic-20260930&utm_content=csv-report), which shares the kernel but has different features and a different runtime environment.
