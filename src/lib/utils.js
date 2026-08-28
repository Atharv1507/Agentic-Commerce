import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

export const DEFAULT_ASSISTANT_NAME = "Shopper Agent";

// Two-letter initials to match the avatar circle's original "SA" sizing —
// one word from a custom name (e.g. "Nova") takes its first two letters,
// multiple words (e.g. "Shopper Agent") take one letter from each.
export function getAssistantInitials(name) {
  const trimmed = (name || DEFAULT_ASSISTANT_NAME).trim();
  const words = trimmed.split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return trimmed.slice(0, 2).toUpperCase();
}

// The catalogue's size rail, smallest first. Fixed rather than derived from a
// product so every rail lines up: a garment that skips XS shows a gap at XS
// instead of shifting M into its place.
export const SIZE_ORDER = ["XS", "S", "M", "L", "XL", "XXL"];

/** Sizes this product can actually be bought in right now. */
export function availableSizes(product) {
  if (product?.available_sizes) return product.available_sizes;
  const sizes = product?.sizes;
  if (!sizes) return [];
  return SIZE_ORDER.filter((size) => (sizes[size] ?? 0) > 0);
}

/**
 * Which size to add a product to the cart in, given no explicit choice.
 *
 * The shopper's own size when it's in stock, otherwise the smallest size that
 * is. Falling back rather than refusing keeps a one-click add working, and the
 * cart shows the chosen size as an editable control — so a fallback is visible
 * and one tap from being corrected, never a silent substitution at checkout.
 *
 * Returns null only when the product is sold out in every size, which is the
 * one case where there is nothing honest to add.
 */
export function resolveCartSize(product, userSize) {
  const stocked = availableSizes(product);
  if (!stocked.length) return null;
  if (userSize && stocked.includes(userSize)) return userSize;
  return stocked[0];
}

/** Identity of a cart line: a product in a size, not just a product. */
export function cartLineKey(item) {
  return `${item.id}::${item.size || ""}`;
}
