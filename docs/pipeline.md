# Pipeline, metrics, Phase 3

## Target

**99.999% attack detection with under 0.02% false positives.** Not expected at first. First goal: hit
these numbers consistently on the held-out set. Then improve each iteration, add detection of novel
attacks, and reduce rules where better classifier weights allow.

## Stages (order decided by measurement, not assumption)

normalize (unicode, homoglyphs, zero-width, common encodings) -> NLP and regex -> activation probe ->
system one models (Clef, Laya, Mica, Maya, d1, plus decision models found in the inventory).
Jev is out of scope until later.

- NLP is expected to matter more than regex. Use both to avoid extra inference passes.
- Decide how a long prompt or context is broken down so attacks can be located.
- Log per-stage scores in the run manifest.
- A control change merges only if held-out detection improves and false positives stay low.

## Statistics

Report confidence intervals and sample sizes with every rate, and state the attack distribution the
numbers apply to. Rule of thumb: claiming a 0.02% false-positive rate at 95% confidence needs about
15,000 benign held-out prompts with no false positives; 99.999% detection needs about 300,000 attacks
with no misses.

## Phase 3 (not before the pipeline is good)

Weight-space programming and fine-tuning, using Phase 1 activation data, to potentially consolidate
the rule set. Order: probes, activation steering, weight edits. Judge every edit by the same held-out
metrics. Treat downloaded checkpoints as untrusted.
