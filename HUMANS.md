# Decisions needed

## Step 8: Harriet correctness gate after all three permitted attempts

Status: resolved by developer on 2026-11-26: “yes, go on” authorizes treating this 0.025 difference as evaluator variance and continuing the fixed sample. Historical scores and all attempt records remain unchanged.

The roadmap requires advancing only after the preceding item has no unresolved execution error or correctness regression. OpenAI question 2 (QA.csv, a6ee3143-428c-5d8e-8d8e-d131dc92ac54, “Who killed Harriet?”) scored 0.95 in each of three fresh attempts, compared with the frozen recorded 0.975. The rerun allowance is exhausted. Each answer correctly says she survived; citation support is 1.0 and no tool/telemetry/trace structure errors were found. All attempts share executable source fingerprint e066b617dd6c88f1b6e252557ddb945406fc1d003a9d5aa21380ade8abb53027.

The historical evaluator marked D2 present, explaining “she was alive,” although D2 actually requires living in Australia under an assumed identity until Mikael found her. The saved historical answer does not mention Australia or an assumed identity. Current evaluations mark that detail partial. Managed evaluator definitions match the historical OpenAI definitions exactly; the evaluator identity differs only through its code fingerprint. This supports an evaluator-variance explanation but does not automatically waive the roadmap's serial gate.

Required decision: authorize recording this 0.025 difference as evaluator variance and continuing, or keep the strict gate and stop validation here. Do not change prompts, evidence policy, historical scores, or generate a replacement baseline to conceal the discrepancy. The developer has been notified and asked this question in chat.

Evidence: docs/experiments/langgraph-v2.17-step1/comparison-manifest.json, questions[1]; docs/experiments/langgraph-v2.17-step8/openai-q02-a1, openai-q02-a2, openai-q02-a3 (request, manifest, results, live trace and review for each); progress.json. The first attempt is provisionally selected because all three correctness scores tie; its 18.24-second latency belongs to that exact attempt. Nothing is accepted as Step 9 aggregate acceptance.

## Step 8: first-book summary supporting-fact discrepancy

Status: resolved by developer on 2026-11-26: “record and continue” authorizes recording the best attempt’s 0.0333 gap as an evaluator discrepancy and continuing. Historical scores and all attempt records remain unchanged.

OpenAI Q6 (right-set-3, 87382e52-ad6e-5336-9aa1-1b0d29cfc8ed) exhausted three permitted attempts: 0.60 / 49.82 seconds; 0.45 / 37.48 seconds; 0.3333 / 41.25 seconds. Historical correctness is 0.6333. Attempt 1 is the best and is provisionally selected, with its own latency. All three traces show ten turns followed by application budget drafting and one finalization; attempt 1 additionally synthesizes inside finalization. No framework, provider, tool or trace structure error was found.

The selected attempt and historical baseline both receive R1 present, R2 present and R3 missing. The historical judge additionally marks D1 present (“Martin dies after trying to kill Mikael”), although the saved historical answer only says Martin tries to kill Blomkvist, without his death. Its explanation even says that detail is missing, contradicting its own verdict. The candidate judge marks D1 missing, accounting for the 0.0333 gap. Both saved answers omit Wennerstrom's exposure through hacking. Citation scores of 0.5 and grouped passage IDs in some candidate answers remain visible; no score or answer was repaired. The second attempt's citation judge also rejects the equivalent wording “fled her brother” versus “ran away from her brother.”

Required decision: authorize treating the best attempt's 0.0333 gap as an evaluator discrepancy and continuing, or retain the strict gate. The prior developer authorization resolved Harriet specifically. Prompts, evidence policy, historical results and the three-attempt limit remain unchanged. Developer notified in chat.

Evidence: frozen comparison-manifest.json questions[5], and Step 8 openai-q06-a1/a2/a3 retained results, manifests, live traces and reviews. Step 8 remains incomplete; Step 9 has not started.

## Step 8: substantive abandoned-factory regression

Status: resolved by developer on 2026-11-26: current answer approved as perfectly correct; requested scorer correction isolated to this question and continuation. Factory rubric now accepts the approved core account. Live rescore v2 gives attempts 1/3 full credit and the scene-confused attempt 2 only 0.5. Original scores and prior diagnosis retained as history.

