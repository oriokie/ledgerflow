/**
 * Authenticated file download.
 *
 * A plain `<a href download>` sends no `Authorization` header and no
 * `X-Tenant-ID`, so every export link in the app returned 401 — and, in
 * development where no Vite proxy exists, silently saved Vite's index.html
 * under the report's filename instead.
 *
 * Fetching the blob through the API client carries the auth headers, honours
 * the 401-refresh-retry path, and lets us surface a real error instead of
 * handing the user a corrupt file.
 */
import { getBlob } from "../api/client";

export async function downloadFile(path: string, filename: string): Promise<void> {
  const blob = await getBlob(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Without this the object URL — and the whole blob — leaks until page unload.
  URL.revokeObjectURL(url);
}
