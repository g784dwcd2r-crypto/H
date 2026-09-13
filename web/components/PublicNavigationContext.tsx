"use client";

import { createContext, useContext } from "react";

type PublicNavigationState = {
  active: string | null;
  toggle: (id: string, trigger: HTMLButtonElement) => void;
  close: (restoreFocus?: boolean) => void;
};

export const PublicNavigationContext = createContext<PublicNavigationState | null>(null);
export const usePublicNavigation = () => useContext(PublicNavigationContext);
