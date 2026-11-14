import { useEffect, useState } from "react";

export type Route =
  | { view: "intro" }
  | { view: "runs" }
  | { view: "run"; id: string }
  | { view: "stats" }
  | { view: "how" };

export function parseHash(hash: string): Route {
  const h = hash.replace(/^#\/?/, ""), parts = h.split("/");
  if (parts[0] === "runs") return { view: "runs" };
  if (parts[0] === "run" && parts[1]) return { view: "run", id: decodeURIComponent(parts[1]) };
  if (parts[0] === "stats") return { view: "stats" };
  if (parts[0] === "how") return { view: "how" };
  return { view: "intro" };
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(location.hash));
  useEffect(() => {
    const on = () => { setRoute(parseHash(location.hash)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

/** Query-string flags (?mock=1, ?at=, ?pause=, ?speed=, ?open=). */
export const query = new URLSearchParams(location.search);
export const MOCK = query.get("mock") === "1";
