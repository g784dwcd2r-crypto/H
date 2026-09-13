export type LaunchRegion = "US" | "UK" | "EU" | "AU" | "ROW";
export const launchRegions: { value: LaunchRegion; label: string }[] = [
  { value: "US", label: "United States" }, { value: "UK", label: "United Kingdom" },
  { value: "EU", label: "Europe" }, { value: "AU", label: "Australia" },
  { value: "ROW", label: "Rest of the world" },
];
export type Campaign = {
  id: string; opens_at: string; registration_closes_at: string;
  benefit_starts_at: string; benefit_ends_at: string;
  capacity: number; allocated: number; remaining: number; state: "open" | "full" | "closed";
  individual_accounts: boolean; auto_charge: boolean; ai_allowance: string;
};
export type Membership = {
  status: "reserved" | "waitlisted"; position: number; region: LaunchRegion;
  joined_at: string; benefit_starts_at: string | null; benefit_ends_at: string | null;
};
export type LaunchMembership = {
  campaign: Campaign; membership: Membership | null;
  entitlement: { active: boolean; phase: "none" | "upcoming" | "active" | "expired"; plan: string | null; starts_at: string | null; ends_at: string | null };
};
