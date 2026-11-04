# Dataset approvals (ticket 0005)

Decisions against the attack taxonomy in docs/datasets.md. Licenses read from Hugging Face dataset
cards on 2026-11-04; the loader re-checks the card at download and stops if it changed. Raw files
live under `/mnt/storage/llm_security/raw/` (not in git). Total raw budget: 10 GB.

| Source | License | Use | Why |
|---|---|---|---|
| deepset/prompt-injections | Apache-2.0 | approve | direct injections + benign, small, widely cited baseline |
| jackhhao/jailbreak-classification | Apache-2.0 | approve | known jailbreaks vs benign |
| TrustAIRLab/in-the-wild-jailbreak-prompts | MIT | approve | real named jailbreaks (named_jailbreak), plus regular prompts as benign |
| Lakera/gandalf_ignore_instructions | MIT | approve | direct override attempts from a live game |
| reshabhs/SPML_Chatbot_Prompt_Injection | MIT | approve | injections against system-prompted chatbots, with benign |
| microsoft/llmail-inject-challenge | MIT | approve, subset ≤50k | email channel (indirect injection) |
| JailbreakBench/JBB-Behaviors | MIT | approve as red-team seeds only | behaviors, not prompts; never scored as attacks |
| databricks/databricks-dolly-15k | CC-BY-SA-3.0 | approve, benign | instructions incl. long context/summarize; share-alike: cite, keep license |
| OpenAssistant/oasst2 | Apache-2.0 | approve, benign | multi_turn benign conversations |
| jayavibhav/prompt-injection | none on card | reject | no license; cannot publish or verify |
| xTRam1/safe-guard-prompt-injection | none on card | reject | no license |
| qxcv/tensor-trust | none on card | hold | useful hijack/extraction data; revisit if license found |
| allenai/wildjailbreak | ODC-BY, gated | hold | needs HF login; revisit for novel jailbreaks |
| local eval harness files | unknown | reject for ingestion | task results, not labeled prompts; email-suite design is a reference for generation |

Gaps no public source fills: long context, document, tool output, code comments, hard negatives,
payload splitting, many-shot. These come from the red team (Maya) and are approved by the evaluator.
Publishable: only the approved sources, under their licenses; generated data after evaluator review.
