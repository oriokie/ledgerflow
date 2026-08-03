import { Eye, FileText, Image as ImageIcon, Paperclip, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { attachmentsApi } from "../../api/finance";
import { useTransactionAttachments, useUploadReceipt } from "../../hooks/useFinance";
import { Banner, Button, Spinner, Text } from "../../ui";

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function FileGlyph({ contentType }: { contentType: string }) {
  if (contentType.startsWith("image/")) return <ImageIcon size={16} strokeWidth={1.8} aria-hidden="true" />;
  if (contentType === "application/pdf") return <FileText size={16} strokeWidth={1.8} aria-hidden="true" />;
  return <Paperclip size={16} strokeWidth={1.8} aria-hidden="true" />;
}

/** Receipts for a transaction: existing attachments (viewable) plus an upload
 * dropzone. Upload prefers a presigned direct-to-storage PUT and transparently
 * falls back to streaming through our API when the backend can't presign. */
export function ReceiptManager({ txnId }: { txnId: string }) {
  const { data: attachments } = useTransactionAttachments(txnId);
  const upload = useUploadReceipt(txnId);
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewingId, setViewingId] = useState<string | null>(null);

  const handleFile = async (file: File | undefined) => {
    if (!file) return;
    setError(null);
    try {
      await upload.mutateAsync(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    }
  };

  const view = async (attachmentId: string) => {
    setError(null);
    setViewingId(attachmentId);
    try {
      const blob = await attachmentsApi.download(attachmentId);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank", "noopener");
      // Revoke shortly after so the new tab has time to load it.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't open the receipt.");
    } finally {
      setViewingId(null);
    }
  };

  return (
    <div>
      <p className="lf-label">Receipts</p>

      {attachments && attachments.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--lf-space-2)", marginBottom: "var(--lf-space-3)" }}>
          {attachments.map((a) => (
            <div key={a.id} className="lf-receipt-item">
              <span className="lf-receipt-thumb">
                <FileGlyph contentType={a.content_type} />
              </span>
              <div className="lf-receipt-main">
                <div className="lf-cell-primary" style={{ fontSize: "var(--lf-text-sm)" }}>
                  {a.content_type || "File"}
                </div>
                <div className="lf-cell-meta">
                  {formatBytes(a.byte_size)} · {a.status}
                </div>
              </div>
              {a.status === "uploaded" && (
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Eye size={15} strokeWidth={1.8} />}
                  loading={viewingId === a.id}
                  onClick={() => view(a.id)}
                >
                  View
                </Button>
              )}
            </div>
          ))}
        </div>
      )}

      <div
        className="lf-receipt-drop"
        data-drag={dragging}
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          handleFile(e.dataTransfer.files?.[0]);
        }}
      >
        {upload.isPending ? (
          <>
            <Spinner />
            <Text tone="tertiary" size="sm">
              Uploading…
            </Text>
          </>
        ) : (
          <>
            <UploadCloud size={22} strokeWidth={1.6} aria-hidden="true" />
            <Text tone="tertiary" size="sm">
              Drop a receipt here, or click to upload (PDF or image).
            </Text>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          accept="image/*,application/pdf"
          hidden
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
      </div>

      {error && (
        <div style={{ marginTop: "var(--lf-space-3)" }}>
          <Banner tone="warning">{error}</Banner>
        </div>
      )}
    </div>
  );
}
