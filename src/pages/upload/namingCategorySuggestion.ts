import type { NamingFields } from "../../types/ingest";
import type { NamingOptionDTO } from "../../types/naming";

export interface NamingCategorySuggestion {
  id: string;
  basis: "ai" | "only_option";
}

function normalized(value: string | null | undefined): string {
  return (value ?? "").trim().replace(/\s+/g, " ").toLocaleLowerCase();
}

function uniqueMatch(
  categories: NamingOptionDTO[],
  predicate: (category: NamingOptionDTO) => boolean,
): NamingOptionDTO | null {
  const matches = categories.filter(predicate);
  return matches.length === 1 ? matches[0] : null;
}

export function suggestNamingCategory(
  naming: NamingFields | null | undefined,
  categories: NamingOptionDTO[],
): NamingCategorySuggestion | null {
  const primary = normalized(naming?.primary_category);
  const secondary = normalized(naming?.secondary_category);

  if (primary && secondary) {
    const exact = uniqueMatch(
      categories,
      (category) =>
        normalized(category.primary) === primary && normalized(category.secondary) === secondary,
    );
    if (exact) return { id: exact.id, basis: "ai" };
  }
  if (secondary) {
    const secondaryMatch = uniqueMatch(
      categories,
      (category) => normalized(category.secondary) === secondary,
    );
    if (secondaryMatch) return { id: secondaryMatch.id, basis: "ai" };
  }
  if (primary) {
    const primaryMatch = uniqueMatch(
      categories,
      (category) => normalized(category.primary) === primary,
    );
    if (primaryMatch) return { id: primaryMatch.id, basis: "ai" };
  }
  if (categories.length === 1) return { id: categories[0].id, basis: "only_option" };
  return null;
}
