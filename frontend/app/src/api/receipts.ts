import { api } from "./client";
import type { Receipt, ReceiptUploadTicket } from "./types";

export const receiptsApi = {
  requestUpload: (params: { filename: string; contentType: string; byteSize: number; financialAccountId?: string }) =>
    api.post<ReceiptUploadTicket>("/receipts/upload/", {
      filename: params.filename,
      content_type: params.contentType,
      byte_size: params.byteSize,
      financial_account_id: params.financialAccountId ?? null,
    }),

  /** Direct PUT to the presigned URL — bytes never pass through our own API. */
  uploadToStorage: (uploadUrl: string, file: Blob, contentType: string) =>
    fetch(uploadUrl, { method: "PUT", headers: { "Content-Type": contentType }, body: file }),

  /** `imageBase64` is only needed when `uploadUrl` was null (local dev
   * without presigning) — the server writes the bytes itself in that case. */
  confirmUpload: (receiptId: string, imageBase64?: string) =>
    api.post<Receipt>(`/receipts/${receiptId}/confirm-upload/`, {
      image_base64: imageBase64 ?? null,
    }),

  detail: (receiptId: string) => api.get<Receipt>(`/receipts/${receiptId}/`),

  queue: () => api.get<Receipt[]>("/receipts/queue/"),

  confirmFields: (
    receiptId: string,
    fields: { merchant?: string; amountMinor?: number; occurredOn?: string; categoryId?: string },
  ) =>
    api.patch<Receipt>(`/receipts/${receiptId}/fields/`, {
      merchant: fields.merchant,
      amount_minor: fields.amountMinor,
      occurred_on: fields.occurredOn,
      category_id: fields.categoryId,
    }),

  link: (receiptId: string, financialAccountId: string, categoryId: string) =>
    api.post<{ transaction_id: string; receipt: Receipt }>(`/receipts/${receiptId}/link/`, {
      financial_account_id: financialAccountId,
      category_id: categoryId,
    }),

  discard: (receiptId: string) => api.post<Receipt>(`/receipts/${receiptId}/discard/`, {}),
};

/** Read a File/Blob as base64, without the data-URL prefix — used only for
 * the local-dev fallback path where no presigned URL is available. */
export function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.split(",")[1] ?? "");
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
