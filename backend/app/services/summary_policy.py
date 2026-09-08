"""Summary display policy, independent of original-file access permissions."""

# L1 stays public; L5 retains its existing access policy. Never use this set to
# decide original-file grants or original-chunk access.
REDACTED_SUMMARY_LEVELS = frozenset({"L2", "L3", "L4"})
