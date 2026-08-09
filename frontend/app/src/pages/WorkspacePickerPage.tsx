import { zodResolver } from "@hookform/resolvers/zod";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { ApiError } from "../api/client";
import { tenancyApi } from "../api/tenancy";
import { useAuth } from "../lib/AuthContext";
import { AuthLayout } from "../components/auth/AuthLayout";
import { Banner, Button, Grid, Heading, Inline, Input, Select, Stack, Text } from "../ui";

/** Below this count the list is a glance; a search box would be clutter for
 * the common case of 1-3 workspaces. Past it (an advisor with several
 * clients, a family with several households) it earns its keep. */
const FILTER_THRESHOLD = 5;

const schema = z.object({
  name: z.string().min(1, "Give this workspace a name."),
  // "Couple" and "Family" are UI-only distinctions — the backend's TenantType
  // has no matching values (only personal / household / organization), and
  // nothing in the product actually branches on the difference between a
  // couple and a family. Submitting "couple" or "family" directly used to
  // hit a clean 400 from DRF's ChoiceField ("couple" is not a valid choice"),
  // surfaced as an unhelpful raw validation message — from the user's side,
  // picking either option and submitting just failed. Mapped to "household"
  // at submission time in onSubmit below, so the two more relatable labels
  // stay in the picker without inventing backend values nothing reads.
  type: z.enum(["personal", "couple", "family"]),
  base_currency: z.string().length(3, "Use a 3-letter currency code, e.g. USD."),
});
type FormValues = z.infer<typeof schema>;

const BACKEND_TYPE: Record<FormValues["type"], "personal" | "household"> = {
  personal: "personal",
  couple: "household",
  family: "household",
};

export function WorkspacePickerPage() {
  const { workspaces, switchWorkspace, refreshWorkspaces } = useAuth();
  // Derived, not captured. `useState(workspaces.length === 0)` runs its
  // initialiser only on the first render, so mounting while the session was
  // still bootstrapping (workspaces still empty) latched "creating" on
  // permanently — the picker then showed the create form forever, however
  // many workspaces arrived afterwards, and creating one more never escaped
  // it. `null` means "no explicit choice yet, follow the data".
  const [creatingOverride, setCreatingOverride] = useState<boolean | null>(null);
  const creating = creatingOverride ?? workspaces.length === 0;
  const setCreating = setCreatingOverride;
  const [serverError, setServerError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const filteredWorkspaces = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return workspaces;
    return workspaces.filter((ws) => ws.tenant.name.toLowerCase().includes(query));
  }, [filter, workspaces]);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { type: "personal", base_currency: "USD" },
  });

  // Reachable two ways: ProtectedRoute sends here when there's no active
  // workspace at all, and the AppShell's "+ New workspace" link sends here
  // deliberately even with one already active — so this never auto-redirects
  // away just because an active workspace exists.

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    try {
      const workspace = await tenancyApi.createWorkspace({
        ...values,
        type: BACKEND_TYPE[values.type],
      });
      await refreshWorkspaces();
      switchWorkspace(workspace.tenant.id);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.detail : "Couldn't create the workspace. Please try again.");
    }
  });

  return (
    <AuthLayout maxWidth={440} illustration="welcome">
      {workspaces.length > 0 && !creating ? (
        <Stack gap={2}>
          <Heading level={1}>Choose a workspace</Heading>
          {workspaces.length > FILTER_THRESHOLD && (
            <Input
              leading={<Search size={16} strokeWidth={1.8} aria-hidden="true" />}
              type="search"
              placeholder="Search workspaces"
              aria-label="Search workspaces"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          )}
          {filteredWorkspaces.map((ws) => (
            <button
              key={ws.tenant.id}
              type="button"
              className="lf-workspace-menu-item"
              style={{ padding: 12, border: "1px solid var(--lf-border-subtle)", borderRadius: 10 }}
              onClick={() => switchWorkspace(ws.tenant.id)}
            >
              {ws.tenant.name}
              <Text tone="secondary" size="sm" as="span" style={{ display: "block" }}>
                {ws.tenant.base_currency} &middot; {ws.role}
              </Text>
            </button>
          ))}
          {filteredWorkspaces.length === 0 && (
            <Text tone="secondary" size="sm">
              No workspaces match &ldquo;{filter}&rdquo;.
            </Text>
          )}
          <Button variant="ghost" onClick={() => setCreating(true)}>
            + New workspace
          </Button>
        </Stack>
      ) : (
        <form onSubmit={onSubmit} noValidate>
          <Stack gap={4}>
            <div>
              <Heading level={1}>
                {workspaces.length === 0 ? "Create your first workspace" : "New workspace"}
              </Heading>
              <Text tone="secondary" size="sm" style={{ marginTop: "var(--lf-space-2)" }}>
                A workspace holds one set of accounts, budgets, and goals — use separate ones for personal
                finances vs. a shared household.
              </Text>
            </div>

            <Input
              label="Workspace name"
              placeholder="e.g. Personal, The Rivera Household"
              error={errors.name?.message}
              {...register("name")}
            />

            <Grid cols={2} gap={4}>
              <Select
                label="Type"
                options={[
                  { value: "personal", label: "Personal" },
                  { value: "couple", label: "Couple" },
                  { value: "family", label: "Family" },
                ]}
                {...register("type")}
              />
              <Input
                label="Base currency"
                maxLength={3}
                error={errors.base_currency?.message}
                {...register("base_currency")}
              />
            </Grid>

            {serverError && <Banner tone="danger">{serverError}</Banner>}

            <Inline gap={2}>
              <Button type="submit" variant="primary" loading={isSubmitting}>
                Create workspace
              </Button>
              {workspaces.length > 0 && (
                <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                  Cancel
                </Button>
              )}
            </Inline>
          </Stack>
        </form>
      )}
    </AuthLayout>
  );
}