OpenAI Q9 (Additional Questions, 36c50723-3b65-49f6-9d9b-70574cc9471c) exhausted all three permitted attempts: 0.5167 / 41.12 seconds; 0.5 / 56.09 seconds; 0.5167 / 45.12 seconds. Historical correctness is 1.0. Attempt 1 is provisionally selected as the earliest best-correctness tie, using its own latency. All results remain unchanged.

All three answers omit the required nail-gun immobilization of Niedermann. Attempt 2 additionally mixes the Gosseberga shooting/burial into the brickworks account. Citation support is 0.5 on attempt 1. The final cited evidence in all three attempts lacks the word “nail.” All traces complete ten investigation turns, application budget drafting and one finalization, with no provider, tool, telemetry or graph structure errors. Attempts 2 and 3 include coverage rewriting. Source inspection confirms legacy runner _finish and graph prepare_final_answer are the same helper (app/agent/submission.py), including that rewrite. No behavior change or new baseline was introduced. These observations locate the answer-quality failure but do not establish that the migration is accepted.

Required decision: authorize recording the substantive failure and continuing the remaining serial validation, or keep the gate and investigate changes to preserved pipeline behavior. The prior authorizations cover Harriet and the summary evaluator discrepancies; they do not waive this substantive regression. Developer notified with both options in chat. No fourth attempt may be run under the current agreement.

Evidence: Step 8 openai-q09-a1/a2/a3 results, manifests, traces and reviews, frozen Step 1 questions[8], progress.json. Step 8 remains incomplete and Step 9 has not started.

## Step 8: local mathematics-book evaluator discrepancy

Status: resolved by developer on 2026-11-26: “record and cont” authorizes recording this and similarly verified evaluator-only discrepancies while continuing, leaving other scorers unchanged and still stopping for execution errors or substantive wrong answers.

Ollama Q1 exhausted three permitted attempts: correctness 0.90/0.95/0.95 versus recorded local fallback 1.0. Attempt 2 is provisionally selected as the earliest best-score tie, with its own 33.21-second latency. The answers correctly identify Dimensions in Mathematics and describe memorization/carrying. The older local baseline uses qwen3:8b and evaluator version 1; its saved score credits L.C. Young even though its saved answer names no author. Current evaluator version 2 scores author/publication supporting details; no rubric or scorer for this question was changed. All three executions and traces complete normally after expected submission rejections.

Required decision: authorize recording this and similarly verified evaluator-only discrepancies while continuing, leaving all other scorers unchanged and still stopping for execution errors or substantive wrong answers; or retain separate serial gating for each. Developer asked in chat. Historical scores and all attempts remain intact; no additional generation allowed for Q1 under the three-attempt rule.

Evidence: frozen Step 1 questions[0].baselines.ollama and retained Step 8 ollama-q01-a1/a2/a3 results, manifests, traces and reviews. Step 8 remains incomplete.

## Step 8: substantive local Harriet hallucinations despite high judge scores

Status: awaiting developer decision, 2026-11-26. Ollama Q3–Q10 remain unstarted. This is outside the authorization for verified evaluator-only discrepancies.

Ollama Q2 exhausted all three permitted attempts: correctness 1.0/0.925/0.95; latencies 59.88/83.44/67.28 seconds. Every answer correctly says Harriet is alive but adds materially false unsupported details. Attempt 1 calls Gottfried her uncle and invents a plan to frame Henrik. Attempt 2 says Martin was her uncle and held her captive for decades. Attempt 3 says Martin imprisoned her for decades until her later escape/rescue, although its E3 explicitly says he did not know what had happened to his sister. Citation support is 0.5. The correctness judge's high scores do not establish factual acceptance. All graph executions and trace checks complete; attempts 1/2 reach budget handoff and attempt3 passes the existing conditional verification/text route. No supported orchestration mismatch was identified, and prompts/verification/evidence-selection policies remain preserved.

Required decision: authorize recording this substantive validation failure and continuing the remaining eight local questions, or investigate changes to preserved answering behavior. Developer notified in chat. No fourth generation attempt is allowed under the existing three-attempt agreement. Provisionally retain attempt1 as highest numeric correctness with its own latency, but do not mark it factually accepted or hide the failure behind aggregate correctness.

Evidence: retained Step 8 ollama-q02-a1/a2/a3 results, manifests, live traces and manual reviews; especially attempt3 output.evidence E3 versus output.answer. Historical local baseline/model/evaluator differences remain as recorded in Step1. Step8 is incomplete; Step9 and deployment have not started.
