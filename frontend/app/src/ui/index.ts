/**
 * LedgerFlow UI component library.
 *
 * A typed, documented React layer over the CSS design system (tokens +
 * components.css). Pages import from here — `import { Button, Card, FormField }
 * from "@/ui"` — instead of hand-writing `.lf-*` class strings and inline
 * styles. Every component references design tokens only; theming (incl. dark
 * mode) flows through automatically.
 *
 * Grouping:
 *   Layout       Stack, Inline, Grid, Divider, Spacer
 *   Typography   Heading, Text, Eyebrow, PageHeader
 *   Actions      Button, IconButton
 *   Forms        FormField, Input, Textarea, Select, Switch, Checkbox,
 *                SegmentedControl
 *   Containers   Card, CardHeader, Badge, Chip
 *   Overlays     Modal
 *   Data         Table (+ Column type), Meter, Money, Figure, FigureRow
 *   Feedback     Banner, Spinner, Skeleton, SkeletonCard, LoadingBlock,
 *                EmptyState
 *   Navigation   Tabs
 */

// Layout
export { Stack, Inline, Grid, Divider, Spacer } from "./Layout";

// Typography
export { Heading, Text, Eyebrow, PageHeader } from "./Typography";

// Actions
export { Button, IconButton } from "./Button";
export { ConfirmAction } from "./ConfirmAction";

// Forms
export { FormField, Input, Textarea, Select } from "./Field";
export { PasswordInput } from "./PasswordInput";
export { Switch, Checkbox, SegmentedControl } from "./Toggle";

// Containers
export { Card, CardHeader, Badge, Chip } from "./Card";

// Overlays
export { Modal } from "./Modal";

// Data display
export { Table } from "./Table";
export type { Column, SortDirection } from "./Table";
export { Meter } from "./Meter";
export { Figure, FigureRow } from "./Figure";
export type { Certainty, FigureSize, FigureTone, FigureProps } from "./Figure";
export { Money } from "../components/Money";

// Feedback
export { Banner, Spinner, Skeleton, SkeletonCard, LoadingBlock } from "./Feedback";
export { EmptyState } from "./EmptyState";

// Navigation
export { Tabs } from "./Tabs";
export type { TabItem } from "./Tabs";
export { ToastProvider } from "./Toast";
export { useToast } from "./toastContext";
export type { ToastOptions } from "./toastContext";
