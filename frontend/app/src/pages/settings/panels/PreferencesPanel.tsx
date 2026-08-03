import {
  ACCENTS,
  FONT_FAMILIES,
  FONT_SIZES,
  useAccent,
  useDensity,
  useFontFamily,
  useFontSize,
  type Density,
  type FontFamily,
  type FontSize,
} from "../../../lib/appearance";
import { useFlag } from "../../../lib/featureFlags";
import { useTheme, type Theme } from "../../../lib/useTheme";
import { SegmentedControl, Switch, Text } from "../../../ui";
import { SettingsRow, SettingsSection } from "../components";
import { NotificationPreferencesSection } from "../NotificationPreferences";
import { PushToggle } from "../PushToggle";

export function PreferencesPanel() {
  return (
    <>
      <NavigationSection />
      <AppearanceSection />
      <SettingsSection title="Notifications" description="Alerts even when LedgerFlow isn't open.">
        <SettingsRow
          title="Push notifications"
          description="Budget alerts, bill reminders, and goal milestones — sent to this device."
        >
          <PushToggle />
        </SettingsRow>
        <NotificationPreferencesSection />
      </SettingsSection>
    </>
  );
}

function AppearanceSection() {
  const { theme, setTheme } = useTheme();
  const { accent, setAccent } = useAccent();
  const { density, setDensity } = useDensity();
  const { fontFamily, setFontFamily } = useFontFamily();
  const { fontSize, setFontSize } = useFontSize();

  return (
    <SettingsSection title="Appearance" description="How LedgerFlow looks on this device.">
      <SettingsRow title="Theme" description="Follow your system, or lock to a light or dark look.">
        <SegmentedControl
          legend="Theme"
          value={theme}
          onChange={(v) => setTheme(v as Theme)}
          options={[
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
            { value: "system", label: "System" },
          ]}
        />
      </SettingsRow>

      <SettingsRow title="Accent color" description="Colors every button, link, and highlight.">
        <div className="lf-accent-swatches" role="radiogroup" aria-label="Accent color">
          {ACCENTS.map((a) => (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={accent === a.id}
              aria-label={a.label}
              title={a.label}
              className="lf-accent-swatch"
              style={{ ["--swatch" as string]: a.swatch }}
              onClick={() => setAccent(a.id)}
            />
          ))}
        </div>
      </SettingsRow>

      <SettingsRow title="Font" description="Grotesk is LedgerFlow's own voice; System and Serif are easy alternatives.">
        <SegmentedControl
          legend="Font family"
          value={fontFamily}
          onChange={(v) => setFontFamily(v as FontFamily)}
          options={FONT_FAMILIES.map((f) => ({ value: f.id, label: f.label }))}
        />
      </SettingsRow>

      <SettingsRow title="Text size" description="Scales all text and spacing together.">
        <SegmentedControl
          legend="Text size"
          value={fontSize}
          onChange={(v) => setFontSize(v as FontSize)}
          options={FONT_SIZES.map((f) => ({ value: f.id, label: f.label }))}
        />
      </SettingsRow>

      <SettingsRow title="Density" description="Compact tightens spacing to fit more on screen.">
        <SegmentedControl
          legend="Density"
          value={density}
          onChange={(v) => setDensity(v as Density)}
          options={[
            { value: "comfortable", label: "Comfortable" },
            { value: "compact", label: "Compact" },
          ]}
        />
      </SettingsRow>
    </SettingsSection>
  );
}

/**
 * The Phase 5 navigation, opt-in.
 *
 * An IA change is the one kind of redesign that reliably breaks people who
 * already know the product — someone who has used `/bills` for a year does not
 * want to find out it is a tab now. So it ships as a switch they choose, and
 * can un-choose, rather than as something that happens to them.
 *
 * Old URLs keep working either way: with this on they redirect to their new
 * home with the right tab already selected.
 */
function NavigationSection() {
  const [navV2, setNavV2] = useFlag("navV2");

  return (
    <SettingsSection
      title="Navigation"
      description="How LedgerFlow is organised. This is a preview — you can switch back at any time."
    >
      <SettingsRow
        title="Simplified navigation"
        description="Groups the sidebar into 8 destinations instead of 21, and shows live figures beside them. Budgets, Bills, Recurring and Cash flow become tabs of one Plan screen; Coach, Trends and Reports become tabs of Insights."
      >
        <Switch
          checked={navV2}
          onChange={(e) => setNavV2(e.target.checked)}
          label="Simplified navigation"
        />
      </SettingsRow>

      <Text tone="tertiary" size="xs">
        Your existing links and bookmarks keep working — they redirect to the matching tab.
      </Text>
    </SettingsSection>
  );
}
