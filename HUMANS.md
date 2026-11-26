# Decisions needed

## Step 8: Harriet correctness gate after all three permitted attempts

Status: resolved by developer on 2026-11-26: “yes, go on” authorizes treating this 0.025 difference as evaluator variance and continuing the fixed sample. Historical scores and all attempt records remain unchanged.

The roadmap requires advancing only after the preceding item has no unresolved execution error or correctness regression. OpenAI question 2 (QA.csv, a6ee3143-428c-5d8e-8d8e-d131dc92ac54, “Who killed Harriet?”) scored 0.95 in each of three fresh attempts, compared with the frozen recorded 0.975. The rerun allowance is exhausted. Each answer correctly says she survived; citation support is 1.0 and no tool/telemetry/trace structure errors were found. All attempts share executable source fingerprint e066b617dd6c88f1b6e252557ddb945406fc1d003a9d5aa21380ade8abb53027.

The historical evaluator marked D2 present, explaining “she was alive,” although D2 actually requires living in Australia under an assumed identity until Mikael found her. The saved historical answer does not mention Australia or an assumed identity. Current evaluations mark that detail partial. Managed evaluator definitions match the historical OpenAI definitions exactly; the evaluator identity differs only through its code fingerprint. This supports an evaluator-variance explanation but does not automatically waive the roadmap's serial gate.

Required decision: authorize recording this 0.025 difference as evaluator variance and continuing, or keep the strict gate and stop validation here. Do not change prompts, evidence policy, historical scores, or generate a replacement baseline to conceal the discrepancy. The developer has been notified and asked this question in chat.

Evidence: docs/experiments/langgraph-v2.17-step1/comparison-manifest.json, questions[1]; docs/experiments/langgraph-v2.17-step8/openai-q02-a1, openai-q02-a2, openai-q02-a3 (request, manifest, results, live trace and review for each); progress.json. The first attempt is provisionally selected because all three correctness scores tie; its 18.24-second latency belongs to that exact attempt. Nothing is accepted as Step 9 aggregate acceptance.
