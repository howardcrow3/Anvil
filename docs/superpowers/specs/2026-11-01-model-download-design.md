# Model download / delete UI: design

Howard's decisions (2026-11-01): **only offer models that will work on this machine**; **Cancel cleans up after itself**.
Everything else follows the defaults agreed in chat.

## Behavior

1. **Fit filter.** A local catalog model is offered only if `min_ram_gb <= this machine's total RAM`
   (GB, rounded to nearest). Models that do not fit are omitted from `model.list`, so they appear in
   neither the chat picker nor Settings. Exceptions: a model that is already downloaded or currently
   downloading is always listed (so it can be used or deleted). If RAM cannot be detected, nothing is filtered.
   `model.download` re-checks and rejects a model that does not fit.
2. **Disk check.** Before the first byte is written, `download` requires free space in the models
   directory of at least (bytes still to fetch + 1 GiB). Otherwise it fails with a message giving needed vs free GB.
3. **Explicit download.** Nothing downloads unless the user clicks Download in Settings > Models, which shows the size.
4. **One download at a time.** The runtime rejects `model.download` while another is running; the UI disables other Download buttons with the reason.
5. **Progress.** Settings shows one bar per downloading model (GB done/total, speed, ETA), summed across shards.
   A window opened mid-download shows the bar, because `model.list` carries `progress` for downloading models.
6. **Cancel = clean up.** `model.cancel_download` stops the download and deletes everything for that model
   (`.part` files, finished shards, manifest). A *failed* download (error/network) keeps its partial files so Retry resumes.
7. **Delete.** Confirm dialog stating the space freed. Disabled with a reason for the active model or one that is downloading.
8. **Picker.** Fit-but-not-downloaded local models stay visible and disabled, labelled "(download in Settings)".

## Non-goals

HF token field (no catalog entry is gated today; `HF_TOKEN` env already works), parallel downloads,
stopping only the deleted model's server (existing `delete` stops all owned servers; unchanged).

## Protocol additions

- `model.list` local entries: `status` in `available | downloadable | downloading`, plus `progress?: {done, total}`, `download_gb` and `min_ram_gb`.
- `model.cancel_download {model_id}` -> `{status: "cancelled" | "not_downloading", model_id}`.
- `model.download_progress` notification gains `status: "cancelled"`.
