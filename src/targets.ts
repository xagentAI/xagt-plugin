export type InstallTargetId =
  | "cursor"
  | "claude-code"
  | "codex"
  | "opencode"
  | "generic";

export type TargetSelector = InstallTargetId | "all";

export interface InstallTarget {
  id: InstallTargetId;
  label: string;
  base: "cwd" | "home";
  skillsDirectory: string;
  notes: string;
}

export const SUPPORTED_TARGETS: readonly InstallTarget[] = [
  {
    id: "cursor",
    label: "Cursor project skill",
    base: "cwd",
    skillsDirectory: ".cursor/skills",
    notes: "Installs the skills into the current workspace for Cursor."
  },
  {
    id: "claude-code",
    label: "Claude Code user skill",
    base: "home",
    skillsDirectory: ".claude/skills",
    notes: "Installs the skills into the Claude-compatible user skill directory."
  },
  {
    id: "codex",
    label: "Codex CLI user skill",
    base: "home",
    skillsDirectory: ".codex/skills",
    notes: "Installs the skills into the OpenAI Codex CLI user skill directory."
  },
  {
    id: "opencode",
    label: "OpenCode user skill",
    base: "home",
    skillsDirectory: ".config/opencode/skills",
    notes: "Installs the skills into the OpenCode user skill directory."
  },
  {
    id: "generic",
    label: "AgentSkills-compatible user skill",
    base: "home",
    skillsDirectory: ".agents/skills",
    notes: "Installs into the AgentSkills-compatible user directory used by OpenClaw and similar runtimes."
  }
];

export function isTargetSelector(value: string): value is TargetSelector {
  return value === "all" || SUPPORTED_TARGETS.some((target) => target.id === value);
}

export function planInstallTargets(selector: TargetSelector): InstallTarget[] {
  if (selector === "all") {
    return [...SUPPORTED_TARGETS];
  }

  return SUPPORTED_TARGETS.filter((target) => target.id === selector);
}
