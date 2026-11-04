# Sources for the adapters and estimates (read 2026-10-26)

Read during this session with the web fetch tool. These are documentation statements, not test results. No endpoint was called.

| Provider | Page | What was used | Gaps |
|---|---|---|---|
| Anthropic | Messages API and Vision guide (docs.claude.com) | `POST /v1/messages`; `x-api-key` and `anthropic-version: 2023-06-01` headers; image content block with a base64 source, placed before the text block; `max_tokens`; response `content[].text`, `stop_reason` (`end_turn`, `max_tokens`, `stop_sequence`, `refusal`), `usage`; image tokens ⌈w/28⌉ × ⌈h/28⌉; standard resize threshold 1,568 px (a higher tier for newer models) | Behaviour of the specific model chosen at execution |
| OpenAI | Images and vision guide (developers.openai.com) | Chat Completions `image_url` with a data URL; `detail` levels `low`, `high`, `original`, `auto` (documented default `auto`); `max_completion_tokens`; a 30,000-patch rejection limit per image; Responses API `input_image` as an alternative | The per-model sizing table was cut off in the fetched copy, so image token cost for the chosen model is unknown |
| Ollama | API reference (`/api/chat`, `/api/show`) | `messages[].images` as base64; `stream: false`; `options.num_predict`, `num_ctx`, `temperature`, `seed`; response `message.content`, `done_reason`, `prompt_eval_count`, `eval_count`, load and total durations in ns; `/api/show` lists model capabilities | Which installed model accepts images; it is checked only when the founder releases the local machine |

Before execution, re-read these pages for any change since 2026-10-26, and record the dates read in the run manifest notes.
