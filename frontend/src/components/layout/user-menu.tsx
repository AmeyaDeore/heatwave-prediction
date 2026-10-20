import { LogIn, LogOut, Monitor, Moon, Palette, Sun, UserRound } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api/endpoints";
import { useSession } from "@/state/session-context";
import { useTheme, type ThemePreference } from "@/state/theme-context";

const NAV_BUTTON = "text-nav-foreground hover:bg-nav-accent hover:text-nav-foreground";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

/** Sign in, or the signed-in official's menu; theme choice lives here for both. */
export function UserMenu() {
  const { user, isAuthenticated, requestSignIn, signOut, token } = useSession();

  /** Revoke the token on the server (Part 15 R2), then end the session here either way. */
  async function signOutEverywhere() {
    if (token) await api.logout({ token }).catch(() => undefined);
    signOut("signed_out");
  }
  const { preference, setPreference } = useTheme();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        {isAuthenticated && user ? (
          <Button
            variant="ghost"
            size="sm"
            className={NAV_BUTTON}
            aria-label={`Account: ${user.display_name}`}
          >
            <span className="grid size-6 place-items-center rounded-full bg-nav-foreground text-[0.625rem] font-bold text-nav">
              {initials(user.display_name) || <UserRound className="size-3.5" />}
            </span>
            <span className="hidden max-w-32 truncate lg:inline">{user.display_name}</span>
          </Button>
        ) : (
          <Button
            variant="ghost"
            size="icon-sm"
            className={NAV_BUTTON}
            aria-label="Account and display settings"
          >
            <UserRound aria-hidden="true" />
          </Button>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        {isAuthenticated && user ? (
          <DropdownMenuLabel className="flex flex-col gap-0.5">
            <span>{user.display_name}</span>
            <span className="text-xs font-normal text-muted-foreground">
              {user.username} · {user.role}
            </span>
          </DropdownMenuLabel>
        ) : (
          <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">
            Viewing as guest. Sign in to issue alerts.
          </DropdownMenuLabel>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs font-medium text-muted-foreground">
          Theme
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(v) => setPreference(v as ThemePreference)}
        >
          <DropdownMenuRadioItem value="light">
            <Sun aria-hidden="true" /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">
            <Moon aria-hidden="true" /> Dark
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor aria-hidden="true" /> Match system
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/design-system">
            <Palette aria-hidden="true" /> Design system
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {isAuthenticated ? (
          <DropdownMenuItem onSelect={() => void signOutEverywhere()}>
            <LogOut aria-hidden="true" /> Sign out
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onSelect={requestSignIn}>
            <LogIn aria-hidden="true" /> Sign in
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
