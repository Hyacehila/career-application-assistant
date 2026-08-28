import { useEffect, useRef, useSyncExternalStore } from "react";

const MOBILE_MEDIA_QUERY = "(max-width: 767px)";

function queryMatches(query: string): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  try {
    return window.matchMedia(query).matches;
  } catch {
    return false;
  }
}

export function isNarrowScreen(): boolean {
  return queryMatches(MOBILE_MEDIA_QUERY);
}

export function useIsMobile(): boolean {
  const listenersRef = useRef(new Set<() => void>());

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }
    const mediaQuery = window.matchMedia(MOBILE_MEDIA_QUERY);
    const notify = () => {
      listenersRef.current.forEach((listener) => listener());
    };
    mediaQuery.addEventListener("change", notify);
    return () => {
      mediaQuery.removeEventListener("change", notify);
    };
  }, []);

  const subscribe = (callback: () => void) => {
    listenersRef.current.add(callback);
    return () => {
      listenersRef.current.delete(callback);
    };
  };

  const getSnapshot = () => queryMatches(MOBILE_MEDIA_QUERY);
  const getServerSnapshot = () => false;

  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
