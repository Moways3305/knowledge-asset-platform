# Governed directories and WorkBuddy retrieval

KAP directory membership is a single stable `directory_key` stored on the current formal asset
version. Display paths are derived at read time. A project path uses the current project name;
the project code remains naming metadata and is never a directory locator.

WorkBuddy exposes two read-only operations:

- `kap_list_knowledge_directories()` resolves authorized stable keys and display paths. It returns
  no asset counts and no directories for projects outside the bound user's active memberships or
  registration ceiling.
- `kap_search_knowledge(..., directory_key?, project_id?)` accepts an exact key returned by that
  catalog. The gateway validates scope/project consistency and applies the registration ceiling,
  real-time access decisions, confidentiality and AI-access rules. Candidate document IDs are
  constrained before semantic Top-K recall.

When a user explicitly names a directory, the connector must resolve the key first and then use it
as a hard filter. For a general topical request it must search broadly and may use directory labels
only as explanatory metadata; it must not guess a key. `personal.pending` is processing state, not
formal knowledge, and is excluded from platform and Agent retrieval.

Legacy category metadata is mapped only when an explicit mapping yields one unique directory.
Ambiguous or unknown history remains `未分类 / 待治理`; no file is moved, deleted, or silently
assigned by this compatibility behavior.
