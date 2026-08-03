import { useEffect, useState, type Dispatch, type SetStateAction } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Opens a page-level surface (a create modal, an import dialog) when the URL
 * carries a flag — e.g. `/budgets?add=1`.
 *
 * This is what makes command-palette actions honest: "Create budget" navigates
 * to the budgets page *and* opens the form, instead of dropping the user on a
 * page and leaving them to find the button. It also makes every create surface
 * linkable and shareable.
 *
 * The flag is consumed on mount — stripped from the URL with a `replace` so it
 * never lands in history. Without that, a refresh or a Back would silently
 * reopen a form the user had already dismissed.
 *
 * @param param  Query-string key to watch.
 * @param value  Value that counts as "on".
 * @returns The usual `[open, setOpen]` pair — a drop-in for `useState(false)`,
 *          updater callbacks included.
 */
export function useOpenOnParam(
  param = "add",
  value = "1",
): [boolean, Dispatch<SetStateAction<boolean>>] {
  const [searchParams, setSearchParams] = useSearchParams();
  const [open, setOpen] = useState(() => searchParams.get(param) === value);

  useEffect(() => {
    if (searchParams.get(param) !== value) return;
    setOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete(param);
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams, param, value]);

  return [open, setOpen];
}
