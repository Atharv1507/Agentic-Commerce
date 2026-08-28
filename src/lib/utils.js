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
