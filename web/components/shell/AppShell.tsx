"use client";

import {
  BarChart3,
  Bell,
  BookUser,
  Check,
  GitCompare,
  Inbox,
  Menu,
  Search,
  Sparkles,
  X,
  type LucideIcon,
  Network,
  SlidersHorizontal,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { cx } from "@/lib/format";

import { useRole, type Role } from "./RoleContext";
import { useSignals } from "./Signals";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  roles: Role[];
  badge?: "changes" | "sources";
}

const NAV: NavItem[] = [
  { href: "/", label: "Ask", icon: Search, roles: ["processor", "owner"] },
  { href: "/changes", label: "Changes", icon: Bell, roles: ["processor", "owner"], badge: "changes" },
  { href: "/sources", label: "Sources", icon: Upload, roles: ["owner"], badge: "sources" },
  { href: "/conflicts", label: "Conflicts", icon: GitCompare, roles: ["owner"] },
  { href: "/review", label: "Review queue", icon: Inbox, roles: ["owner"] },
  { href: "/setup", label: "Setup", icon: SlidersHorizontal, roles: ["owner"] },
  { href: "/entities", label: "Entities", icon: Network, roles: ["owner"] },
  { href: "/capture", label: "Expert capture", icon: BookUser, roles: ["processor", "owner"] },
  { href: "/analytics", label: "Analytics", icon: BarChart3, roles: ["owner"] },
];

const ROLE_LABEL: Record<Role, string> = { processor: "Processor", owner: "Process owner" };

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

function BrandGlyph() {
  return (
    <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-rose-tint text-rose">
      <Sparkles className="h-[18px] w-[18px]" aria-hidden />
    </span>
  );
}

function RoleMenu({ placement }: { placement: "rail" | "bar" }) {
  const { role, setRole } = useRole();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Signed in as ${ROLE_LABEL[role]}. Switch role`}
        className="flex h-9 w-9 items-center justify-center rounded-full border border-hairline bg-fill font-display text-xs font-semibold text-ink hover:border-muted"
      >
        {role === "owner" ? "PO" : "PR"}
      </button>
      {open && (
        <div
          role="menu"
          className={cx(
            "absolute z-50 w-52 rounded-2xl border border-hairline bg-surface p-1.5 shadow-card",
            placement === "rail" ? "bottom-0 left-12" : "right-0 top-11",
          )}
        >
          <p className="eyebrow px-2.5 pb-1 pt-1.5">View as</p>
          {(["processor", "owner"] as Role[]).map((r) => (
            <button
              key={r}
              role="menuitemradio"
              aria-checked={role === r}
              type="button"
              onClick={() => {
                setRole(r);
                setOpen(false);
              }}
              className="flex w-full items-center justify-between rounded-xl px-2.5 py-2 text-left text-sm font-medium text-ink hover:bg-fill"
            >
              {ROLE_LABEL[r]}
              {role === r && <Check className="h-4 w-4 text-ink" aria-hidden />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function NavLinks({ items, pathname, layout, onNavigate }: {
  items: NavItem[];
  pathname: string;
  layout: "rail" | "list";
  onNavigate?: () => void;
}) {
  const { unseen, attention } = useSignals();
  const counts = { changes: unseen.length, sources: attention };
  return (
    <>
      {items.map((item) => {
        const active = isActive(pathname, item.href);
        const Icon = item.icon;
        const count = item.badge ? counts[item.badge] : 0;
        const label = count ? `${item.label} (${count} new)` : item.label;
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            aria-label={layout === "rail" ? label : undefined}
            title={layout === "rail" ? label : undefined}
            className={cx(
              "relative flex items-center rounded-xl transition-colors",
              layout === "rail" ? "h-10 w-10 justify-center" : "gap-3 px-3 py-2.5 text-sm font-medium",
              active ? "text-ink" : "text-muted hover:bg-fill hover:text-ink",
              active && layout === "list" && "bg-fill",
            )}
          >
            {active && layout === "rail" && (
              <span className="absolute -left-[12px] top-2 h-6 w-[2px] rounded-full bg-rose" aria-hidden />
            )}
            <span className="relative">
              <Icon className="h-5 w-5" aria-hidden />
              {count > 0 && (
                <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-rose ring-2 ring-surface" aria-hidden />
              )}
            </span>
            {layout === "list" && (
              <span className="flex flex-1 items-center justify-between">
                {item.label}
                {count > 0 && <span className="font-mono text-[11px] text-muted">{count}</span>}
              </span>
            )}
          </Link>
        );
      })}
    </>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { role } = useRole();
  const items = NAV.filter((n) => n.roles.includes(role));
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-[1440px]">
      {/* Left nav rail, md and up */}
      <nav
        aria-label="Main"
        className="sticky top-0 hidden h-screen w-16 shrink-0 flex-col items-center border-r border-hairline bg-surface py-4 md:flex"
      >
        <Link href="/" aria-label="Ask — home" className="mb-6">
          <BrandGlyph />
        </Link>
        <div className="flex flex-col items-center gap-1.5">
          <NavLinks items={items} pathname={pathname} layout="rail" />
        </div>
        <div className="mt-auto">
          <RoleMenu placement="rail" />
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar below md */}
        <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b border-hairline bg-surface px-4 md:hidden">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              className="flex h-9 w-9 items-center justify-center rounded-xl text-ink hover:bg-fill"
            >
              {menuOpen ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
            </button>
            <Link href="/" className="flex items-center gap-2">
              <BrandGlyph />
              <span className="font-display text-[15px] font-semibold">Knowledge Engine</span>
            </Link>
          </div>
          <RoleMenu placement="bar" />
        </header>
        {menuOpen && (
          <nav id="mobile-nav" aria-label="Main" className="border-b border-hairline bg-surface px-3 py-2 md:hidden">
            <NavLinks items={items} pathname={pathname} layout="list" onNavigate={() => setMenuOpen(false)} />
          </nav>
        )}
        {children}
      </div>
    </div>
  );
}
