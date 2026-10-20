import { useId, type ReactNode } from "react";
import { typography } from "@/design/tokens";
import { cn } from "@/lib/utils";

export interface PanelProps {
  title: string;
  description?: ReactNode;
  /** DataSourceTag(s) beside the title ("DEMO DATA", "AI EXPLAINED"). */
  tags?: ReactNode;
  /** Right-aligned header controls (a link, a period selector, a refresh button). */
  action?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}

/**
 * The standard card every page panel uses ("Regional Heatwave Risk", "Why this prediction?",
 * "Alert Distribution", …), so header layout, padding and tags are identical everywhere.
 * Rendered as a <section> labelled by its title, so screen-reader users can jump between panels.
 */
export function Panel({
  title,
  description,
  tags,
  action,
  footer,
  children,
  className,
  contentClassName,
}: PanelProps) {
  const id = useId();
  return (
    <section
      data-slot="panel"
      aria-labelledby={id}
      className={cn(
        "flex min-w-0 flex-col rounded-xl border bg-card text-card-foreground shadow-xs",
        className,
      )}
    >
      {/* A div, not <header>: inside a page, several panel headers must not read as extra
          banner landmarks (the shell's top bar is the one banner). Same for the footer. */}
      <div
        data-slot="panel-header"
        className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-5 pt-5"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id={id} className={typography.sectionTitle}>
              {title}
            </h2>
            {tags}
          </div>
          {description && <p className={typography.secondary}>{description}</p>}
        </div>
        {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
      </div>
      <div className={cn("flex-1 p-5", contentClassName)}>{children}</div>
      {footer && (
        <div data-slot="panel-footer" className="border-t px-5 py-3 text-xs text-muted-foreground">
          {footer}
        </div>
      )}
    </section>
  );
}

export interface PageHeaderProps {
  title: string;
  subtitle?: string;
  /** Usually the current region; rendered as a quiet chip after the subtitle. */
  context?: ReactNode;
  actions?: ReactNode;
}

/** Page title block (§4.2 type scale), shared by Parts 11–14. */
export function PageHeader({ title, subtitle, context, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="flex min-w-0 flex-col gap-1.5">
        <h1 className={typography.pageTitle}>{title}</h1>
        {(subtitle || context) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {subtitle && <p className={typography.pageSubtitle}>{subtitle}</p>}
            {context}
          </div>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
