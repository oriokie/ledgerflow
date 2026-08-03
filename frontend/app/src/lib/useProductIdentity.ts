import { useEffect } from "react";

/**
 * Marks which product the user is currently inside.
 *
 * Sets `data-product` on `<html>` rather than a class on a shell element,
 * because `<dialog>` promotes to the top layer and portalled content escapes
 * any subtree: an operator opening a confirm dialog in the console must not
 * find the customer app's identity staring back from it.
 *
 * The cleanup matters as much as the effect. Without it, an operator who
 * leaves the console keeps the console's palette in their own workspace —
 * which inverts the whole point of having two identities, because now the
 * *customer* app is the one wearing the control room's clothes.
 */
export function useProductIdentity(product: string | null): void {
  useEffect(() => {
    if (!product) return;
    const previous = document.documentElement.dataset.product;
    document.documentElement.dataset.product = product;
    return () => {
      if (previous) document.documentElement.dataset.product = previous;
      else delete document.documentElement.dataset.product;
    };
  }, [product]);
}
