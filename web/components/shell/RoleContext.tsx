"use client";

import { createContext, useContext, useEffect, useState } from "react";

import { safeStorageGet, safeStorageSet } from "@/lib/format";

export type Role = "processor" | "owner";

const KEY = "ps07.role";

interface RoleState {
  role: Role;
  setRole: (r: Role) => void;
  userId: string;
}

const RoleContext = createContext<RoleState>({ role: "processor", setRole: () => {}, userId: "demo-user" });

// No real auth for the MVP (DESIGN.md §3): the role lives in localStorage.
export function RoleProvider({ children }: { children: React.ReactNode }) {
  const [role, setRoleState] = useState<Role>("processor");
  const [userId, setUserId] = useState("demo-user");

  useEffect(() => {
    const stored = safeStorageGet(KEY);
    if (stored === "owner" || stored === "processor") setRoleState(stored);
    let id = safeStorageGet("ps07.user");
    if (!id) {
      id = `user-${Math.random().toString(36).slice(2, 10)}`;
      safeStorageSet("ps07.user", id);
    }
    setUserId(id);
  }, []);

  const setRole = (r: Role) => {
    setRoleState(r);
    safeStorageSet(KEY, r);
  };

  return <RoleContext.Provider value={{ role, setRole, userId }}>{children}</RoleContext.Provider>;
}

export const useRole = () => useContext(RoleContext);
