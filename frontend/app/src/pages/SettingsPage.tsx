import { Navigate, Route, Routes } from "react-router-dom";
import { PageHeader } from "../ui";
import {
  IntelligencePanel,
  PreferencesPanel,
  ProfilePanel,
  SecurityPanel,
  SettingsNav,
  TaxonomyPanel,
  WorkspacePanel,
} from "./settings";

/**
 * Settings shell: a persistent grouped nav beside a panel outlet. Each section
 * is its own route (/settings/<slug>) so it's linkable and the surface never
 * shows everything at once.
 */
export function SettingsPage() {
  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Settings"
        description="How LedgerFlow looks and behaves for you in this workspace."
        illustration="adjust"
      />
      <div className="lf-settings-layout">
        <SettingsNav />
        <div className="lf-settings-content">
          <Routes>
            <Route index element={<Navigate to="profile" replace />} />
            <Route path="profile" element={<ProfilePanel />} />
            <Route path="security" element={<SecurityPanel />} />
            <Route path="preferences" element={<PreferencesPanel />} />
            <Route path="workspace" element={<WorkspacePanel />} />
            <Route path="taxonomy" element={<TaxonomyPanel />} />
            <Route path="intelligence" element={<IntelligencePanel />} />
            <Route path="*" element={<Navigate to="profile" replace />} />
          </Routes>
        </div>
      </div>
    </>
  );
}
