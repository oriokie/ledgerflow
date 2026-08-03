import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReceiptCamera } from "./ReceiptCamera";

function fakeStream() {
  const track = { stop: vi.fn() };
  return { getTracks: () => [track], _track: track } as unknown as MediaStream;
}

function stubGetUserMedia(impl: (...args: unknown[]) => Promise<MediaStream>) {
  Object.defineProperty(navigator, "mediaDevices", {
    value: { getUserMedia: vi.fn(impl) },
    configurable: true,
  });
}

const originalMediaDevices = navigator.mediaDevices;

beforeEach(() => {
  // jsdom's <video> never actually plays or reports dimensions; stubbed so
  // the component's own logic (not video decoding) is what's under test.
  HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
});

afterEach(() => {
  Object.defineProperty(navigator, "mediaDevices", {
    value: originalMediaDevices,
    configurable: true,
  });
  vi.restoreAllMocks();
});

describe("ReceiptCamera", () => {
  it("requests the rear camera, not the front-facing one", async () => {
    const getUserMedia = vi.fn().mockResolvedValue(fakeStream());
    Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });

    render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);

    await waitFor(() =>
      expect(getUserMedia).toHaveBeenCalledWith(
        expect.objectContaining({ video: expect.objectContaining({ facingMode: "environment" }) }),
      ),
    );
  });

  it("stops the camera stream when the user cancels", async () => {
    const stream = fakeStream();
    stubGetUserMedia(() => Promise.resolve(stream));
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<ReceiptCamera onCapture={vi.fn()} onClose={onClose} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onClose).toHaveBeenCalled();
    expect((stream as unknown as { _track: { stop: ReturnType<typeof vi.fn> } })._track.stop).toHaveBeenCalled();
  });

  it("falls back to a file picker when getUserMedia is unavailable", async () => {
    // No navigator.mediaDevices at all — an insecure context, or a browser
    // that never implemented the API. Camera scanning must degrade, not break.
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });

    render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);

    expect(await screen.findByText(/isn't available here/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /choose photo/i })).toBeInTheDocument();
  });

  it("falls back to a file picker when the user declines camera permission", async () => {
    stubGetUserMedia(() => Promise.reject(new DOMException("denied", "NotAllowedError")));

    render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);

    expect(await screen.findByText(/couldn't access the camera/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /choose photo/i })).toBeInTheDocument();
  });

  it("passes a chosen file straight to onCapture", async () => {
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
    const onCapture = vi.fn();
    const user = userEvent.setup();

    render(<ReceiptCamera onCapture={onCapture} onClose={vi.fn()} />);
    await screen.findByRole("button", { name: /choose photo/i });

    const file = new File(["fake-image-bytes"], "receipt.jpg", { type: "image/jpeg" });
    const input = screen.getByLabelText(/receipt photo/i) as HTMLInputElement;
    await user.upload(input, file);

    expect(onCapture).toHaveBeenCalledWith(file);
  });

  it("offers a close control even before the camera resolves", async () => {
    // A slow permission prompt must not trap someone in the camera view with
    // no way out.
    stubGetUserMedia(() => new Promise(() => {})); // never resolves
    render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });

  it("the shutter is disabled until the stream is actually ready", async () => {
    stubGetUserMedia(() => new Promise(() => {}));
    render(<ReceiptCamera onCapture={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: /take photo/i })).toBeDisabled();
  });
});
