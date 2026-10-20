import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge must know the custom type scale (globals.css @theme: --text-meta/metric/
 * display); otherwise it reads `text-meta` as a colour and drops it when a `text-tone-*`
 * colour follows, silently losing the font size.
 */
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ["meta", "metric", "display"] } },
});

/** Merge class names, letting later Tailwind utilities override earlier ones. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
