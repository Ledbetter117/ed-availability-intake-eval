"""mmeval: multi-model comparison layer for the ED availability-intake evaluation (candidate r6).

config     explicit provider / endpoint / modality / data-class configuration and its validation
transport  deny-by-default transport, an offline recorded double, and the gated HTTP transport
adapters   request builders and response parsers (Anthropic Messages, OpenAI Chat Completions, Ollama chat)
casesets   case identities, duplicate and split checks, render / reference agreement
runner     manifest, plan, append-only attempt ledger, bounded retries, resume, dispatch gate, dry-run packet
replay     offline replay of stored responses; import of the historical v1 raw folders
report     accounting, unchanged historic metrics, extended metrics, paired document-level comparisons
"""
VERSION = "r6-candidate-2026-10-26"
