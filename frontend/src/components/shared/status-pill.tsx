import {
  CircleCheckBig,
  CircleDashed,
  CircleX,
  LoaderCircle,
  Megaphone,
  PencilLine,
  type LucideIcon,
} from "lucide-react";
import { STATUS_TONE, TONE_STYLE, type OperationalStatus } from "@/design/tokens";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

/** READY and NOTIFIED share green, so their icons differ: selected vs. delivered. */
const STATUS_ICON: Record<OperationalStatus, LucideIcon> = {
  DRAFT: PencilLine,
  READY: CircleDashed,
  PENDING: LoaderCircle,
  NOTIFIED: CircleCheckBig,
  ISSUED: Megaphone,
  FAILED: CircleX,
};

const STATUS_DESCRIPTION: Record<OperationalStatus, string> = {
  DRAFT: "Saved, not issued. Nothing has been sent.",
  READY: "Selected and ready. Nothing has been sent yet.",
  PENDING: "Delivery in progress.",
  NOTIFIED: "Accepted for delivery by the provider.",
  ISSUED: "Issued to the public. An issued alert cannot be changed.",
  FAILED: "Delivery failed.",
};

export interface StatusPillProps {
  status: OperationalStatus;
  /** Extra context shown on hover/focus, e.g. a channel's failure reason from the API. */
  detail?: string | null;
  className?: string;
}

/**
 * Alert and delivery status (§4.3): READY / NOTIFIED / PENDING / FAILED / DRAFT / ISSUED,
 * colour-mapped through STATUS_TONE and always labelled with the status word and an icon.
 */
export function StatusPill({ status, detail, className }: StatusPillProps) {
  const Icon = STATUS_ICON[status];
  const description = detail
    ? `${STATUS_DESCRIPTION[status]} ${detail}`
    : STATUS_DESCRIPTION[status];
  const pill = (
    <span
      data-slot="status-pill"
      data-status={status}
      title={detail ? undefined : description}
      className={cn(
        "inline-flex h-6 w-fit shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-[0.6875rem] font-semibold tracking-wide whitespace-nowrap uppercase [&_svg]:size-3.5",
        TONE_STYLE[STATUS_TONE[status]].subtle,
        className,
      )}
    >
      <Icon
        aria-hidden="true"
        strokeWidth={2.25}
        className={cn(status === "PENDING" && "animate-spin")}
      />
      {status}
      <span className="sr-only">. {description}</span>
    </span>
  );
  if (!detail) return pill;
  // Only pills with a detail (e.g. a FAILED channel's reason) become tab stops with a tooltip,
  // so a table of statuses doesn't add a dozen focus stops.
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        {/* A focusable wrapper so keyboard users get the tooltip too. */}
        <span
          tabIndex={0}
          className="inline-flex rounded-full outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          {pill}
        </span>
      </TooltipTrigger>
      <TooltipContent aria-hidden="true">{description}</TooltipContent>
    </Tooltip>
  );
}
