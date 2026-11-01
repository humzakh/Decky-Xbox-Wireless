import { findInReactTree } from "@decky/ui";
import { routerHook } from "@decky/api";
import { ReactElement, ReactNode } from "react";

const SETTINGS_ROUTE = "/settings";
// how many wrapper components (other plugins, Decky) to look through for the page list
const MAX_DEPTH = 4;

// returns the sidebar's new page list
type SidebarEdit = (pages: any[]) => any[];

const routeOf = (p: any): string | null => (typeof p?.route === "string" ? p.route : null);

const edits = new Set<SidebarEdit>();
let removePatch: (() => void) | null = null;

/**
 * Patches Steam's Settings so each `edits` entry can change its sidebar pages. Steam's settings
 * component returns `<Sidebar title pages={[{title, icon, route, content}]}/>`, so each render
 * we rewrite `pages`. If a Steam update changes that shape, or anything here throws, Settings
 * renders untouched.
 */
function installPatch() {
  const wrapped = new WeakMap<object, (props: object) => ReactNode>();
  let warned = false;

  // true once the sidebar was found, so wrapping stops going deeper
  const editSidebar = (ret: any) => {
    try {
      const sidebar = findInReactTree(ret, (x) => Array.isArray(x?.pages) && x.pages.some(routeOf));
      if (!sidebar) return false;
      let pages = sidebar.pages;
      for (const edit of edits) pages = edit(pages);
      sidebar.pages = pages;
      return true;
    } catch (e) {
      if (!warned) console.warn("[Xbox Wireless] couldn't change the settings pages", e);
      warned = true;
      return true;
    }
  };

  // returns a cached wrapper so React sees a stable component type
  const wrap = (type: any, depth: number): any => {
    if (typeof type !== "function" || type.prototype?.isReactComponent) return type;
    let w = wrapped.get(type);
    if (!w) {
      w = (props: object) => {
        const ret = type(props);
        if (!editSidebar(ret) && depth < MAX_DEPTH && ret?.type) {
          return { ...ret, type: wrap(ret.type, depth + 1) };
        }
        return ret;
      };
      wrapped.set(type, w);
    }
    return w;
  };

  const patch = routerHook.addPatch(SETTINGS_ROUTE, (route: any) => {
    const child = route.children as ReactElement | undefined;
    if (child?.type) route.children = { ...child, type: wrap(child.type, 0) };
    return route;
  });
  return () => routerHook.removePatch(SETTINGS_ROUTE, patch);
}

function addSidebarEdit(edit: SidebarEdit) {
  edits.add(edit);
  removePatch ??= installPatch();
  return () => {
    edits.delete(edit);
    if (edits.size === 0) {
      removePatch?.();
      removePatch = null;
    }
  };
}

/** Swaps the content of one of Steam's own Settings pages, picked by route prefix. */
export function patchSettingsPage(route: string, patchContent: (content: ReactElement) => ReactElement) {
  return addSidebarEdit((pages) =>
    pages.map((p) => (routeOf(p)?.startsWith(route) && p?.content ? { ...p, content: patchContent(p.content) } : p)),
  );
}
