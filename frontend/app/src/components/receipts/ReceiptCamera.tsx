import { Camera, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Text } from "../../ui";

interface ReceiptCameraProps {
  onCapture: (file: Blob) => void;
  onClose: () => void;
}

/**
 * A live in-app camera for photographing a receipt.
 *
 * `getUserMedia` is the primary path: it keeps someone inside the app rather
 * than bouncing them out to the OS camera app and back, and lets the capture
 * be tuned for a receipt specifically (rear camera, a document-shaped guide
 * frame) rather than a generic photo.
 *
 * It is not the only path. `getUserMedia` requires a secure context and
 * camera permission, both of which can fail or simply be declined — the
 * component falls back to a native `<input type="file" accept="image/*"
 * capture="environment">` in that case, which still opens the device camera
 * on essentially every mobile browser without needing any JavaScript camera
 * API at all. Camera scanning degrades to file picking; it never simply
 * breaks.
 */
export function ReceiptCamera({ onCapture, onClose }: ReceiptCameraProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const stopStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("no-camera-api");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1920 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        setReady(true);
      } catch {
        // Permission denied, no camera present, insecure context — any of
        // these land here, and the file-input fallback covers all of them
        // identically rather than needing to distinguish the cause.
        setError("permission-or-unavailable");
      }
    }

    start();
    return () => {
      cancelled = true;
      stopStream();
    };
  }, [stopStream]);

  // A full-screen overlay is a modal in every sense that matters, so it needs
  // the same treatment AppShell gives its nav drawer: Escape to leave, focus
  // moved in on open, focus handed back on close, and background scroll
  // locked. Without focus moving in, a keyboard or screen-reader user is
  // stranded on whatever button opened the camera — a control now buried
  // behind an overlay they have no way of knowing they're inside.
  useEffect(() => {
    const returnFocusTo = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    // Focus the close control specifically: it's the one action guaranteed to
    // exist in both the live-camera and file-fallback views, and "how do I get
    // out of this" is the first thing someone needs when a full-screen
    // overlay appears unannounced.
    closeRef.current?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        stopStream();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKey);
      returnFocusTo?.focus?.();
    };
  }, [onClose, stopStream]);

  const capture = useCallback(() => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;

    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(video, 0, 0);

    canvas.toBlob(
      (blob) => {
        if (blob) {
          stopStream();
          onCapture(blob);
        }
      },
      "image/jpeg",
      0.85,
    );
  }, [onCapture, stopStream]);

  const handleFileChosen = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (file) onCapture(file);
    },
    [onCapture],
  );

  if (error) {
    return (
      <div className="lf-camera-fallback">
        <button
          ref={closeRef}
          type="button"
          className="lf-camera-close"
          onClick={onClose}
          aria-label="Close receipt capture"
        >
          <X size={18} aria-hidden="true" />
        </button>
        <Camera size={32} strokeWidth={1.5} aria-hidden="true" />
        <Text tone="secondary" size="sm">
          {error === "no-camera-api"
            ? "In-app camera isn't available here."
            : "Couldn't access the camera."}{" "}
          Choose a photo instead.
        </Text>
        <Button variant="primary" onClick={() => fileInputRef.current?.click()}>
          Choose photo
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="lf-visually-hidden"
          onChange={handleFileChosen}
          aria-label="Receipt photo"
        />
      </div>
    );
  }

  return (
    <div className="lf-camera" role="dialog" aria-modal="true" aria-label="Photograph a receipt">
      <video ref={videoRef} className="lf-camera-video" playsInline muted autoPlay />

      {/* A document-shaped guide, not a functional crop — it only helps
          someone frame the receipt; capture always takes the full frame. */}
      {ready && <div className="lf-camera-guide" aria-hidden="true" />}

      <button
        ref={closeRef}
        type="button"
        className="lf-camera-close"
        onClick={() => {
          stopStream();
          onClose();
        }}
        aria-label="Cancel"
      >
        <X size={18} aria-hidden="true" />
      </button>

      <div className="lf-camera-controls">
        {/* Plain span, not <Text>: the design system's tone scale is for
            content on the app's own surfaces, and this overlays live camera
            video — it needs its own fixed contrast treatment regardless of
            theme, in lf-camera.css. */}
        <span className="lf-camera-hint">Fit the whole receipt in the frame</span>
        <button
          type="button"
          className="lf-camera-shutter"
          onClick={capture}
          disabled={!ready}
          aria-label="Take photo"
        >
          <span className="lf-camera-shutter-ring" />
        </button>
        <button
          type="button"
          className="lf-camera-switch"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Choose a photo instead"
        >
          <RotateCcw size={16} aria-hidden="true" />
        </button>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="lf-visually-hidden"
        onChange={handleFileChosen}
        aria-label="Receipt photo"
      />
    </div>
  );
}
