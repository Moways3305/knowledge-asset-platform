import type { NamingFields } from "../../types/ingest";
import type { NamingOptionDTO } from "../../types/naming";

export interface NamingCategorySuggestion {
  id: string;
  basis: "ai" | "only_option" | "manual";
}

export function suggestNamingCategory(
  naming: NamingFields | null | undefined,
  categories: NamingOptionDTO[],
  ruleVersion?: number | null,
): NamingCategorySuggestion | null {
  const suggestion = naming?.category_suggestion;
  if (!suggestion?.suggested_category_id || suggestion.status !== "classified") return null;
  if (ruleVersion != null && suggestion.candidate_rule_revision !== ruleVersion) return null;
  if (!categories.some((category) => category.id === suggestion.suggested_category_id)) return null;
  if (
    suggestion.category_source === "ai_content" &&
    (suggestion.category_confidence === "high" || suggestion.category_confidence === "medium")
  ) {
    return { id: suggestion.suggested_category_id, basis: "ai" };
  }
  if (suggestion.category_source === "rule_only_option") {
    return { id: suggestion.suggested_category_id, basis: "only_option" };
  }
  if (suggestion.category_source === "manual") {
    return { id: suggestion.suggested_category_id, basis: "manual" };
  }
  return null;
}
