import type { LucideIcon } from "lucide-react";
import { ACTION_ICONS, actionIconKey } from "@/design/icons";
import { typography } from "@/design/tokens";
import { cn } from "@/lib/utils";

export interface ActionListItemProps {
  index: number;
  text: string;
  icon?: LucideIcon;
  className?: string;
}

/** One numbered recommended-action row with an icon (§4.3). */
export function ActionListItem({ index, text, icon, className }: ActionListItemProps) {
  const Icon = icon ?? ACTION_ICONS[actionIconKey(text)];
  return (
    <li
      data-slot="action-item"
      className={cn("flex items-start gap-3 rounded-lg border bg-card px-3 py-2.5", className)}
    >
      <span
        aria-hidden="true"
        className="tabular grid size-6 shrink-0 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
      >
        {index}
      </span>
      <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
      <span className={cn(typography.body, "min-w-0")}>{text}</span>
    </li>
  );
}

export interface ActionListProps {
  /** `recommended_actions` from the API, in order (Part 07 §3: deterministic). */
  actions: string[];
  limit?: number;
  className?: string;
}

/** The numbered "Recommended Authority Actions" list used by the dashboard and Prediction page. */
export function ActionList({ actions, limit, className }: ActionListProps) {
  const shown = actions.slice(0, limit ?? actions.length);
  return (
    <ol className={cn("flex flex-col gap-2", className)} aria-label="Recommended actions">
      {shown.map((text, i) => (
        <ActionListItem key={`${i}-${text}`} index={i + 1} text={text} />
      ))}
    </ol>
  );
}
