import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fileToBase64, receiptsApi } from "../api/receipts";
import { useAuth } from "../lib/AuthContext";

const KEY = "receipts";

export function useReceiptQueue() {
  const { activeWorkspace } = useAuth();
  return useQuery({
    queryKey: [KEY, "queue", activeWorkspace?.tenant.id],
    queryFn: () => receiptsApi.queue(),
    enabled: !!activeWorkspace,
  });
}

export function useReceipt(receiptId: string | null) {
  return useQuery({
    queryKey: [KEY, receiptId],
    queryFn: () => receiptsApi.detail(receiptId!),
    enabled: !!receiptId,
  });
}

/**
 * The full capture-to-upload flow in one mutation: request a presigned URL,
 * PUT the image bytes to storage, confirm. Presented as one step to the
 * caller because that is genuinely one user action ("I took a photo") even
 * though it is three network calls — splitting it into separate hooks would
 * just move the sequencing bug surface into every screen that uses it.
 */
export function useCaptureReceipt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (file: Blob) => {
      const ticket = await receiptsApi.requestUpload({
        filename: `receipt-${Date.now()}.jpg`,
        contentType: file.type || "image/jpeg",
        byteSize: file.size,
      });

      if (ticket.upload_url) {
        await receiptsApi.uploadToStorage(ticket.upload_url, file, file.type || "image/jpeg");
        return receiptsApi.confirmUpload(ticket.id);
      }
      // Local dev without a presigning-capable storage backend: send the
      // bytes through the API itself rather than leaving the receipt stuck.
      const base64 = await fileToBase64(file);
      return receiptsApi.confirmUpload(ticket.id, base64);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}

export function useConfirmReceiptFields() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      receiptId,
      fields,
    }: {
      receiptId: string;
      fields: Parameters<typeof receiptsApi.confirmFields>[1];
    }) => receiptsApi.confirmFields(receiptId, fields),
    onSuccess: (_data, { receiptId }) => {
      queryClient.invalidateQueries({ queryKey: [KEY, receiptId] });
      queryClient.invalidateQueries({ queryKey: [KEY, "queue"] });
    },
  });
}

export function useLinkReceipt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      receiptId,
      financialAccountId,
      categoryId,
    }: {
      receiptId: string;
      financialAccountId: string;
      categoryId: string;
    }) => receiptsApi.link(receiptId, financialAccountId, categoryId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: [KEY] });
      queryClient.invalidateQueries({ queryKey: ["transactions"] });
    },
  });
}

export function useDiscardReceipt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (receiptId: string) => receiptsApi.discard(receiptId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [KEY] }),
  });
}
