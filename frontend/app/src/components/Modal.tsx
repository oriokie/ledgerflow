/** Back-compat shim: the canonical Modal now lives in the ui/ library.
 * Existing pages import from here; new code should import from "../ui". */
export { Modal } from "../ui/Modal";
