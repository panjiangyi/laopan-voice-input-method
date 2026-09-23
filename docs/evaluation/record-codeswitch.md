# Independent mixed-language recordings

Corpus: `codeswitch-20260923.txt`, 20 original sentences.

Read naturally, using your usual English pronunciation. Do not read punctuation
aloud. Read API, HTTP and JSON the way you normally say them; do not change your
accent to accommodate the model. Leave about half a second before and after speech.
Do not use VoiceIME output as the reference transcript: keep the actual recording
and manually record any deviation from the supplied sentence.

Sentences 1–14 cover ordinary English, product names, technical vocabulary and
longer utterances. Sentences 15–16 are Chinese controls. Reserve sentences 17–20
for acceptance; do not add aliases or tune prompts from their recognition errors.
If those sentences influence tuning, they are no longer held out.

This corpus intentionally avoids ambiguous formatting requirements such as camel
case and unspoken underscores. Those require a separate formatting evaluation.

From the project root:

```bash
PROMPTS_FILE="$PWD/docs/evaluation/codeswitch-20260923.txt" \
SESSION_DIR="$PWD/samples/codeswitch-20260923" \
bash scripts/14-record-samples.sh
```

Enter starts each recording; Enter again stops it. At transcript confirmation,
Enter accepts the supplied text, `r` retries, and other text records what was
actually spoken. To resume at sentence 9, use the same environment variables and
append `12 9` to the command. Use a new session directory for a separate take.
